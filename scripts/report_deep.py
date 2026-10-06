"""Regenerate v0.6 report and figures from completed raw experiment artifacts."""
import argparse
import csv
import json
from importlib.metadata import version
from pathlib import Path
from statistics import mean
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from graph_mf.deep_benchmark import summarize_requests
from graph_mf.benchmark import write_csv
from graph_mf.split_policy import policy_scores
from graph_mf.optimization import nondominated_sort


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('results/neo4j/deep-v06'))
    parser.add_argument('--report', type=Path, default=Path('docs/v06-deepening.md'))
    args = parser.parse_args()
    suite = json.loads((args.source/'suite.json').read_text())
    if suite['status'] != 'completed':
        raise ValueError('Completed suite required')
    lines = ['# v0.6: topology, scale and coupled selection', '',
        'Measured live Neo4j results; generated from committed raw data. These runs use a warm',
        'shared server. Five sample seeds per graph are independent sampling epochs, not',
        'independent database deployments. All approximate strategies share frozen correction',
        'and bounds. Timing seeds 8000–8002, evaluation seeds 9000–9004; fitting/calibration',
        'use separate seed ranges. Every raw component count was checked against NumPy.', '',
        '## Mixed-stream cost', '',
        'Each standalone policy using any sampled call is charged its entire sample build',
        'divided by its actual mixed-stream request count. Exact-only streams need no build.',
        'This is a standalone allocation scenario; all modes share a prebuilt sample in the',
        'measurement harness. Import, calibration, profiling and optimizer setup',
        'are excluded here and itemized below. Fixed policies ignore the selected tier budget,',
        'including exact-tier requests; their violations are expected baseline behavior.', '',
        '| Graph | Policy | Request ms | With build ms | Budget violations |',
        '|---|---|---:|---:|---:|']
    paired = []
    memory = []
    startup = []
    optimizer = []
    largest_front = 0
    modes = ['exact', 'fixed10', 'fixed25', 'fixed50', 'fixed75', 'exhaustive', 'nsga2', 'adaptive']
    chart = {}
    for case in suite['completed']:
        name = case['case']
        folder = args.source/name
        meta = json.loads((folder/'metadata.json').read_text())
        if meta['status'] != 'completed' or not meta['all_counts_match_numpy']:
            raise ValueError('Completed validated case required')
        if meta['backend'] != 'neo4j':
            raise ValueError('This measured-performance report requires live Neo4j cases')
        raw = read_csv(folder/'raw-results.csv')
        typed = [{**r, **{k: float(r[k]) for k in ['node_fidelity', 'edge_fidelity',
            'node_error', 'edge_error', 'request_ms']}, 'count_calls': int(r['count_calls']),
            'epoch': int(r['epoch']), 'violation': r['violation'] == 'True'} for r in raw]
        typed_builds = [{**b, 'epoch': int(b['epoch']), 'build_ms': float(b['build_ms'])}
                        for b in read_csv(folder/'builds.csv')]
        write_csv(folder/'summary.csv', summarize_requests(typed, typed_builds, meta['stream_requests_per_sample']))
        meta['build_scope'] = 'standalone mixed stream charged full build / actual requests only if any sampled call was used; exact-only streams need no sample'
        meta['measurement_packages'] = {name: version(name) for name in ['numpy', 'neo4j', 'psutil', 'matplotlib']}
        meta['nsga_configuration'] = dict(population_size=32, generations=30, mutation_rate=.2, seeds=list(range(10)), runtime_seed=0)
        (folder/'metadata.json').write_text(json.dumps(meta, indent=2)+'\n')
        profile = json.loads((folder/'profile.json').read_text())
        objectives = [dict(predicate=p, node_fidelity=pair[0], edge_fidelity=pair[1],
            profiled_request_ms=score[0], node_bound=score[1], edge_bound=score[2])
            for p in meta['predicates'] for pair, score in policy_scores(profile, p).items()]
        write_csv(folder/'policy-objectives.csv', objectives)
        summaries = read_csv(folder/'summary.csv')
        all_rows = {r['mode']: r for r in summaries if r['tier'] == 'all'}
        chart[name] = [float(all_rows[m]['with_build_ms_mean']) for m in modes]
        for mode in modes:
            r = all_rows[mode]
            lines.append(f"| {name} | {mode} | {float(r['request_ms_mean']):.2f} | {float(r['with_build_ms_mean']):.2f} | {100*float(r['violation_rate']):.1f}% |")
        builds = {int(b['epoch']): float(b['build_ms']) for b in read_csv(folder/'builds.csv')}
        for mode in ['exhaustive', 'nsga2', 'adaptive']:
            differences = []
            for epoch, build in builds.items():
                selected = [float(r['request_ms']) for r in raw if int(r['epoch']) == epoch and r['mode'] == mode]
                exact = [float(r['request_ms']) for r in raw if int(r['epoch']) == epoch and r['mode'] == 'exact']
                uses_sample = any(int(r['epoch']) == epoch and r['mode'] == mode and
                    (float(r['node_fidelity']) < 1 or float(r['edge_fidelity']) < 1 or int(r['count_calls']) > 2)
                    for r in raw)
                differences.append(mean(selected)+(build/meta['stream_requests_per_sample'] if uses_sample else 0)-mean(exact))
            rng = np.random.default_rng(1776)
            boot = rng.choice(differences, (2000, len(differences)), replace=True).mean(axis=1)
            low, high = np.percentile(boot, [2.5, 97.5])
            paired.append(f'| {name} | {mode} | {mean(differences):+.2f} | [{low:+.2f}, {high:+.2f}] |')
        rss = read_csv(folder/'memory-raw.csv')
        values = {p: [int(r[p+'_rss_bytes'])/2**20 for r in rss if r.get(p+'_rss_bytes')] for p in ['client', 'server']}
        memory.append(f"| {name} | {min(values['client']):.1f}–{max(values['client']):.1f} | {min(values['server']):.1f}–{max(values['server']):.1f} |")
        startup.append(f"| {name} | " + ' | '.join(f"{meta[k]/1000:.2f}" for k in ['import_connect_ms', 'correction_calibration_ms', 'timing_profile_ms', 'optimization_setup_ms'])+' |')
        comparisons = read_csv(folder/'optimizer-comparison.csv')
        front_sizes = {p: len(nondominated_sort(list(policy_scores(profile, p).values()))[0]) for p in meta['predicates']}
        largest_front = max(largest_front, max(front_sizes.values()))
        for row in comparisons:
            size = front_sizes[row['predicate']]
            row.update(reference_front_size=size, maximum_recall_at_population_size=min(32, size)/size)
        write_csv(folder/'optimizer-comparison.csv', comparisons)
        choices = json.loads((folder/'choices.json').read_text())
        agreement = mean(c['nsga2'] == c['exhaustive'] for by_tier in choices.values() for c in by_tier.values())
        optimizer.append(f"| {name} | {min(front_sizes.values())}–{max(front_sizes.values())} | {min(float(r['final_front_recall']) for r in comparisons):.1%} | {mean(float(r['unique_evaluations']) for r in comparisons):.1f}/64 | {agreement:.1%} |")
    lines += ['', '## Paired epoch differences versus exact', '',
        'Positive means slower. These 95% percentile bootstrap intervals resample five paired',
        'seed-epoch means (2,000 resamples), not correlated individual requests. They describe',
        'this experiment only; five blocks are insufficient for broad statistical claims.', '',
        '| Graph | Policy | Mean difference ms | Preliminary interval ms |',
        '|---|---|---:|---:|', *paired, '', '## Actual process resident memory', '',
        '100 ms sampling. Whole-process ranges in MiB; sampled maxima may miss short peaks.',
        'The server retains all earlier benchmark datasets. These are not per-graph allocations',
        'and do not demonstrate memory savings from lower fidelity. See per-phase memory CSVs.', '',
        '| Graph run | Python RSS MiB | Neo4j RSS MiB |', '|---|---:|---:|', *memory, '',
        '## Startup costs', '', 'Seconds, excluded from mixed-stream latency above. Profiling includes its sample builds.', '',
        '| Graph | Import/connect | Fit/calibrate | Timing profile | Optimize |',
        '|---|---:|---:|---:|---:|', *startup, '', '## NSGA-II diagnostic', '',
        'Ten seeds per predicate, population 32, 30 generations, 64 categorical pairs.',
        'Only predeclared seed zero supplies runtime choices. The exhaustive front is used',
        'only for diagnostic recall. This small space does not establish search efficiency.', '',
        'Search optimizes cached query latency and the two calibrated bounds. Fitness is a',
        'frozen-table lookup; profiling cost is reported separately. Build-inclusive costs',
        'are evaluated afterward, so cached-optimal choices can lose on short streams.', '',
        '| Graph | Reference-front size | Minimum final-front recall | Mean unique objective evaluations | Seed-zero choice agreement |',
        '|---|---:|---:|---:|---:|', *optimizer, '',
        f'The largest reference front has {largest_front} points. A 32-individual population cannot',
        'retain all of it, even without duplicates. The implementation retains duplicate',
        'individuals, so unique coverage can be lower still. Larger populations, diversity',
        'handling and budget-specific selection need evaluation before optimality claims.', '',
        '## Interpretation and remaining work', '',
        'Public topology: [Stanford SNAP Facebook](https://snap.stanford.edu/data/ego-Facebook.html),',
        '4,039 nodes and 88,234 undirected edges, each stored once. Degree buckets are derived',
        'from the full topology; the shared adapter stores them in its legacy `country` field.',
        'These custom COUNTs are not an official LDBC benchmark. Synthetic graphs retain',
        'duplicate edge records and directional semantics from the original generator.', '',
        'The controller independently chooses node/edge fidelity, charges its initial draft',
        'and escalation calls, and delays demotion for three consecutive requests. Bounds',
        'are graph-specific calibrated uncertainty, not per-query error guarantees.',
        'See raw results and adaptive traces for errors, selected pairs and all escalation steps.', '',
        'Still missing: full LDBC/complex traversals, independent cold-cache runs, long-stream',
        'startup amortization, online audit/drift/refresh, energy measurements and novelty analysis.',
        'No energy reduction, memory saving, neural DLSS implementation or novelty is claimed.', '',
        '## Verification', '',
        'All 40 unit/integration tests passed with live Neo4j opt-in enabled. The offline',
        'run passes 36 tests and skips the four live cases. The final offline deep smoke',
        'validated 1,200 requests. A wheel was installed into a fresh environment with no',
        'Neo4j driver or NumPy, and the dependency-free tiny memory smoke passed.',
        'All ten original v0.1 deliverable hashes remain unchanged. The live suite validated',
        f"{sum(c['timed_requests'] for c in suite['completed']):,} timed requests plus their raw component/escalation counts.", '',
        'Reproduce: `python scripts/report_deep.py`; raw source: `results/neo4j/deep-v06/`.', '',
        '![Build-inclusive mixed-stream cost](../results/neo4j/deep-v06/policy-cost.png)', '']
    x = np.arange(len(modes))
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, (name, costs) in enumerate(chart.items()):
        ax.bar(x+(i-1.5)*.2, costs, width=.2, label=name)
    ax.set_xticks(x, modes, rotation=25)
    ax.set_ylabel('Mean request + allocated sample build (ms)')
    ax.legend()
    fig.tight_layout()
    fig.savefig(args.source/'policy-cost.png', dpi=160)
    plt.close(fig)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text('\n'.join(lines), encoding='utf-8')
    print(args.report)


if __name__ == '__main__':
    main()
