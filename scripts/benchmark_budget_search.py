"""Real COUNT evaluations, bounded search, then a separately charged exhaustive reference."""
import argparse
import json
import random
from itertools import product
from pathlib import Path
from statistics import mean
from time import perf_counter
from graph_mf.adaptive import LEVELS
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.budget_search import search
from graph_mf.synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend', choices=['memory', 'neo4j'], default='memory')
    p.add_argument('--nodes', type=int, default=50000)
    p.add_argument('--runs', type=int, default=5)
    p.add_argument('--budget', type=int, default=16)
    p.add_argument('--tolerance', type=float, default=.05)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or a.runs < 2:
        raise ValueError('Fresh output and multiple runs required')
    graph = generate_graph(a.nodes)
    connection = Neo4jBackend() if a.backend == 'neo4j' else None
    backend = SyntheticNeo4j(graph, connection) if connection else SyntheticMemory(graph)
    if connection:
        backend.validate_import()  # Never reimport or clear existing data.
    domain = list(product(LEVELS, repeat=2))
    a.output.mkdir(parents=True)
    rows, calls, anchors = [], [], []
    metadata = dict(status='running', backend=a.backend, nodes=a.nodes, graph_sha256=graph.fingerprint,
        runs=a.runs, budget=a.budget, tolerance=a.tolerance,
        scope='same static graph; train FR/DE, held-out ES/IT/NL; empirical error, no probabilistic guarantee',
        methods=['random', 'nsga2', 'surrogate'], domain_size=len(domain),
        approximation='uncorrected inclusion scaling; surrogate learns configuration cost/error, not answer correction',
        oracle_available_to_search=False, performance_measured=a.backend=='neo4j')
    def checkpoint():
        (a.output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    checkpoint()
    try:
        for run in range(a.runs):
            start = perf_counter()
            backend.prepare(15000+run)
            truth = {c: backend.counts(c) for c in ('FR','DE','ES','IT','NL')}
            anchors.append(dict(run=run, setup_ms=1000*(perf_counter()-start), exact_truth_queries=10,
                                seed=15000+run))
            def evaluate(candidate, method):
                costs, errors = [], []
                for country in ('FR','DE'):
                    for kind, f, power in zip(('node','edge'), candidate, (1,2)):
                        result = backend.count_component(country, f, kind)
                        target = truth[country][kind+'_count']
                        costs.append(result['query_ms'])
                        errors.append(abs(result['count']/f**power-target)/max(target,1))
                cost, error = sum(costs), max(errors)
                calls.append(dict(run=run, method=method, node_f=candidate[0], edge_f=candidate[1],
                                  cost_ms=cost, error=error, business_queries=4))
                return cost, error
            methods = list(metadata['methods']); random.Random(run).shuffle(methods)
            outputs = {}
            for method in methods:
                start = perf_counter()
                result = search(domain, lambda c: evaluate(c, method), a.budget, a.tolerance, method, run)
                result['search_ms'] = 1000*(perf_counter()-start)
                outputs[method] = result
            # This truth table is constructed only after all searches finish.
            start = perf_counter()
            oracle = {c: evaluate(c, 'exhaustive') for c in domain}
            oracle_ms = 1000*(perf_counter()-start)
            feasible = [c for c in domain if oracle[c][1] <= a.tolerance]
            optimum = min(oracle[c][0] for c in feasible)
            for method, result in outputs.items():
                selected = result['selected']
                held_errors, held_costs = [], []
                if selected is not None:
                    for country in ('ES','IT','NL'):
                        for kind,f,power in zip(('node','edge'), selected, (1,2)):
                            measured = backend.count_component(country,f,kind)
                            target = truth[country][kind+'_count']
                            held_errors.append(abs(measured['count']/f**power-target)/max(target,1))
                            held_costs.append(measured['query_ms'])
                rows.append(dict(run=run, method=method, evaluations=result['evaluations'],
                    search_ms=result['search_ms'], exhaustive_ms=oracle_ms, exhaustive_evaluations=len(domain),
                    node_f=selected[0] if selected else None, edge_f=selected[1] if selected else None,
                    reference_cost_ratio=oracle[selected][0]/optimum if selected else None,
                    reference_feasible=oracle[selected][1]<=a.tolerance if selected else False,
                    heldout_max_error=max(held_errors) if held_errors else None,
                    heldout_pass=max(held_errors)<=a.tolerance if held_errors else False,
                    heldout_queries=len(held_costs), heldout_query_ms=sum(held_costs)))
            write_csv(a.output/'runs.csv', rows); write_csv(a.output/'evaluations.csv', calls)
            write_csv(a.output/'setup.csv', anchors)
            print('Completed budget-search run',run+1,flush=True)
        metadata['summary'] = {method: dict(mean_evaluations=mean(r['evaluations'] for r in rows if r['method']==method),
            mean_search_ms=mean(r['search_ms'] for r in rows if r['method']==method),
            heldout_passes=sum(r['heldout_pass'] for r in rows if r['method']==method)) for method in methods}
        metadata['status']='completed'; checkpoint(); print(json.dumps(metadata['summary'],indent=2))
    except BaseException:
        metadata['status']='failed_or_interrupted'; checkpoint(); raise
    finally:
        if connection:
            connection.close()


if __name__=='__main__':
    main()
