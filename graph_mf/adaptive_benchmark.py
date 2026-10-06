"""New timing calibration and held-out adaptive/fixed/exact request measurements."""
import json
import platform
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter
from . import __version__
from .adaptive import AdaptiveController, calibrate, save_profile, LEVELS, COUNTRIES, TIERS
from .backends import Neo4jBackend
from .benchmark import relative_error, write_csv
from .reusable import ReusableSample
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j, numpy


def summarize(rows, builds, stream_size):
    summary = []
    for mode in sorted({r['mode'] for r in rows}):
        selected = [r for r in rows if r['mode'] == mode]
        for tier in list(TIERS):
            subset = [r for r in selected if r['tier'] == tier]
            if not subset:
                continue
            # One sample is charged per standalone stream; exact mode has no sample cost.
            cost = mean(b['build_ms'] for b in builds) / stream_size if mode != 'exact' else 0
            summary.append(dict(mode=mode, tier=tier, requests=len(subset),
                request_ms_mean=mean(r['request_ms'] for r in subset),
                request_ms_p95=float(numpy().percentile([r['request_ms'] for r in subset], 95)),
                amortized_ms_mean=mean(r['request_ms'] for r in subset) + cost,
                node_error_mean=mean(r['node_error'] for r in subset),
                edge_error_mean=mean(r['edge_error'] for r in subset),
                budget_violation_rate=mean(r['budget_violation'] for r in subset),
                interval_miss_rate=mean(r['interval_miss'] for r in subset) if mode == 'adaptive' else None,
                approximate_requests=sum(r['fidelity'] < 1 for r in subset),
                approximate_interval_miss_rate=(mean(r['interval_miss'] for r in subset if r['fidelity'] < 1)
                    if mode == 'adaptive' and any(r['fidelity'] < 1 for r in subset) else None),
                count_pairs_mean=mean(r['queries'] for r in subset)))
    return summary


def run_adaptive_benchmark(backend_name='memory', nodes=50000, epochs=15,
                           repeats_per_tier=4, timing_epochs=5,
                           output='results/local/adaptive', fit_epochs=20, calibration_epochs=40,
                           cost_policy='amortized', evaluation_seed=5000,
                           baseline_fidelities=(0.1, 0.25, 0.5, 0.75)):
    if epochs < 2 or repeats_per_tier < 3 or timing_epochs < 2:
        raise ValueError('Use >=2 evaluation/timing epochs and >=3 requests per tier block')
    if (len(set(baseline_fidelities)) != len(baseline_fidelities)
            or any(not 0 < f < 1 for f in baseline_fidelities)):
        raise ValueError('Fixed approximate baselines must be unique fidelities in (0,1)')
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output folder must be new or empty')
    graph = generate_graph(nodes)
    profile = calibrate(graph, fit_epochs, calibration_epochs)
    timing_seeds = list(range(4000, 4000 + timing_epochs))
    if type(evaluation_seed) is not int or evaluation_seed < 0:
        raise ValueError('Evaluation seed must be a nonnegative integer')
    evaluation_seeds = list(range(evaluation_seed, evaluation_seed + epochs))
    splits = [profile['fitting_seeds'], profile['calibration_seeds'], timing_seeds, evaluation_seeds]
    if any(set(a) & set(b) for i, a in enumerate(splits) for b in splits[i + 1:]):
        raise ValueError('Fitting, calibration, timing and evaluation seeds must be disjoint')
    reference = SyntheticMemory(graph)
    truth = {c: reference.counts(c) for c in COUNTRIES}
    # Tightening is immediate; final relaxed block exercises delayed demotion.
    tier_sequence = ['performance', 'balanced', 'quality', 'performance', 'exact']
    stream_size = len(COUNTRIES) * len(tier_sequence) * repeats_per_tier
    output.mkdir(parents=True, exist_ok=True)
    metadata = dict(status='running', project_version=__version__, backend=backend_name,
        started_at=datetime.now(timezone.utc).isoformat(), graph_sha256=graph.fingerprint,
        dataset=graph.dataset, nodes=nodes, edge_records=len(graph.src), countries=COUNTRIES,
        levels=LEVELS, timing_seeds=timing_seeds, evaluation_seeds=evaluation_seeds,
        stream_requests_per_sample=stream_size, repeats_per_tier=repeats_per_tier,
        tier_sequence=tier_sequence, completed_evaluation_epochs=0,
        python=platform.python_version(), platform=platform.platform(),
        performance_benchmark_measured=backend_name == 'neo4j',
        latency_scope='complete controller request including all escalation queries, state checks and correction',
        amortization='full measured build charged to each standalone stream / requests in that stream',
        excluded_costs='graph import, connection, offline correction calibration and timing profiling; reported separately',
        workload='static graph; warm cache; serial client; five country predicates; one sample per epoch',
        validation='counts checked against NumPy, truth used only after returned estimates; disjoint sample seeds',
        cost_policy=cost_policy, baseline_fidelities=list(baseline_fidelities),
        generalization='new sample seeds on same graph/predicates; no graph/workload distribution shift claim')
    def checkpoint():
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    checkpoint()
    connection = None
    timing_rows, rows, builds, decisions = [], [], [], []
    try:
        start = perf_counter()
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            backend.seed()
            components, _, _ = connection.driver.execute_query(
                'CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition',
                database_=connection.database)
            metadata['server_components'] = [r.data() for r in components]
            settings, _, _ = connection.driver.execute_query(
                'SHOW SETTINGS YIELD name,value WHERE name IN $names RETURN name,value',
                names=['server.memory.heap.initial_size', 'server.memory.heap.max_size',
                       'server.memory.pagecache.size'], database_=connection.database)
            metadata['server_memory_settings'] = {r['name']: r['value'] for r in settings}
        elif backend_name == 'memory':
            backend = SyntheticMemory(graph)
        else:
            raise ValueError('Unknown backend')
        metadata['import_connect_ms'] = 1000 * (perf_counter() - start)
        cache = ReusableSample(backend)
        timing_builds = []
        start = perf_counter()
        for index, seed in enumerate(timing_seeds):
            timing_builds.append(cache.build(seed, refresh=True))
            reference.prepare(seed)
            for country in COUNTRIES:
                for f in LEVELS:
                    cache.counts(country, f)  # One untimed warmup per setting/epoch.
                for repeat in range(3):
                    order = list(LEVELS)
                    random.Random(seed + repeat).shuffle(order)
                    for f in order:
                        observed = cache.counts(country, f)
                        expected = reference.counts(country, f)
                        if any(observed[k] != expected[k] for k in ('node_count', 'edge_count')):
                            raise RuntimeError('Timing calibration count mismatch')
                        timing_rows.append(dict(seed=seed, country=country, fidelity=f,
                            repeat=repeat, request_ms=observed['request_ms'],
                            node_count=observed['node_count'], edge_count=observed['edge_count']))
            write_csv(output / 'timing-raw.csv', timing_rows)
            print(f'Timing calibration {index+1}/{timing_epochs}: all counts match', flush=True)
        metadata['timing_profiling_ms'] = 1000 * (perf_counter() - start)
        profile['build_ms_mean'] = mean(b['build_ms'] for b in timing_builds)
        profile['timing'] = {country: {str(f): dict(request_ms_mean=mean(
            r['request_ms'] for r in timing_rows if r['country'] == country and r['fidelity'] == f))
            for f in LEVELS} for country in COUNTRIES}
        save_profile(output / 'profile.json', profile)
        write_csv(output / 'timing-builds.csv', timing_builds)
        metadata['calibration_cpu_ms'] = profile['calibration_cpu_ms']
        metadata['fitting_seeds'] = profile['fitting_seeds']
        metadata['calibration_seeds'] = profile['calibration_seeds']
        checkpoint()
        for epoch, seed in enumerate(evaluation_seeds):
            build = cache.build(seed, refresh=True)
            builds.append(dict(epoch=epoch, **build))
            reference.prepare(seed)
            controllers = {c: AdaptiveController(profile, cost_policy=cost_policy) for c in COUNTRIES}
            for country in COUNTRIES:
                for f in LEVELS:
                    cache.counts(country, f)
            for block, tier in enumerate(tier_sequence):
                for repeat in range(repeats_per_tier):
                    country_order = list(COUNTRIES)
                    random.Random(seed + block * 100 + repeat).shuffle(country_order)
                    for country in country_order:
                        modes = ['adaptive', 'exact'] + [f'fixed-{f}' for f in baseline_fidelities]
                        random.Random(seed + block * 100 + repeat + COUNTRIES.index(country)).shuffle(modes)
                        for mode in modes:
                            if mode == 'adaptive':
                                result = controllers[country].request(cache, country, tier,
                                                                     reuse_requests=stream_size)
                                # Validate every actual escalation count without supplying truth to controller.
                                for step in result['steps']:
                                    expected = reference.counts(country, step['fidelity'])
                                    if any(step[k] != expected[k] for k in ('node_count', 'edge_count')):
                                        raise RuntimeError('Adaptive escalation count mismatch')
                                decisions.append(dict(epoch=epoch, seed=seed, block=block,
                                    repeat=repeat, **result))
                            else:
                                f = 1.0 if mode == 'exact' else float(mode.split('-')[1])
                                observed = cache.counts(country, f)
                                expected = reference.counts(country, f)
                                if any(observed[k] != expected[k] for k in ('node_count', 'edge_count')):
                                    raise RuntimeError('Held-out baseline count mismatch')
                                result = dict(fidelity=f, request_ms=observed['request_ms'], queries=1,
                                    node_estimate=observed['node_count']/f,
                                    edge_estimate=observed['edge_count']/f**2,
                                    node_bound=0 if f == 1 else None, edge_bound=0 if f == 1 else None,
                                    node_budget=TIERS[tier][0], edge_budget=TIERS[tier][1])
                            node_error = relative_error(result['node_estimate'], truth[country]['node_count'])
                            edge_error = relative_error(result['edge_estimate'], truth[country]['edge_count'])
                            interval_miss = (node_error > result['node_bound'] or edge_error > result['edge_bound']) if mode == 'adaptive' else None
                            rows.append(dict(epoch=epoch, seed=seed, country=country, block=block,
                                repeat=repeat, mode=mode, tier=tier, fidelity=result['fidelity'],
                                request_ms=result['request_ms'], queries=result['queries'],
                                node_estimate=result['node_estimate'], edge_estimate=result['edge_estimate'],
                                node_error=node_error, edge_error=edge_error,
                                node_budget=result['node_budget'], edge_budget=result['edge_budget'],
                                budget_violation=node_error > result['node_budget'] or edge_error > result['edge_budget'],
                                interval_miss=interval_miss))
            metadata['completed_evaluation_epochs'] = epoch + 1
            write_csv(output / 'raw-results.csv', rows)
            write_csv(output / 'builds.csv', builds)
            (output / 'decisions.json').write_text(json.dumps(decisions, indent=2) + '\n', encoding='utf-8')
            checkpoint()
            print(f'Held-out epoch {epoch+1}/{epochs}: {stream_size * (2+len(baseline_fidelities))} requests validated', flush=True)
        summary = summarize(rows, builds, stream_size)
        write_csv(output / 'summary.csv', summary)
        metadata.update(status='completed', finished_at=datetime.now(timezone.utc).isoformat(),
                        all_counts_match_numpy=True, measured_requests=len(rows),
                        sample_build_ms_mean=mean(b['build_ms'] for b in builds))
        checkpoint()
        return dict(metadata=metadata, summary=summary, output=str(output.resolve()))
    except BaseException:
        metadata['status'] = 'interrupted_or_failed'
        checkpoint()
        raise
    finally:
        if connection:
            connection.close()
