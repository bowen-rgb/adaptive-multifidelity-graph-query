"""Controlled profile faults, exact anchors and costed independent recovery."""
import csv
from copy import deepcopy
import json
from pathlib import Path
import random
from statistics import mean
from time import perf_counter
from . import __version__
from .adaptive import calibrate, LEVELS, TIERS
from .audit import AuditedSession
from .backends import Neo4jBackend
from .benchmark import write_csv, relative_error
from .reusable import ReusableSample
from .split_policy import CostAwareSession, policy_scores, choose
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j


def prepare_recovery(backend, graph, countries, scenario, epoch):
    """Full static snapshot calibration; independent timing and new runtime sample seeds."""
    start = perf_counter()
    if backend.name == 'neo4j':
        backend.validate_import()
    profile = calibrate(graph, countries=countries, fit_seed_start=20000+scenario*300+epoch*50,
                        calibration_seed_start=21000+scenario*300+epoch*50)
    cache = ReusableSample(backend)
    timing_seed = 24000+scenario*100+epoch
    build = cache.build(timing_seed, refresh=True)
    reference = SyntheticMemory(graph)
    reference.prepare(timing_seed)
    timing = {p: {k: {} for k in ('node', 'edge')} for p in countries}
    for predicate in countries:
        for kind in ('node', 'edge'):
            for f in LEVELS:
                readings = []
                for _ in range(2):
                    result = cache.count_component(predicate, f, kind)
                    if result['count'] != reference.count_component(predicate, f, kind)['count']:
                        raise RuntimeError('Recovery timing COUNT mismatch')
                    readings.append(result['request_ms'])
                timing[predicate][kind][str(f)] = mean(readings)
    profile['component_timing'] = timing
    return profile, build['build_ms'], dict(preparation_ms=1000*(perf_counter()-start),
        fitting_seeds=profile['fitting_seeds'], calibration_seeds=profile['calibration_seeds'],
        timing_seed=timing_seed, timing_build_ms=build['build_ms'])


def run_audit_benchmark(source, output, backend_name='memory', epochs=3, requests=60,
                        audit_every=10, recovery_strategy='full', scenarios=None):
    if epochs < 2 or requests < 40:
        raise ValueError('Use >=2 epochs and >=40 requests')
    if type(audit_every) is not int or audit_every < 1 or recovery_strategy not in ('full', 'timing_only'):
        raise ValueError('Positive audit interval and known recovery strategy required')
    scenarios = list(scenarios or ('healthy', 'gain_fault', 'timing_fault'))
    if len(set(scenarios)) != len(scenarios) or any(s not in ('healthy', 'gain_fault', 'timing_fault') for s in scenarios):
        raise ValueError('Distinct known scenarios required')
    source, output = Path(source), Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('New or empty output required')
    source_meta = json.loads((source/'metadata.json').read_text(encoding='utf-8'))
    if source_meta['status'] != 'completed' or not source_meta['all_counts_match_numpy']:
        raise ValueError('Completed validated source required')
    if source_meta['provenance'].get('type') != 'synthetic':
        raise ValueError('Synthetic source required for static snapshot recovery')
    graph = generate_graph(source_meta['nodes'], source_meta['provenance']['avg_degree'], source_meta['provenance']['graph_seed'])
    base_profile = json.loads((source/'profile.json').read_text(encoding='utf-8'))
    if graph.fingerprint != base_profile['graph_sha256']:
        raise ValueError('Profile fingerprint mismatch')
    candidates = [p for p in base_profile['countries'] if choose(policy_scores(base_profile, p), TIERS['performance']) != (1., 1.)]
    if not candidates:
        raise ValueError('This robustness experiment requires a predicate with an approximate cached plan')
    predicate = candidates[0]
    with (source/'timing-builds.csv').open(newline='', encoding='utf-8') as handle:
        forecast_build = mean(float(r['build_ms']) for r in csv.DictReader(handle))
    reference = SyntheticMemory(graph)
    truth = reference.counts(predicate)
    output.mkdir(parents=True, exist_ok=True)
    metadata = dict(status='running', version=__version__, backend=backend_name, source=source.as_posix(),
        graph_sha256=graph.fingerprint, nodes=source_meta['nodes'], predicate=predicate,
        epochs=epochs, requests_per_stream=requests, scenarios=scenarios,
        modes=['exact', 'unaudited', 'audited'], audit_every=audit_every, recovery_strategy=recovery_strategy,
        timing_factor=3. if backend_name == 'neo4j' else 1e6, timing_patience=3,
        injected_at_request=6, recovery_at_request=31, gain_multiplier=1.8,
        timing_multiplier=.01 if backend_name == 'neo4j' else 1e-12,
        fault_scope='controlled profile corruption only; no graph data mutation or actual server slowdown',
        controller_mode='cached to exercise approximate path; actual fresh sample construction charged',
        recovery_scope=('full local static graph snapshot, independent fit/calibration/timing seeds, new sample; all preparation charged'
                        if recovery_strategy == 'full' else
                        'timing quarantine: retained sample, frozen gains/bounds, predicate-only profiling; other faults use full recovery; all preparation charged'),
        performance_measured=backend_name == 'neo4j', energy_measured=False)
    def checkpoint():
        (output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    checkpoint()
    rows, streams, recoveries, events = [], [], [], []
    connection = None
    try:
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            backend.validate_import()
        elif backend_name == 'memory':
            backend = SyntheticMemory(graph)
        else:
            raise ValueError('Unknown backend')
        for scenario in metadata['scenarios']:
            scenario_id = ('healthy', 'gain_fault', 'timing_fault').index(scenario)
            for epoch in range(epochs):
                seed = 25000+scenario_id*100+epoch
                reference.prepare(seed)
                initial_expected = {(k, f): reference.count_component(predicate, f, k)['count'] for k in ('node', 'edge') for f in LEVELS}
                order = list(metadata['modes'])
                random.Random(seed).shuffle(order)
                for mode in order:
                    expected = dict(initial_expected)
                    p = deepcopy(base_profile)
                    factor = 3. if backend_name == 'neo4j' else 1e6
                    client = (AuditedSession(backend, p, forecast_build, requests, seed, mode='cached', timing_factor=factor,
                                            audit_every=audit_every)
                              if mode == 'audited' else CostAwareSession(backend, p, forecast_build, requests, seed,
                                  mode='exact' if mode == 'exact' else 'cached'))
                    cache = client.session.cache if mode == 'audited' else client.cache
                    for kind in ('node', 'edge'):
                        if cache.count_component(predicate, 1., kind)['count'] != truth[kind+'_count']:
                            raise RuntimeError('Warmup exact mismatch')
                    selected, recovery_ms = [], 0.
                    for index in range(1, requests+1):
                        active = client.session.profile if mode == 'audited' else client.profile
                        if index == 6 and mode != 'exact':
                            if scenario == 'gain_fault':
                                for level in active['levels'][:-1]:
                                    level['node_gain'] *= 1.8
                                    level['edge_gain'] *= 1.8
                            elif scenario == 'timing_fault':
                                scale = .01 if backend_name == 'neo4j' else 1e-12
                                for kind in active['component_timing'][predicate].values():
                                    for f in kind:
                                        kind[f] *= scale
                        if index == 31 and mode == 'audited' and scenario != 'healthy' and client.state == 'quarantined':
                            recovery_start = perf_counter()
                            if recovery_strategy == 'timing_only' and client.reason == 'timing_drift':
                                detail = client.refresh_timing(predicate)
                                for step in detail.pop('steps'):
                                    if step['count'] != expected[step['kind'], step['fidelity']]:
                                        raise RuntimeError('Timing recovery COUNT mismatch')
                                next_seed = seed
                                new = client.session.profile
                            else:
                                new, forecast, detail = prepare_recovery(backend, graph, base_profile['countries'], scenario_id, epoch)
                                next_seed = 26000+scenario_id*100+epoch
                                client.refresh(new, forecast, next_seed)
                            elapsed = 1000*(perf_counter()-recovery_start)
                            recovery_ms += elapsed
                            detail.pop('sample_seed', None)
                            recoveries.append(dict(scenario=scenario, epoch=epoch, sample_seed=next_seed,
                                                   total_recovery_ms=elapsed, **detail))
                            (output/f'recovered-{scenario}-{epoch}.json').write_text(json.dumps(new, indent=2)+'\n', encoding='utf-8')
                            reference.prepare(next_seed)
                            expected = {(k, f): reference.count_component(predicate, f, k)['count'] for k in ('node', 'edge') for f in LEVELS}
                        result = client.request(predicate, 'performance')
                        for step in result['steps']:
                            if step['count'] != expected[step['kind'], step['fidelity']]:
                                raise RuntimeError('Audit/fallback component mismatch')
                        candidate = result.get('candidate') if mode == 'audited' else result
                        errors = [relative_error(result[k+'_estimate'], truth[k+'_count']) for k in ('node', 'edge')]
                        candidate_errors = ([relative_error(candidate[k+'_estimate'], truth[k+'_count']) for k in ('node', 'edge')]
                                            if candidate else None)
                        row = dict(scenario=scenario, epoch=epoch, initial_sample_seed=seed, mode=mode, index=index,
                            node_fidelity=result['node_fidelity'], edge_fidelity=result['edge_fidelity'],
                            node_error=errors[0], edge_error=errors[1], violation=any(e>b for e,b in zip(errors, TIERS['performance'])),
                            candidate_violation=any(e>b for e,b in zip(candidate_errors, TIERS['performance'])) if candidate_errors else False,
                            audited=result.get('audited', False), audit_ms=result.get('audit_ms', 0.),
                            quarantined=result.get('quarantined', False), reason=result.get('reason'),
                            state=result.get('state', 'active'),
                            timing_ratio=result.get('timing_ratio'), profile_epoch=result.get('profile_epoch', 0),
                            online_ms=result['online_ms'], build_ms=result['build_ms'], count_calls=len(result['steps']))
                        rows.append(row)
                        selected.append(row)
                    if mode == 'audited':
                        events.extend(dict(scenario=scenario, epoch=epoch, **e) for e in client.events)
                    detections = [r['index'] for r in selected if r['quarantined']]
                    streams.append(dict(scenario=scenario, epoch=epoch, mode=mode,
                        online_ms_per_request=(sum(r['online_ms'] for r in selected)+recovery_ms)/requests,
                        recovery_ms=recovery_ms, audit_ms=sum(r['audit_ms'] for r in selected),
                        build_ms=sum(r['build_ms'] for r in selected),
                        served_violations=sum(r['violation'] for r in selected),
                        candidate_violations=sum(r['candidate_violation'] for r in selected),
                        audits=sum(r['audited'] for r in selected), first_detection=min(detections) if detections else None,
                        recovered=any(r['profile_epoch']>0 and r['state']=='active'
                            and (r['node_fidelity']<1 or r['edge_fidelity']<1) for r in selected)))
                    write_csv(output/'raw-results.csv', rows)
                    write_csv(output/'streams.csv', streams)
                    (output/'recoveries.json').write_text(json.dumps(recoveries, indent=2)+'\n', encoding='utf-8')
                    (output/'events.json').write_text(json.dumps(events, indent=2)+'\n', encoding='utf-8')
                    print(f'{scenario} {epoch+1}/{epochs} {mode}: violations={streams[-1]["served_violations"]}, detection={streams[-1]["first_detection"]}', flush=True)
        summary = []
        for scenario in metadata['scenarios']:
            for mode in metadata['modes']:
                subset = [s for s in streams if s['scenario'] == scenario and s['mode'] == mode]
                summary.append(dict(scenario=scenario, mode=mode, streams=len(subset),
                    online_ms_per_request=mean(s['online_ms_per_request'] for s in subset),
                    served_violations=sum(s['served_violations'] for s in subset),
                    audits=sum(s['audits'] for s in subset), recovery_ms_mean=mean(s['recovery_ms'] for s in subset),
                    recovered_streams=sum(s['recovered'] for s in subset)))
        write_csv(output/'summary.csv', summary)
        metadata.update(status='completed', timed_requests=len(rows), all_counts_match_numpy=True)
        checkpoint()
        return metadata
    except BaseException:
        metadata['status'] = 'interrupted_or_failed'
        checkpoint()
        raise
    finally:
        if connection:
            connection.close()
