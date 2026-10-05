"""Warm-cache matched-workload benchmark with explicit sampling preparation cost."""
import csv
import json
import os
import platform
import random
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from statistics import mean, median, pstdev
from time import perf_counter
from zoneinfo import ZoneInfo
from . import __version__
from .backends import Neo4jBackend
from .dataset import cypher
from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j, numpy

LEVELS = (0.10, 0.25, 0.50, 0.75, 1.0)


def relative_error(estimate, truth):
    return abs(estimate - truth) / truth if truth else (0.0 if estimate == 0 else float('inf'))


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize(rows):
    result = []
    for f in LEVELS:
        selected = [r for r in rows if r['fidelity'] == f]
        result.append(dict(fidelity=f, repeats=len(selected),
            node_error_mean=mean(r['node_error'] for r in selected),
            edge_error_mean=mean(r['edge_error'] for r in selected),
            query_ms_mean=mean(r['query_ms'] for r in selected),
            query_ms_median=median(r['query_ms'] for r in selected),
            query_ms_std=pstdev(r['query_ms'] for r in selected),
            query_ms_p95=float(numpy().percentile([r['query_ms'] for r in selected], 95)),
            preparation_ms_median=median(r['preparation_ms'] for r in selected),
            with_preparation_ms_median=median(r['with_preparation_ms'] for r in selected)))
    return result


def plot_summary(path, summary, title='Graph COUNT benchmark'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    x = [r['fidelity'] * 100 for r in summary]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))
    fig.suptitle(title)
    for key, label in [('node_error_mean', 'Node COUNT'), ('edge_error_mean', 'Edge COUNT')]:
        axes[0].plot(x, [r[key] * 100 for r in summary], marker='o', label=label)
    axes[0].set_ylabel('Mean relative error (%)')
    axes[0].set_title('Accuracy')
    axes[0].legend()
    axes[1].plot(x, [r['query_ms_median'] for r in summary], marker='o')
    axes[1].set_ylabel('Median combined COUNT latency (ms)')
    axes[1].set_title('Queries after sample preparation')
    axes[2].plot(x, [r['with_preparation_ms_median'] for r in summary], marker='o')
    axes[2].set_ylabel('Median preparation + queries (ms)')
    axes[2].set_yscale('log')
    axes[2].set_title('Full preparation charged per level')
    for ax in axes:
        ax.set_xlabel('Fidelity (%)')
        ax.set_xticks(x)
        ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def run_benchmark(backend_name='memory', n_nodes=50000, avg_degree=6, graph_seed=42,
                  repeats=20, warmups=2, output='results/local/benchmark'):
    if repeats < 2 or warmups < 1:
        raise ValueError('Use at least 2 repeats and 1 warmup')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output folder must be new or empty; existing measurements are preserved')
    graph = generate_graph(n_nodes, avg_degree, graph_seed)
    reference = SyntheticMemory(graph)
    expected_exact = reference.counts()
    connection = None
    try:
        started_at = datetime.now(ZoneInfo('Europe/Paris')).isoformat()
        start = perf_counter()
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            backend.seed()
        elif backend_name == 'memory':
            backend = reference
        else:
            raise ValueError('Unknown backend')
        import_ms = 1000 * (perf_counter() - start)
        observed_exact = backend.counts()
        for key in ('node_count', 'edge_count'):
            if observed_exact[key] != expected_exact[key]:
                raise RuntimeError(f'Exact {key} does not match the NumPy graph')
        print(f'Imported/validated {n_nodes} nodes, {len(graph.src)} edge records; exact FR counts '
              f'{expected_exact["node_count"]}/{expected_exact["edge_count"]}', flush=True)
        backend.prepare(1000)
        for _ in range(warmups):
            for f in LEVELS:
                backend.counts(fidelity=f)
        rows = []
        for repeat in range(repeats):
            start = perf_counter()
            backend.prepare(1000 + repeat)
            preparation_ms = 1000 * (perf_counter() - start)
            if backend is not reference:
                reference.prepare(1000 + repeat)
            order = list(LEVELS)
            random.Random(5000 + repeat).shuffle(order)
            for order_index, f in enumerate(order):
                measured = backend.counts(fidelity=f)
                expected = reference.counts(fidelity=f)
                for key in ('node_count', 'edge_count'):
                    if measured[key] != expected[key]:
                        raise RuntimeError(f'Sampled {key} mismatch at repeat {repeat}, fidelity {f}')
                prep = preparation_ms if f < 1 else 0.0
                rows.append(dict(backend=backend_name, fidelity=f, repeat=repeat,
                    sample_seed=1000 + repeat, order_index=order_index,
                    node_estimate=measured['node_count'] / f,
                    edge_estimate=measured['edge_count'] / (f * f),
                    node_error=relative_error(measured['node_count'] / f, expected_exact['node_count']),
                    edge_error=relative_error(measured['edge_count'] / (f * f), expected_exact['edge_count']),
                    **measured, preparation_ms=prep,
                    with_preparation_ms=measured['query_ms'] + prep))
            print(f'Repeat {repeat + 1}/{repeats}: all sampled counts matched NumPy', flush=True)
        summary = summarize(rows)
        metadata = dict(project_version=__version__, started_at=started_at,
            finished_at=datetime.now(ZoneInfo('Europe/Paris')).isoformat(), backend=backend_name,
            database=connection.database if connection else None,
            dataset=graph.dataset, graph_sha256=graph.fingerprint, n_nodes=n_nodes,
            n_edge_records=len(graph.src), avg_degree=avg_degree, graph_seed=graph_seed,
            country='FR', repeats=repeats, warmups_per_fidelity=warmups,
            sample_seeds=list(range(1000, 1000 + repeats)), order_seeds=list(range(5000, 5000 + repeats)),
            exact_counts={k: expected_exact[k] for k in ('node_count', 'edge_count')},
            all_counts_match_numpy=True, import_and_connect_ms=import_ms,
            python=platform.python_version(), numpy=version('numpy'),
            os=platform.platform(), cpu=platform.processor(), logical_cpus=os.cpu_count(),
            cache_state='warm; no cache flush; sample property updates between repeats',
            latency_scope='client wall time for two sequential COUNT execute_query calls; includes transaction/driver overhead',
            preparation_scope='uniform sample generation + property updates + index maintenance; full cost charged per approximate level',
            concurrency='one client; serial; do not mutate this dataset during a run',
            sampling='Bernoulli node inclusion, nested levels sharing one rank vector per repeat',
            edge_semantics='one directed relationship per stored v0.1 edge record, including parallel duplicates; counted once',
            performance_benchmark_measured=backend_name == 'neo4j',
            limitations=['single host/run; no cold-cache experiment', 'timings do not include graph import',
                         'preparation cost is not an optimized online sampling method',
                         'no energy or memory measurement; no adaptive controller migration'])
        if connection:
            records, _, _ = connection.driver.execute_query(
                'CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition',
                database_=connection.database)
            metadata['server_components'] = [r.data() for r in records]
            metadata['neo4j_driver'] = version('neo4j')
            settings, _, _ = connection.driver.execute_query(
                'SHOW SETTINGS YIELD name, value WHERE name IN $names RETURN name, value',
                names=['server.memory.heap.initial_size', 'server.memory.heap.max_size',
                       'server.memory.pagecache.size'], database_=connection.database)
            metadata['server_memory_settings'] = {r['name']: r['value'] for r in settings}
            plans = {}
            for suffix in ['exact_nodes', 'exact_edges', 'sampled_nodes', 'sampled_edges']:
                params = dict(dataset=graph.dataset, country='FR')
                if suffix.startswith('sampled'):
                    params['fidelity'] = 0.1
                _, query_summary, _ = connection.driver.execute_query(
                    'EXPLAIN ' + cypher('synthetic_' + suffix), parameters_=params,
                    database_=connection.database)
                plans[suffix] = query_summary.plan
            metadata['explain_plans'] = plans
        output.mkdir(parents=True, exist_ok=True)
        write_csv(output / 'raw_results.csv', rows)
        write_csv(output / 'summary.csv', summary)
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2, default=str) + '\n', encoding='utf-8')
        plot_summary(output / 'fidelity-tradeoffs.png', summary,
                     f'{backend_name.title()} | {n_nodes:,} nodes | {repeats} repeats | warm cache')
        return dict(output=str(output.resolve()), metadata=metadata, summary=summary)
    finally:
        if connection:
            connection.close()
