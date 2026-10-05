"""Independent sample epochs with repeated, read-only requests per sample."""
import json
import os
import platform
import random
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from importlib.metadata import version
from time import perf_counter
from zoneinfo import ZoneInfo
from . import __version__
from .backends import Neo4jBackend
from .benchmark import LEVELS, relative_error, write_csv
from .reusable import ReusableSample
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j


def summarize_reuse(rows, builds, requests):
    result = []
    exact_mean = mean(r['request_ms'] for r in rows if r['fidelity'] == 1)
    for f in LEVELS:
        selected = [r for r in rows if r['fidelity'] == f]
        independent = [r for r in selected if r['request_index'] == 0]
        # Full build cost assigned to each standalone fidelity stream (no mixed-stream discount).
        build_mean = mean(b['build_ms'] for b in builds) if f < 1 else 0.0
        request_mean = mean(r['request_ms'] for r in selected)
        saving = exact_mean - request_mean
        import math
        break_even = math.ceil(build_mean / saving) if f < 1 and saving > 0 else None
        result.append(dict(fidelity=f, independent_sample_epochs=len(independent),
            timed_requests=len(selected), requests_per_sample=requests,
            node_error_mean=mean(r['node_error'] for r in independent),
            edge_error_mean=mean(r['edge_error'] for r in independent),
            request_ms_mean=request_mean, request_ms_median=median(r['request_ms'] for r in selected),
            state_check_ms_mean=mean(r['state_check_ms'] for r in selected),
            build_ms_mean=build_mean,
            amortized_ms_per_request=(sum(r['request_ms'] for r in selected)
                                      + (sum(b['build_ms'] for b in builds) if f < 1 else 0)) / len(selected),
            modeled_break_even_requests=break_even))
    return result


def plot_reuse(path, summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    x = [r['fidelity'] * 100 for r in summary]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    axes[0].plot(x, [r['node_error_mean'] * 100 for r in summary], 'o-', label='Node COUNT')
    axes[0].plot(x, [r['edge_error_mean'] * 100 for r in summary], 's-', label='Edge COUNT')
    axes[0].set_ylabel('Mean relative error (%)')
    axes[0].set_title('Independent samples, not repeated answers')
    axes[1].plot(x, [r['request_ms_mean'] for r in summary], 'o-', label='After build, including state check')
    axes[1].plot(x, [r['amortized_ms_per_request'] for r in summary], 's-', label='Including amortized build cost')
    axes[1].set_ylabel('Mean milliseconds per request')
    axes[1].set_title(f"{summary[0]['requests_per_sample']} requests per sample, per fidelity")
    for ax in axes:
        ax.set_xlabel('Fidelity (%)')
        ax.set_xticks(x)
        ax.grid(alpha=0.2)
        ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run_reuse_benchmark(backend_name='memory', n_nodes=50000, avg_degree=6, graph_seed=42,
                        epochs=20, requests=100, warmups=2, sample_seed=1000,
                        output='results/local/reuse-benchmark'):
    if epochs < 2 or requests < 2 or warmups < 1 or sample_seed < 0:
        raise ValueError('Use at least 2 epochs, 2 requests, 1 warmup and a nonnegative sample seed')
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output folder must be new or empty')
    graph = generate_graph(n_nodes, avg_degree, graph_seed)
    reference = SyntheticMemory(graph)
    truth = reference.counts()
    connection = None
    metadata = dict(status='running', project_version=__version__, backend=backend_name,
        started_at=datetime.now(ZoneInfo('Europe/Paris')).isoformat(),
        graph_sha256=graph.fingerprint, dataset=graph.dataset, n_nodes=n_nodes,
        n_edge_records=len(graph.src), graph_seed=graph_seed, avg_degree=avg_degree,
        epochs=epochs, requests_per_epoch_per_fidelity=requests, warmups_per_epoch_per_fidelity=warmups,
        sample_seeds=list(range(sample_seed, sample_seed + epochs)), completed_epochs=0,
        exact_counts={k: truth[k] for k in ('node_count', 'edge_count')},
        python=platform.python_version(), os=platform.platform(), numpy=version('numpy'),
        cpu=platform.processor(), logical_cpus=os.cpu_count(),
        latency_scope='client wall time: sample-state check plus two COUNT requests; graph generation and connection excluded',
        build_scope='state lookup, graph-size validation, rank writes, index maintenance, ready-state publication',
        amortization='one full measured build charged to each fidelity stream, divided by measured requests in that stream',
        independence='20 sample epochs by default; repeated requests reuse answers and are not independent accuracy trials',
        lifecycle='static graph only; one active sample; no concurrent refresh or graph mutation',
        cache_state='warm, no flush; shuffled fidelity order within each repeated request round',
        performance_benchmark_measured=backend_name == 'neo4j')
    output.mkdir(parents=True, exist_ok=True)
    def save_metadata():
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    save_metadata()
    rows, builds = [], []
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
            metadata['neo4j_driver'] = version('neo4j')
            settings, _, _ = connection.driver.execute_query(
                'SHOW SETTINGS YIELD name, value WHERE name IN $names RETURN name, value',
                names=['server.memory.heap.initial_size', 'server.memory.heap.max_size',
                       'server.memory.pagecache.size'], database_=connection.database)
            metadata['server_memory_settings'] = {r['name']: r['value'] for r in settings}
        elif backend_name == 'memory':
            backend = SyntheticMemory(graph)
        else:
            raise ValueError('Unknown backend')
        metadata['graph_setup_ms'] = 1000 * (perf_counter() - start)
        cache = ReusableSample(backend)
        print(f'Reuse benchmark: {n_nodes} nodes, {len(graph.src)} edges, '
              f'{epochs} independent samples, {requests} requests/level/sample', flush=True)
        for epoch in range(epochs):
            seed = sample_seed + epoch
            build = cache.build(seed, refresh=True)
            build.update(epoch=epoch)
            builds.append(build)
            reference.prepare(seed)
            expected = {f: reference.counts(fidelity=f) for f in LEVELS}
            for _ in range(warmups):
                for f in LEVELS:
                    cache.counts(fidelity=f)
            for request in range(requests):
                order = list(LEVELS)
                random.Random(9000 + epoch * requests + request).shuffle(order)
                for index, f in enumerate(order):
                    observed = cache.counts(fidelity=f)
                    for key in ('node_count', 'edge_count'):
                        if observed[key] != expected[f][key]:
                            raise RuntimeError(f'Count mismatch: epoch {epoch}, request {request}, fidelity {f}')
                    rows.append(dict(epoch=epoch, sample_seed=seed, request_index=request,
                        fidelity=f, order_index=index,
                        node_estimate=observed['node_count'] / f, edge_estimate=observed['edge_count'] / (f*f),
                        node_error=relative_error(observed['node_count'] / f, truth['node_count']),
                        edge_error=relative_error(observed['edge_count'] / (f*f), truth['edge_count']), **observed))
            metadata['completed_epochs'] = epoch + 1
            write_csv(output / 'raw_results.csv', rows)
            write_csv(output / 'builds.csv', builds)
            save_metadata()
            print(f'Epoch {epoch + 1}/{epochs}: build {build["build_ms"]:.1f} ms; '
                  f'{requests * len(LEVELS)} read-only requests matched NumPy', flush=True)
        summary = summarize_reuse(rows, builds, requests)
        write_csv(output / 'summary.csv', summary)
        plot_reuse(output / 'reusable-tradeoffs.png', summary)
        metadata.update(status='completed', finished_at=datetime.now(ZoneInfo('Europe/Paris')).isoformat(),
                        all_counts_match_numpy=True, measured_requests=len(rows),
                        first_build_ms=builds[0]['build_ms'],
                        refresh_build_ms_mean=mean(b['build_ms'] for b in builds[1:]))
        save_metadata()
        return dict(output=str(output.resolve()), metadata=metadata, summary=summary)
    except BaseException:
        metadata['status'] = 'interrupted_or_failed'
        save_metadata()
        raise
    finally:
        if connection:
            connection.close()
