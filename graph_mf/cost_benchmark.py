"""Lazy materialization and cost-aware stream evaluation against preserved profiles."""
import csv
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from . import __version__
from .adaptive import LEVELS, TIERS
from .backends import Neo4jBackend
from .benchmark import write_csv, relative_error
from .deep_benchmark import SEQUENCE
from .split_policy import CostAwareSession
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j


def stream(predicates, horizon, seed):
    rng = random.Random(seed)
    result = []
    while len(result) < horizon:
        order = list(predicates)
        rng.shuffle(order)
        for predicate in order:
            if len(result) >= horizon:
                break
            tier = SEQUENCE[len(result)*len(SEQUENCE)//horizon]
            result.append((predicate, tier))
    return result


def run_cost_benchmark(source, output, backend_name='memory', epochs=3, horizons=(75, 500)):
    source, output = Path(source), Path(output)
    if epochs < 2 or not horizons or len(set(horizons)) != len(horizons) or any(type(h) is not int or h < 5 for h in horizons):
        raise ValueError('Use >=2 epochs and horizons >=5')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('New or empty output required')
    source_meta = json.loads((source/'metadata.json').read_text(encoding='utf-8'))
    if source_meta['status'] != 'completed' or not source_meta['all_counts_match_numpy']:
        raise ValueError('Completed validated synthetic source required')
    if source_meta['provenance'].get('type') != 'synthetic':
        raise ValueError('This focused benchmark requires synthetic graph provenance')
    graph = generate_graph(source_meta['nodes'], source_meta['provenance']['avg_degree'],
                           source_meta['provenance']['graph_seed'])
    profile = json.loads((source/'profile.json').read_text(encoding='utf-8'))
    if graph.fingerprint != profile['graph_sha256']:
        raise ValueError('Graph/profile fingerprint mismatch')
    with (source/'timing-builds.csv').open(newline='', encoding='utf-8') as handle:
        forecast_build_ms = mean(float(r['build_ms']) for r in csv.DictReader(handle))
    reference = SyntheticMemory(graph)
    truth = {p: reference.counts(p) for p in profile['countries']}
    output.mkdir(parents=True, exist_ok=True)
    metadata = dict(status='running', version=__version__, backend=backend_name,
        source=source.as_posix(), graph_sha256=graph.fingerprint, nodes=source_meta['nodes'],
        forecast_build_ms=forecast_build_ms, forecast_scope='v06 timing seeds only; no held-out build cost leakage',
        horizons=list(horizons), epochs=epochs, started_at=datetime.now(timezone.utc).isoformat(),
        modes=['exact', 'cached', 'amortized'], tiers=TIERS,
        scope='known stream horizon; graph import/calibration/profile startup excluded; actual sample build charged once',
        cache='warm exact queries before each stream; sequential policy streams, order randomized by seed; shared desktop server',
        performance_measured=backend_name == 'neo4j', energy_measured=False)
    def checkpoint():
        (output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n', encoding='utf-8')
    checkpoint()
    connection = None
    rows, streams = [], []
    try:
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            backend.validate_import()
        elif backend_name == 'memory':
            backend = SyntheticMemory(graph)
        else:
            raise ValueError('Unknown backend')
        for scenario, horizon in enumerate(horizons):
            for epoch in range(epochs):
                seed = 10000+scenario*100+epoch
                reference.prepare(seed)
                expected = {(p, k, f): reference.count_component(p, f, k)['count']
                    for p in profile['countries'] for k in ('node', 'edge') for f in LEVELS}
                requests = stream(profile['countries'], horizon, seed)
                order = ['exact', 'cached', 'amortized']
                random.Random(seed).shuffle(order)
                for mode in order:
                    session = CostAwareSession(backend, profile, forecast_build_ms, horizon, seed, mode)
                    cache = session.cache
                    for p in profile['countries']:
                        for kind in ('node', 'edge'):
                            warm = cache.count_component(p, 1., kind)
                            if warm['count'] != truth[p][kind+'_count']:
                                raise RuntimeError('Warmup exact COUNT mismatch')
                    build_ms, built, online_ms = 0., False, 0.
                    selected_rows = []
                    for index, (predicate, tier) in enumerate(requests):
                        result = session.request(predicate, tier)
                        this_build_ms = result['build_ms']
                        build_ms += this_build_ms
                        built = session.built
                        desired = result['planned_pair']
                        dispatch_ms = result['online_ms']
                        online_ms += dispatch_ms
                        for step in result['steps']:
                            if step['count'] != expected[predicate, step['kind'], step['fidelity']]:
                                raise RuntimeError('Component COUNT mismatch')
                        ne = relative_error(result['node_estimate'], truth[predicate]['node_count'])
                        ee = relative_error(result['edge_estimate'], truth[predicate]['edge_count'])
                        row = dict(horizon=horizon, epoch=epoch, seed=seed, mode=mode, index=index,
                            predicate=predicate, tier=tier, desired_node=desired[0], desired_edge=desired[1],
                            node_fidelity=result['node_fidelity'], edge_fidelity=result['edge_fidelity'],
                            request_ms=result['request_ms'], dispatch_ms=dispatch_ms,
                            build_ms=this_build_ms, count_calls=len(result['steps']), node_error=ne, edge_error=ee,
                            violation=ne>TIERS[tier][0] or ee>TIERS[tier][1])
                        rows.append(row)
                        selected_rows.append(row)
                    streams.append(dict(horizon=horizon, epoch=epoch, seed=seed, mode=mode,
                        built=built, build_ms=build_ms, online_ms=online_ms, online_ms_per_request=online_ms/horizon,
                        query_dispatch_ms_per_request=(online_ms-build_ms)/horizon,
                        violation_rate=mean(r['violation'] for r in selected_rows)))
                    write_csv(output/'raw-results.csv', rows)
                    write_csv(output/'streams.csv', streams)
                    print(f'horizon {horizon}, epoch {epoch+1}/{epochs}, {mode}: build={built}, {online_ms/horizon:.2f} ms', flush=True)
        summaries = []
        for horizon in horizons:
            for mode in metadata['modes']:
                subset = [r for r in streams if r['horizon'] == horizon and r['mode'] == mode]
                summaries.append(dict(horizon=horizon, mode=mode, independent_streams=len(subset),
                    online_ms_per_request=mean(r['online_ms_per_request'] for r in subset),
                    query_dispatch_ms_per_request=mean(r['query_dispatch_ms_per_request'] for r in subset),
                    build_ms_mean=mean(r['build_ms'] for r in subset),
                    streams_built=sum(r['built'] for r in subset), violation_rate=mean(r['violation_rate'] for r in subset)))
        write_csv(output/'summary.csv', summaries)
        metadata.update(status='completed', timed_requests=len(rows), all_counts_match_numpy=True,
                        finished_at=datetime.now(timezone.utc).isoformat())
        checkpoint()
        return metadata
    except BaseException:
        metadata['status'] = 'interrupted_or_failed'
        checkpoint()
        raise
    finally:
        if connection:
            connection.close()
