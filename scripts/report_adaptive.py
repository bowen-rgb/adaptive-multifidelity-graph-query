"""Regenerate summaries, report and optional plots from completed v0.5 runs."""
import csv
import json
from pathlib import Path
from statistics import mean
from graph_mf.adaptive_benchmark import summarize
from graph_mf.benchmark import write_csv

ROOT = Path(__file__).resolve().parents[1]
RUNS = [('amortized', 'adaptive-50k-v05'), ('cached', 'adaptive-cached-50k-v05'),
        ('cached-long', 'adaptive-long-reuse-50k-v05')]


def read_run(name, policy):
    folder = ROOT / 'results' / 'neo4j' / name
    metadata = json.loads((folder / 'metadata.json').read_text())
    if metadata['status'] != 'completed' or not metadata['all_counts_match_numpy']:
        raise ValueError(f'{name} is incomplete/unvalidated')
    with (folder / 'raw-results.csv').open(newline='') as file:
        rows = list(csv.DictReader(file))
    for row in rows:
        for key in ('request_ms', 'fidelity', 'node_error', 'edge_error', 'node_budget', 'edge_budget'):
            row[key] = float(row[key])
        row['queries'] = int(row['queries'])
        for key in ('budget_violation', 'interval_miss'):
            row[key] = row[key] == 'True' if row[key] else None
    with (folder / 'builds.csv').open(newline='') as file:
        builds = [dict(build_ms=float(r['build_ms'])) for r in csv.DictReader(file)]
    summary = summarize(rows, builds, metadata['stream_requests_per_sample'])
    write_csv(folder / 'summary.csv', summary)
    # First run preceded the addition of an explicit policy metadata field.
    metadata.setdefault('cost_policy', 'cached' if policy.startswith('cached') else 'amortized')
    metadata.setdefault('baseline_fidelities', [0.1, 0.25, 0.5, 0.75])
    (folder / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    decisions = json.loads((folder / 'decisions.json').read_text())
    return dict(folder=folder, metadata=metadata, rows=rows, summary=summary, decisions=decisions)


def main():
    runs = [(policy, read_run(name, policy)) for policy, name in RUNS]
    text = ['# Measured adaptive aggregate scaling — v0.5', '',
        'Measured 2026-10-06 on local Neo4j 2026.09.0 Enterprise: 50,000 nodes / 149,996 edge records.',
        'Five predicates (FR/DE/ES/IT/NL), eight levels (5/10/15/25/35/50/75/100%).',
        'Warm cache, one serial client. Each request returns a pair of COUNT aggregates.', '',
        '## Measured results', '',
        '| Planning scenario | Tier | Request mean / p95 (ms) | Including build amortization (ms) | Exact reference mean (ms) | Node / edge mean error | Budget violations |',
        '|---|---|---:|---:|---:|---:|---:|']
    for policy, run in runs:
        for row in run['summary']:
            if row['mode'] != 'adaptive':
                continue
            exact = next(r for r in run['summary'] if r['mode'] == 'exact' and r['tier'] == row['tier'])
            text.append(f"| {policy} | {row['tier']} | {row['request_ms_mean']:.2f} / {row['request_ms_p95']:.2f} | "
                f"{row['amortized_ms_mean']:.2f} | {exact['request_ms_mean']:.2f} | "
                f"{100*row['node_error_mean']:.2f}% / {100*row['edge_error_mean']:.2f}% | {100*row['budget_violation_rate']:.1f}% |")
    text += ['', 'Request latency includes the initial low draft, all escalation queries, state checks,',
        'correction and controller decisions. Graph generation/import and connection startup are excluded.',
        'Each standalone adaptive stream receives the full measured sample-build cost, divided by',
        'its actual request count per sample. Exact reference streams need no sample.',
        'The mixed stream allocates sample cost to every request, including requests returning exact results.',
        'This allocation is not the cost of running the exact tier alone, which needs no sample.', '',
        'The amortized planner selected exact COUNT for all final answers in its measured run;',
        'sample construction and initial drafts therefore made that adaptive stream more expensive.',
        'The cached planner minimizes query cost after an existing sample is available. Query-only',
        'savings do not establish overall savings when a sample is refreshed frequently.', '',
        '## Complete mixed-stream cost', '',
        '| Stream | Controller + build mean (ms/request) | Exact reference mean (ms/request) | Observed cost change |',
        '|---|---:|---:|---:|']
    for policy, run in runs:
        adaptive_rows = [r for r in run['rows'] if r['mode'] == 'adaptive']
        exact_rows = [r for r in run['rows'] if r['mode'] == 'exact']
        adaptive_cost = mean(r['request_ms'] for r in adaptive_rows) + run['metadata']['sample_build_ms_mean'] / run['metadata']['stream_requests_per_sample']
        exact_cost = mean(r['request_ms'] for r in exact_rows)
        text.append(f'| {policy} | {adaptive_cost:.2f} | {exact_cost:.2f} | {100*(adaptive_cost/exact_cost-1):+.1f}% |')
    text += ['', 'This table accounts for the entire measured mixture, including exact-tier requests.',
        'Per-tier construction charges above are allocations within that mixture, not a claim',
        'that each tier alone served 1,000 requests. Fitting/profiling setup costs remain separate.', '',
        '## Costs, scope and independent samples', '']
    for policy, run in runs:
        m = run['metadata']
        text.append(f"- {policy}: {len(m['evaluation_seeds'])} held-out sample seeds, {m['measured_requests']:,} "
            f"timed requests, {m['stream_requests_per_sample']} requests per standalone sample/stream; "
            f"mean build {m['sample_build_ms_mean']:.2f} ms. "
            f"Import/connect {m['import_connect_ms']/1000:.2f} s; offline fitting/calibration "
            f"{m['calibration_cpu_ms']/1000:.2f} s; timing profiling {m['timing_profiling_ms']/1000:.2f} s.")
    total = sum(r['metadata']['measured_requests'] for _, r in runs)
    text += ['', f'Raw COUNTs for all {total:,} timed requests and all adaptive escalation steps matched NumPy.',
        'These are repeated requests, not independent accuracy trials. The first two streams serve',
        '100 requests per sample; the long-reuse stream actually serves 1,000, rather than extrapolating.',
        'The long stream has only two independent samples and is a conditional cost demonstration.',
        'Its accuracy/violation rates must not be read as broad statistical guarantees.',
        'The short cached balanced tier violated a budget on 3.3% of requests. Repetitions share',
        'one sampling error, so this percentage is not a rate over independent queries.',
        'Timing profiling used separate sample seeds before each evaluation run. Each run has its',
        'own contemporaneous exact and fixed references; cross-run timings are not a controlled causal ablation.', '',
        '## Correction ablation on the same returned levels', '',
        '| Stream | Approximate requests | Raw node / edge mean error | Corrected node / edge mean error |',
        '|---|---:|---:|---:|']
    for policy, run in runs:
        approximate = [d for d in run['decisions'] if d['fidelity'] < 1]
        if not approximate:
            text.append(f'| {policy} | 0 | n/a | n/a |')
            continue
        truth = {(int(r['seed']), r['country']): (float(r['node_estimate']), float(r['edge_estimate']))
                 for r in run['rows'] if r['mode'] == 'exact'}
        errors = {}
        for prefix in ('raw_', ''):
            for index, kind in enumerate(('node', 'edge')):
                errors[prefix+kind] = mean(abs(d[prefix+kind+'_estimate'] - truth[(d['seed'], d['country'])][index])
                    / truth[(d['seed'], d['country'])][index] for d in approximate)
        text.append(f"| {policy} | {len(approximate)} | {100*errors['raw_node']:.3f}% / {100*errors['raw_edge']:.3f}% | "
                    f"{100*errors['node']:.3f}% / {100*errors['edge']:.3f}% |")
    text += ['', 'Correction gains may help or hurt these held-out samples; the table is a paired',
        'comparison of the same returned levels, not a claim that calibration always improves accuracy.', '',
        '## Agreed DLSS-inspired mechanism', '',
        'The project owner approved low-fidelity drafts, calibration-based correction, uncertainty',
        'gating and hysteresis. This implements that agreed prototype; it does not establish novelty,',
        'implement NVIDIA DLSS, use neural super-resolution, or reconstruct arbitrary graph topology.', '',
        'For nodes use count/f; for edges use count/f². Fit a multiplicative least-squares correction',
        'per level/metric from seeds 2000–2019, then freeze it. Separately calibrate with seeds',
        '3000–3039. One calibration score is the maximum normalized relative residual over all',
        'five predicates, seven approximate levels and both metrics in a sample epoch. The 39th',
        'ordered score of 40 supplies a nominal 95% joint threshold. This deliberately conservative',
        'scheme keeps correlated queries within one independent unit.', '',
        'Calibration uses a split-calibration order statistic inspired by',
        '[Angelopoulos and Bates](https://arxiv.org/abs/2107.07511). Exchangeability and a fixed',
        'workload are assumptions; no per-query guarantee or validity under graph/predicate shift is claimed.',
        'All corrections, uncertainty bounds and timing tables are frozen before evaluation seeds.',
        'Exact answers are used in fitting and post-return evaluation, never as runtime controller inputs.',
        'The profile contains gains/bounds, not cached exact COUNT answers.', '',
        'If relative residual bound is b<1, the interval is [prediction/(1+b), prediction/(1-b)].',
        'The controller checks both node/edge budgets, minimum sample counts, then raises fidelity.',
        'Promotion for a tighter budget is immediate. Demotion requires three consecutive requests',
        'favoring the cheaper lower level. A changed country or sample generation resets history.',
        'Unknown countries or a graph-fingerprint mismatch fall back to exact. Manual mutations',
        'outside the project import APIs remain unsupported by the static-sample lifecycle.', '',
        '## Tier presets', '',
        '| Tier | Node budget | Edge budget |', '|---|---:|---:|',
        '| performance | 5% | 15% |', '| balanced | 2% | 5% |',
        '| quality | 1% | 2% |', '| exact | 0% | 0% |', '',
        'Tiers specify error budgets, not fixed fidelity percentages. The cached experiment',
        'demonstrates runtime transitions; the defaults can legitimately select exact when cheaper.', '',
        '## Plots', '', '![Measured costs](../results/neo4j/adaptive-cached-50k-v05/adaptive-costs.png)', '',
        '![Tier transitions](../results/neo4j/adaptive-cached-50k-v05/tier-transitions.png)', '',
        '## Reproduce', '', '```sh',
        'python -m graph_mf --backend neo4j adaptive-benchmark --output results/local/new-amortized',
        'python -m graph_mf --backend neo4j adaptive-benchmark --cost-policy cached --epochs 6 --evaluation-seed 6000 --output results/local/new-cached',
        'python -m graph_mf --backend neo4j adaptive-benchmark --cost-policy cached --epochs 2 --repeats-per-tier 40 --timing-epochs 2 --evaluation-seed 7000 --baseline-fidelities --output results/local/new-long',
        'python scripts/report_adaptive.py', '```', '',
        'The report generator reads the three committed named result folders; its plots require matplotlib.',
        'Metadata, profiles, timing measurements, builds, raw requests and per-request decisions are retained.',
        'Memory backend runs the same controller/validation workflow without Neo4j.', '',
        '## Validation and limits', '',
        '30 offline tests passed; four existing opt-in integration tests were skipped. New live',
        'measurement requests were separately validated against NumPy as recorded above.',
        'Offline tests cover correction, budget tightening, delayed demotion, sparse/unknown fallback,',
        'exact bypass, generation reset, independent calibration splits and explicit cost policies.',
        'CLI/package smoke, archived v0.1 hashes and GitHub checks are also verified.',
        'No cold-cache, graph-size transfer, changing-graph, rare/new predicate, concurrency, energy',
        'or memory-use experiment was performed. Approximate errors on this graph are not evidence',
        'of performance or accuracy on LDBC/social/robotics workloads. NSGA-II remains a separate',
        'recorded-candidate baseline; coupling it to a broader measured policy space is future work.', '']
    (ROOT / 'docs' / 'v05-adaptive.md').write_text('\n'.join(text), encoding='utf-8')
    plot_runs(runs)


def plot_runs(runs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, len(runs), figsize=(15, 4.5), squeeze=False)
    tiers = ['performance', 'balanced', 'quality', 'exact']
    for ax, (policy, run) in zip(axes.flat, runs):
        adaptive = [next(r for r in run['summary'] if r['mode'] == 'adaptive' and r['tier'] == t) for t in tiers]
        exact = [next(r for r in run['summary'] if r['mode'] == 'exact' and r['tier'] == t) for t in tiers]
        x = list(range(4))
        ax.plot(x, [r['request_ms_mean'] for r in adaptive], 'o-', label='Controller request')
        ax.plot(x, [r['amortized_ms_mean'] for r in adaptive], 's-', label='Including build')
        ax.plot(x, [r['request_ms_mean'] for r in exact], '^-', label='Exact reference')
        ax.set_xticks(x, tiers, rotation=20)
        ax.set_ylabel('Mean milliseconds / COUNT pair')
        ax.set_title(policy + f" | {run['metadata']['stream_requests_per_sample']} requests/sample")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    fig.tight_layout()
    folder = runs[1][1]['folder']
    fig.savefig(folder / 'adaptive-costs.png', dpi=160)
    plt.close(fig)
    run = runs[1][1]
    seed = run['metadata']['evaluation_seeds'][0]
    country = max(run['metadata']['countries'], key=lambda c: len({d['fidelity']
        for d in run['decisions'] if d['seed'] == seed and d['country'] == c}))
    decisions = [d for d in run['decisions'] if d['seed'] == seed and d['country'] == country]
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.step(range(len(decisions)), [d['fidelity']*100 for d in decisions], where='mid', label='Executed fidelity')
    ax.step(range(len(decisions)), [d['desired_fidelity']*100 for d in decisions], where='mid',
            linestyle='--', label='Desired fidelity')
    for index, decision in enumerate(decisions):
        if index == 0 or decision['tier'] != decisions[index-1]['tier']:
            ax.axvline(index, color='gray', alpha=0.3)
            ax.text(index+0.1, 103, decision['tier'], fontsize=9)
    ax.set_ylim(0, 116)
    ax.set_ylabel('Fidelity (%)')
    ax.set_xlabel(f'Request in one {country} stream')
    ax.set_title(f'Cached policy ({country}): budget tightening and delayed demotion')
    ax.grid(alpha=0.2)
    ax.legend(loc='lower right')
    fig.tight_layout()
    fig.savefig(folder / 'tier-transitions.png', dpi=160)
    plt.close(fig)


if __name__ == '__main__':
    main()
