"""Offline ablations on frozen v0.6 profiles. No new database performance claim."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from graph_mf.benchmark import write_csv
from graph_mf.optimization import nsga2, nondominated_sort
from graph_mf.split_policy import policy_scores, choose
from graph_mf.adaptive import TIERS


CONFIGS = [('dedup32', 32, 30, .2), ('capacity48', 48, 30, .2), ('improved48', 48, 40, .35)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('results/neo4j/deep-v06'))
    parser.add_argument('--output', type=Path, default=Path('results/optimization/v07-search'))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('New or empty output required')
    suite = json.loads((args.source/'suite.json').read_text(encoding='utf-8'))
    if suite['status'] != 'completed':
        raise ValueError('Completed v0.6 suite required')
    args.output.mkdir(parents=True, exist_ok=True)
    rows, choices, hashes, fronts = [], [], {}, {}
    for case in suite['completed']:
        name = case['case']
        folder = args.source/name
        profile_path = folder/'profile.json'
        content = profile_path.read_text(encoding='utf-8').replace('\r\n', '\n')
        hashes[name] = hashlib.sha256(content.encode()).hexdigest()
        profile = json.loads(content)
        old_choices = json.loads((folder/'choices.json').read_text(encoding='utf-8'))
        with (folder/'optimizer-comparison.csv').open(newline='', encoding='utf-8') as stream:
            for r in csv.DictReader(stream):
                if int(r['seed']) < 5:
                    rows.append(dict(case=name, predicate=r['predicate'], config='legacy32', seed=int(r['seed']),
                        recall=float(r['final_front_recall']), unique_evaluations=int(r['unique_evaluations']),
                        setup_ms=None))
        for predicate in profile['countries']:
            scores = policy_scores(profile, predicate)
            domain = list(scores)
            oracle = {domain[i] for i in nondominated_sort(list(scores.values()))[0]}
            for tier, budgets in TIERS.items():
                optimal = choose(scores, budgets)
                old = tuple(old_choices[predicate][tier]['nsga2'])
                choices.append(dict(case=name, predicate=predicate, tier=tier, config='legacy32',
                    optimal_pair=str(optimal), selected_pair=str(old), agreement=old == optimal,
                    profiled_regret_ms=scores[old][0]-scores[optimal][0]))
            for config, population, generations, mutation in CONFIGS:
                for seed in range(5):
                    start = perf_counter()
                    result = nsga2(domain, scores.__getitem__, population, generations, seed, mutation,
                                   eliminate_duplicates=True)
                    elapsed = 1000*(perf_counter()-start)
                    front = [tuple(p) for p in result['front']]
                    rows.append(dict(case=name, predicate=predicate, config=config, seed=seed,
                        recall=len(set(front)&oracle)/len(oracle),
                        unique_evaluations=result['unique_evaluations'], setup_ms=elapsed))
                    if seed == 0:
                        fronts[name+'/'+predicate+'/'+config] = front
                        for tier, budgets in TIERS.items():
                            selected, optimal = choose(scores, budgets, front), choose(scores, budgets)
                            choices.append(dict(case=name, predicate=predicate, tier=tier, config=config,
                                optimal_pair=str(optimal), selected_pair=str(selected), agreement=selected == optimal,
                                profiled_regret_ms=scores[selected][0]-scores[optimal][0]))
            write_csv(args.output/'raw-search.csv', rows)
            write_csv(args.output/'choices.csv', choices)
            print(name, predicate, 'completed', flush=True)
    summary = []
    for name in hashes:
        for config in ['legacy32', *[c[0] for c in CONFIGS]]:
            subset = [r for r in rows if r['case'] == name and r['config'] == config]
            decisions = [r for r in choices if r['case'] == name and r['config'] == config]
            summary.append(dict(case=name, config=config, minimum_recall=min(r['recall'] for r in subset),
                mean_recall=mean(r['recall'] for r in subset),
                unique_evaluations_mean=mean(r['unique_evaluations'] for r in subset),
                choice_agreement=mean(r['agreement'] for r in decisions),
                profiled_regret_ms_max=max(r['profiled_regret_ms'] for r in decisions)))
    write_csv(args.output/'summary.csv', summary)
    (args.output/'runtime-fronts.json').write_text(json.dumps(fronts, indent=2)+'\n', encoding='utf-8')
    (args.output/'metadata.json').write_text(json.dumps(dict(status='completed', source_profiles_sha256=hashes,
        configurations=CONFIGS, seeds=list(range(5)), runtime_seed=0, new_neo4j_measurements=False,
        scope='post-v06 engineering ablation on same frozen profiles; no independent generalization or search-efficiency claim',
        oracle='diagnostic only; never used by search or runtime front'), indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
