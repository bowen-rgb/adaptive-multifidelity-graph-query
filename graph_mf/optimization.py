"""Finite categorical NSGA-II and exhaustive reference over recorded measurements.

All objectives are minimized. No Neo4j queries or new latency measurements occur here.
Algorithm reference: Deb et al. (2002), https://doi.org/10.1109/4235.996017.
"""
import csv
import hashlib
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from . import __version__


def validate_objectives(values):
    if not values or not values[0]:
        raise ValueError('At least one nonempty objective vector is required')
    dimension = len(values[0])
    if any(len(v) != dimension or any(not math.isfinite(x) for x in v) for v in values):
        raise ValueError('Objective vectors must have equal dimensions and finite values')


def dominates(left, right):
    if not left or len(left) != len(right):
        raise ValueError('Dominance requires equal nonempty dimensions')
    return all(a <= b for a, b in zip(left, right)) and any(a < b for a, b in zip(left, right))


def nondominated_sort(values):
    """Fast O(M N^2) sorting; return fronts of input indices, including ties."""
    validate_objectives(values)
    dominated, counts = [[] for _ in values], [0] * len(values)
    for i in range(len(values)):
        for j in range(i + 1, len(values)):
            if dominates(values[i], values[j]):
                dominated[i].append(j)
                counts[j] += 1
            elif dominates(values[j], values[i]):
                dominated[j].append(i)
                counts[i] += 1
    current = [i for i, count in enumerate(counts) if count == 0]
    fronts = []
    while current:
        fronts.append(current)
        following = []
        for i in current:
            for j in dominated[i]:
                counts[j] -= 1
                if counts[j] == 0:
                    following.append(j)
        current = following
    return fronts


def crowding_distance(values, front):
    """Normalized neighbor distances. Constant objectives contribute nothing."""
    distances = {i: 0.0 for i in front}
    for axis in range(len(values[0])):
        order = sorted(front, key=lambda i: values[i][axis])
        low, high = values[order[0]][axis], values[order[-1]][axis]
        if low == high:
            continue
        distances[order[0]] = distances[order[-1]] = math.inf
        for index in range(1, len(order) - 1):
            distances[order[index]] += (values[order[index + 1]][axis]
                                        - values[order[index - 1]][axis]) / (high - low)
    return distances


def nsga2(domain, evaluate, population_size=8, generations=20, seed=0, mutation_rate=0.2):
    """Rank/crowding tournament, categorical variation, elitist parent+offspring selection.

    One categorical fidelity gene: uniform crossover inherits either parent's category;
    mutation chooses another category. Sampling is with replacement; duplicate individuals
    are retained, as in a basic NSGA-II. Memoization counts unique objective evaluations.
    The diagnostic visited set never participates in selection.
    """
    if (not domain or len(set(domain)) != len(domain) or population_size < 2
            or generations < 0 or not 0 <= mutation_rate <= 1):
        raise ValueError('Use a unique nonempty domain, population >=2, generations >=0, mutation in [0,1]')
    rng = random.Random(seed)
    cache = {}

    def objectives(population):
        for candidate in population:
            if candidate not in cache:
                cache[candidate] = tuple(evaluate(candidate))
        values = [cache[c] for c in population]
        validate_objectives(values)
        return values

    def ranked(population):
        values = objectives(population)
        fronts = nondominated_sort(values)
        ranks, distances = {}, {}
        for rank, front in enumerate(fronts):
            ranks.update({i: rank for i in front})
            distances.update(crowding_distance(values, front))
        return fronts, ranks, distances

    population = [rng.choice(domain) for _ in range(population_size)]
    trace = []
    for generation in range(generations + 1):
        fronts, ranks, distances = ranked(population)
        trace.append(dict(generation=generation, unique_evaluations=len(cache),
                          population=list(population),
                          front=sorted(set(population[i] for i in fronts[0]))))
        if generation == generations:
            break

        def tournament():
            a, b = rng.sample(range(population_size), 2)
            ka, kb = (ranks[a], -distances[a]), (ranks[b], -distances[b])
            winner = a if ka < kb else b if kb < ka else rng.choice((a, b))
            return population[winner]

        children = []
        for _ in range(population_size):
            child = rng.choice((tournament(), tournament()))
            if len(domain) > 1 and rng.random() < mutation_rate:
                child = rng.choice([c for c in domain if c != child])
            children.append(child)
        combined = population + children
        fronts, _, distances = ranked(combined)
        selected = []
        for front in fronts:
            if len(selected) + len(front) <= population_size:
                selected.extend(front)
            else:
                # Random tie ordering avoids always favoring parent indices.
                rng.shuffle(front)
                front.sort(key=lambda i: distances[i], reverse=True)
                selected.extend(front[:population_size - len(selected)])
                break
        population = [combined[i] for i in selected]
    visited = list(cache)
    discovered = nondominated_sort([cache[c] for c in visited])[0]
    return dict(front=trace[-1]['front'], discovered_front=sorted(visited[i] for i in discovered),
                unique_evaluations=len(cache), objective_requests=population_size * (generations + 1),
                trace=trace)


def load_measurements(source):
    source = Path(source)
    metadata = json.loads((source / 'metadata.json').read_text(encoding='utf-8'))
    if metadata.get('status') != 'completed' or not metadata.get('all_counts_match_numpy'):
        raise ValueError('A completed, count-validated reuse benchmark is required')
    with (source / 'summary.csv').open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    fields = ('fidelity', 'node_error_mean', 'edge_error_mean', 'request_ms_mean', 'build_ms_mean')
    records = [{key: float(row[key]) for key in fields} for row in rows]
    fidelities = [r['fidelity'] for r in records]
    if not records or len(set(fidelities)) != len(records) or 1.0 not in fidelities:
        raise ValueError('Require distinct fidelity levels including an exact reference')
    for row in records:
        if (not 0 < row['fidelity'] <= 1 or any(not math.isfinite(v) or v < 0 for v in row.values())
                or (row['fidelity'] == 1 and any(row[k] != 0 for k in
                    ('node_error_mean', 'edge_error_mean', 'build_ms_mean')))):
            raise ValueError('Invalid measurement; exact reference must have zero error and sample cost')
    return sorted(records, key=lambda r: r['fidelity']), metadata


def candidates_for_reuse(records, requests):
    if type(requests) is not int or requests < 1:
        raise ValueError('Reuse requests must be a positive integer')
    return [dict(r, reuse_requests=requests,
                 modeled_cost_ms=r['request_ms_mean'] + r['build_ms_mean'] / requests)
            for r in records]


def choose_candidate(candidates, node_tolerance, edge_tolerance):
    """Cheapest recorded feasible level; empirical mean errors are NOT an error guarantee."""
    if any(not math.isfinite(t) or t < 0 for t in (node_tolerance, edge_tolerance)):
        raise ValueError('Error tolerances must be finite and nonnegative')
    feasible = [r for r in candidates if r['node_error_mean'] <= node_tolerance
                and r['edge_error_mean'] <= edge_tolerance]
    return min(feasible, key=lambda r: (r['modeled_cost_ms'], -r['fidelity'])) if feasible else None


def write_rows(path, rows):
    with path.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_optimization(source, output, reuse_requests=(1, 10, 100, 1000),
                     runs=30, population_size=8, generations=20, mutation_rate=0.2):
    if runs < 1 or not reuse_requests or len(set(reuse_requests)) != len(reuse_requests):
        raise ValueError('Use positive run count and distinct reuse scenarios')
    records, metadata = load_measurements(source)
    output = Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output folder must be new or empty')
    all_candidates, comparisons, traces, selections = [], [], [], []
    for requests in reuse_requests:
        candidates = candidates_for_reuse(records, requests)
        scores = [(r['modeled_cost_ms'], r['node_error_mean'], r['edge_error_mean']) for r in candidates]
        front_indices = nondominated_sort(scores)[0]
        exact_front = {candidates[i]['fidelity'] for i in front_indices}
        lookup = {r['fidelity']: scores[i] for i, r in enumerate(candidates)}
        for row in candidates:
            row['exhaustive_pareto'] = row['fidelity'] in exact_front
        all_candidates.extend(candidates)
        for seed in range(runs):
            result = nsga2(list(lookup), lookup.__getitem__, population_size, generations, seed, mutation_rate)
            found, visited = set(result['front']), set(result['discovered_front'])
            comparisons.append(dict(reuse_requests=requests, seed=seed,
                exhaustive_front=';'.join(map(str, sorted(exact_front))),
                nsga2_final_front=';'.join(map(str, sorted(found))),
                final_front_recall=len(found & exact_front) / len(exact_front),
                final_front_precision=len(found & exact_front) / len(found),
                discovered_front_recall=len(visited & exact_front) / len(exact_front),
                unique_evaluations=result['unique_evaluations'],
                objective_requests=result['objective_requests'], exhaustive_evaluations=len(candidates)))
            traces.append(dict(reuse_requests=requests, seed=seed, **result))
        for node, edge in ((0.02, 0.05), (0.01, 0.02), (0.0, 0.0)):
            selected = choose_candidate(candidates, node, edge)
            selections.append(dict(reuse_requests=requests, node_tolerance=node, edge_tolerance=edge,
                selected_fidelity=selected['fidelity'] if selected else None,
                modeled_cost_ms=selected['modeled_cost_ms'] if selected else None))
    output.mkdir(parents=True, exist_ok=True)
    write_rows(output / 'candidates.csv', all_candidates)
    write_rows(output / 'nsga2-runs.csv', comparisons)
    write_rows(output / 'selections.csv', selections)
    (output / 'traces.json').write_text(json.dumps(traces, indent=2) + '\n', encoding='utf-8')
    # Hash UTF-8 text with normalized LF so provenance survives Git's line endings.
    provenance = {name: hashlib.sha256((Path(source) / name).read_text(encoding='utf-8').encode('utf-8')).hexdigest()
                  for name in ('summary.csv', 'metadata.json')}
    result = dict(project_version=__version__, status='completed',
        created_at=datetime.now(timezone.utc).isoformat(), source_backend=metadata['backend'],
        graph_sha256=metadata['graph_sha256'], source_sha256=provenance,
        source=str(source), source_hash_encoding='UTF-8 text with normalized LF newlines',
        new_neo4j_measurements=False, model='mean recorded request_ms + mean build_ms / fixed reuse_requests',
        objectives=['modeled_cost_ms', 'node_error_mean', 'edge_error_mean'],
        scenarios=list(reuse_requests), runs=runs, population_size=population_size,
        generations=generations, mutation_rate=mutation_rate,
        search_space='recorded fidelity categories only; reuse is a fixed scenario, not an optimized gene',
        algorithm_reference='https://doi.org/10.1109/4235.996017',
        final_front_recall_mean=mean(r['final_front_recall'] for r in comparisons),
        complete_final_front_runs=sum(r['final_front_recall'] == 1 for r in comparisons),
        total_runs=len(comparisons))
    (output / 'metadata.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result
