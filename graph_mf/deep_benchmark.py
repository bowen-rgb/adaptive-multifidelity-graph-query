"""Same-path policy comparison, public topology and sampled process memory."""
import json
import platform
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import perf_counter
from . import __version__
from .adaptive import calibrate, LEVELS, TIERS
from .backends import Neo4jBackend
from .benchmark import write_csv, relative_error
from .memory_monitor import MemoryMonitor
from .public_graph import load_snap
from .reusable import ReusableSample
from .split_policy import optimize_policies, choose, execute_pair, SplitController
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j, numpy

MODES = ('exact', 'fixed10', 'fixed25', 'fixed50', 'fixed75', 'exhaustive', 'nsga2', 'adaptive')
SEQUENCE = ('performance', 'balanced', 'quality', 'performance', 'exact')


def summarize_requests(rows, builds, stream_size):
    summaries = []
    for mode in MODES:
        for tier in ('all', *TIERS):
            subset = [r for r in rows if r['mode'] == mode and (tier == 'all' or r['tier'] == tier)]
            if not subset:
                continue
            epochs = sorted({r['epoch'] for r in subset})
            uses_sample = {e: any(r['epoch'] == e and r['mode'] == mode and
                (r['node_fidelity'] < 1 or r['edge_fidelity'] < 1 or r['count_calls'] > 2)
                for r in rows) for e in epochs}
            costs = [mean(r['request_ms'] for r in subset if r['epoch'] == e)
                + (next(b['build_ms'] for b in builds if b['epoch'] == e)/stream_size if uses_sample[e] else 0)
                for e in epochs]
            # Resample whole seed epochs, not correlated individual request rows.
            rng = numpy().random.default_rng(1776)
            boot = rng.choice(costs, size=(2000, len(costs)), replace=True).mean(axis=1)
            summaries.append(dict(mode=mode, tier=tier, requests=len(subset), independent_epochs=len(epochs),
                request_ms_mean=mean(r['request_ms'] for r in subset),
                request_ms_p95=float(numpy().percentile([r['request_ms'] for r in subset], 95)),
                with_build_ms_mean=mean(costs), bootstrap_low=float(numpy().percentile(boot, 2.5)),
                bootstrap_high=float(numpy().percentile(boot, 97.5)),
                node_error_mean=mean(r['node_error'] for r in subset),
                edge_error_mean=mean(r['edge_error'] for r in subset),
                violation_rate=mean(r['violation'] for r in subset),
                count_calls_mean=mean(r['count_calls'] for r in subset)))
    return summaries


def run_case(graph, provenance, output, monitor, backend_name, epochs, repeats, timing_epochs):
    output.mkdir(parents=True, exist_ok=True)
    predicates = sorted(set(graph.countries.tolist()))
    reference = SyntheticMemory(graph)
    truth = {p: reference.counts(p) for p in predicates}
    stream_size = len(predicates)*len(SEQUENCE)*repeats
    metadata = dict(status='running', version=__version__, started_at=datetime.now(timezone.utc).isoformat(),
        backend=backend_name, provenance=provenance, graph_sha256=graph.fingerprint, dataset=graph.dataset,
        nodes=len(graph.countries), edge_records=len(graph.src), predicates=predicates,
        epochs=epochs, timing_epochs=timing_epochs, repeats_per_tier=repeats,
        stream_requests_per_sample=stream_size, tier_sequence=SEQUENCE,
        candidate_space=64, objectives=['profiled component latency', 'node calibrated bound', 'edge calibrated bound'],
        nsga_configuration=dict(population_size=32, generations=30, mutation_rate=.2, seeds=list(range(10)), runtime_seed=0),
        evaluation_seeds=list(range(9000, 9000+epochs)), timing_seeds=list(range(8000, 8000+timing_epochs)),
        all_estimators='same frozen correction gains for all approximate policies',
        nsga_runtime_front='predeclared search seed 0 final population, no oracle or union of searches',
        latency_scope='complete request, all component state checks, controller and correction; monitor enabled',
        excluded_costs='graph import, offline fitting/calibration, timing profile, optimizer setup; recorded separately',
        build_scope='standalone mixed stream charged full build / actual requests only if any sampled call was used; exact-only streams need no sample',
        inference_scope='bootstrap seed-epoch means within one graph/run; five epochs are preliminary',
        cache='warmup each predicate/component/level, no flush; shared running server retains earlier datasets',
        performance_measured=backend_name == 'neo4j', energy_measured=False,
        python=platform.python_version(), platform=platform.platform(), completed_epochs=0)
    def checkpoint():
        (output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    checkpoint()
    connection = None
    try:
        monitor.phase = 'correction_calibration'
        profile = calibrate(graph, countries=predicates)
        metadata['correction_calibration_ms'] = profile['calibration_cpu_ms']
        metadata['fitting_seeds'] = profile['fitting_seeds']
        metadata['calibration_seeds'] = profile['calibration_seeds']
        monitor.phase = 'import'
        start = perf_counter()
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            backend.seed()
            components, _, _ = connection.driver.execute_query(
                'CALL dbms.components() YIELD name,versions,edition RETURN name,versions,edition',
                database_=connection.database)
            metadata['server_components'] = [r.data() for r in components]
        elif backend_name == 'memory':
            backend = SyntheticMemory(graph)
        else:
            raise ValueError('Unknown backend')
        metadata['import_connect_ms'] = 1000*(perf_counter()-start)
        cache = ReusableSample(backend)
        timing_rows, timing_builds = [], []
        start = perf_counter()
        for epoch in range(timing_epochs):
            monitor.phase = 'timing_build'
            seed = 8000+epoch
            timing_builds.append(cache.build(seed, refresh=True))
            reference.prepare(seed)
            monitor.phase = 'timing_queries'
            for predicate in predicates:
                for kind in ('node', 'edge'):
                    for f in LEVELS:
                        cache.count_component(predicate, f, kind)
                for repeat in range(3):
                    settings = [(k, f) for k in ('node', 'edge') for f in LEVELS]
                    random.Random(seed+repeat).shuffle(settings)
                    for kind, f in settings:
                        observed = cache.count_component(predicate, f, kind)
                        expected = reference.count_component(predicate, f, kind)
                        if observed['count'] != expected['count']:
                            raise RuntimeError('Timing COUNT mismatch')
                        timing_rows.append(dict(epoch=epoch, predicate=predicate, kind=kind, fidelity=f,
                                                repeat=repeat, **observed))
            write_csv(output/'timing-raw.csv', timing_rows)
            print(f'{output.name}: timing {epoch+1}/{timing_epochs}', flush=True)
        metadata['timing_profile_ms'] = 1000*(perf_counter()-start)
        profile['component_timing'] = {p: {kind: {str(f): mean(r['request_ms'] for r in timing_rows
            if r['predicate'] == p and r['kind'] == kind and r['fidelity'] == f) for f in LEVELS}
            for kind in ('node', 'edge')} for p in predicates}
        (output/'profile.json').write_text(json.dumps(profile, indent=2)+'\n')
        write_csv(output/'timing-builds.csv', timing_builds)
        monitor.phase = 'optimization'
        start = perf_counter()
        policies, fronts, comparisons = {}, {}, []
        for predicate in predicates:
            policies[predicate], fronts[predicate], comparison = optimize_policies(profile, predicate)
            comparisons.extend(dict(predicate=predicate, **r) for r in comparison)
        metadata['optimization_setup_ms'] = 1000*(perf_counter()-start)
        write_csv(output/'optimizer-comparison.csv', comparisons)
        # Freeze all static choices before any held-out query, not just before each request.
        choices = {p: {t: {'exhaustive': choose(policies[p], TIERS[t]),
                          'nsga2': choose(policies[p], TIERS[t], fronts[p])} for t in TIERS} for p in predicates}
        (output/'choices.json').write_text(json.dumps(choices, indent=2)+'\n')
        rows, builds, traces = [], [], []
        for epoch in range(epochs):
            seed = 9000+epoch
            monitor.phase = 'evaluation_build'
            builds.append(dict(epoch=epoch, **cache.build(seed, refresh=True)))
            reference.prepare(seed)
            controllers = {p: SplitController(profile) for p in predicates}
            expected = {(p, kind, f): reference.count_component(p, f, kind)['count']
                        for p in predicates for kind in ('node', 'edge') for f in LEVELS}
            monitor.phase = 'warmup'
            for p, kind, f in expected:
                cache.count_component(p, f, kind)
            for block, tier in enumerate(SEQUENCE):
                for repeat in range(repeats):
                    order = list(predicates)
                    random.Random(seed+block*100+repeat).shuffle(order)
                    for predicate in order:
                        modes = list(MODES)
                        random.Random(seed+block*100+repeat+predicates.index(predicate)).shuffle(modes)
                        for mode in modes:
                            monitor.phase = 'query_'+mode
                            if mode == 'adaptive':
                                result = controllers[predicate].request(cache, predicate, tier)
                                traces.append(dict(epoch=epoch, predicate=predicate, tier=tier,
                                                   block=block, repeat=repeat, **result))
                            else:
                                if mode == 'exact':
                                    pair = (1., 1.)
                                elif mode.startswith('fixed'):
                                    f = int(mode[5:])/100
                                    pair = (f, f)
                                else:
                                    pair = choices[predicate][tier][mode]
                                result = execute_pair(cache, profile, predicate, pair)
                            for step in result['steps']:
                                if step['count'] != expected[predicate, step['kind'], step['fidelity']]:
                                    raise RuntimeError('Held-out component COUNT mismatch')
                            ne = relative_error(result['node_estimate'], truth[predicate]['node_count'])
                            ee = relative_error(result['edge_estimate'], truth[predicate]['edge_count'])
                            rows.append(dict(epoch=epoch, seed=seed, predicate=predicate, tier=tier,
                                block=block, repeat=repeat, mode=mode,
                                node_fidelity=result['node_fidelity'], edge_fidelity=result['edge_fidelity'],
                                node_estimate=result['node_estimate'], edge_estimate=result['edge_estimate'],
                                request_ms=result['request_ms'], count_calls=len(result['steps']),
                                node_error=ne, edge_error=ee, violation=ne>TIERS[tier][0] or ee>TIERS[tier][1]))
            metadata['completed_epochs'] = epoch+1
            write_csv(output/'raw-results.csv', rows)
            write_csv(output/'builds.csv', builds)
            (output/'adaptive-traces.json').write_text(json.dumps(traces, separators=(',', ':'))+'\n')
            checkpoint()
            print(f'{output.name}: held-out {epoch+1}/{epochs}, {stream_size*len(MODES)} requests validated', flush=True)
        write_csv(output/'summary.csv', summarize_requests(rows, builds, stream_size))
        metadata.update(all_counts_match_numpy=True, timed_requests=len(rows),
                        finished_at=datetime.now(timezone.utc).isoformat())
        return metadata
    finally:
        if connection:
            connection.close()


def run_suite(output, backend='memory', sizes=(50000, 100000, 200000), snap_path=None,
              server_pid=None, epochs=5, repeats=3, timing_epochs=3):
    if epochs < 2 or repeats < 3 or timing_epochs < 2 or not sizes and snap_path is None:
        raise ValueError('Use >=2 epochs, >=3 repeats, >=2 timing epochs and at least one graph')
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be new or empty')
    output.mkdir(parents=True, exist_ok=True)
    cases = ([('snap-facebook', None)] if snap_path else []) + [(f'synthetic-{n}', n) for n in sizes]
    results = []
    for name, size in cases:
        folder = output/name
        folder.mkdir()
        try:
            with MemoryMonitor(server_pid) as monitor:
                monitor.phase = 'graph_load'
                if size is None:
                    graph, provenance = load_snap(snap_path)
                else:
                    graph = generate_graph(size)
                    provenance = dict(type='synthetic', graph_seed=42, avg_degree=6)
                print(f'{name}: {len(graph.countries)} nodes, {len(graph.src)} edges', flush=True)
                metadata = run_case(graph, provenance, folder, monitor, backend, epochs, repeats, timing_epochs)
            write_csv(folder/'memory-raw.csv', monitor.rows)
            write_csv(folder/'memory-summary.csv', monitor.summary())
            metadata.update(status='completed', memory=dict(identities=monitor.identities,
                interval_seconds=monitor.interval, errors=monitor.errors,
                scope='process RSS; Windows working set; sampled maximum, shared server with retained datasets',
                source='https://psutil.io/'))
            (folder/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
            results.append(dict(case=name, graph_sha256=graph.fingerprint, timed_requests=metadata['timed_requests']))
            (output/'suite.json').write_text(json.dumps(dict(status='running', completed=results), indent=2)+'\n')
        except BaseException:
            (output/'suite.json').write_text(json.dumps(dict(status='interrupted_or_failed', completed=results), indent=2)+'\n')
            raise
    result = dict(status='completed', completed=results)
    (output/'suite.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
