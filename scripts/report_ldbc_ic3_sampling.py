"""Summarize fixed-tier IC3 feasibility without treating empty answers as evidence."""
import argparse
import csv
import json
from pathlib import Path
from graph_mf.synthetic import numpy


def summarize(root):
    meta=json.loads((root/'metadata.json').read_text())
    if meta['status']!='completed' or not meta['exact_tuples_match']:
        raise ValueError('Completed exact-validated IC3 run required')
    with (root/'requests.csv').open(newline='') as handle:
        rows=list(csv.DictReader(handle))
    blocks=meta['blocks'];pairs=len(meta['parameters']);modes=sorted({r['mode'] for r in rows})
    if len({(r['block'],r['parameter'],r['mode']) for r in rows})!=len(rows) or len(rows)!=blocks*pairs*len(modes):
        raise ValueError('Duplicate/incomplete IC3 records')
    np=numpy();indices=np.random.default_rng(36000).integers(0,blocks,(10000,blocks))
    def costs(mode):
        return np.array([sum(float(r['online_ms']) for r in rows if r['mode']==mode and int(r['block'])==b) for b in range(blocks)])
    reference=costs('reference');exact=costs('population_exact');summary=[]
    for mode in modes:
        selected=[r for r in rows if r['mode']==mode];timings=costs(mode)
        nonempty=[r for r in selected if int(r['exact_rows'])>0]
        boot=exact[indices].sum(axis=1)/timings[indices].sum(axis=1)
        summary.append(dict(mode=mode,requests=len(selected),nonempty_requests=len(nonempty),
            reference_ratio=float(reference.sum()/timings.sum()),population_exact_ratio=float(exact.sum()/timings.sum()),
            bootstrap_low=float(np.quantile(boot,.025)),bootstrap_high=float(np.quantile(boot,.975)),
            nonempty_quality_passes=sum(r['meets_quality']=='True' for r in nonempty),
            mean_nonempty_recall=sum(float(r['recall']) for r in nonempty)/len(nonempty) if nonempty else None,
            max_count_error=max((float(r['max_count_error']) for r in nonempty),default=None),
            measured_ms=float(timings.sum())))
    (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return meta,summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official',type=Path,required=True)
    parser.add_argument('--stress',type=Path,required=True)
    args=parser.parse_args()
    stress_answers=json.loads((args.stress/'answers.json').read_text())['exact']
    counts=[row[k] for answer in stress_answers for row in answer for k in ('xCount','yCount')]
    lines=['# v0.18 — IC3 message-sampling feasibility','',
        'Read-only runs on a quiescent SF0.1 database after prior reference updates,',
        'not a fresh initial snapshot or a complete mixed workload. The official query',
        'is pinned upstream; the candidate retains exact Person/KNOWS candidates and',
        'Bernoulli-samples Message IDs. Counts scale by 1/f. Full-tier ordered tuples',
        'are checked against the upstream query before accepting each measured block.',
        '', '## Results','',
        '| Parameters | Mode | vs upstream | vs population exact (95% paired block bootstrap) | Nonempty quality passes | Mean recall | Worst count error |',
        '|---|---|---:|---:|---:|---:|---:|']
    for trial,root in [('official substitutions',args.official),('custom wide-window stress',args.stress)]:
        meta,summary=summarize(root)
        for row in summary:
            recall='n/a' if row['mean_nonempty_recall'] is None else f"{row['mean_nonempty_recall']:.3f}"
            error='n/a' if row['max_count_error'] is None else f"{100*row['max_count_error']:.1f}%"
            lines.append(f"| {trial} | {row['mode']} | {row['reference_ratio']:.2f} | {row['population_exact_ratio']:.2f} [{row['bootstrap_low']:.2f}, {row['bootstrap_high']:.2f}] | {row['nonempty_quality_passes']}/{row['nonempty_requests']} | {recall} | {error} |")
    lines+=['', '## Interpretation and limits','',
        'The first eight randomly selected official substitutions return empty exact',
        'answers. Empty/empty agreement is reported but does not validate preservation',
        'of nonempty rankings. That initial run also contains candidate compilation cost.',
        'The stress trial uses the same roots, the globally most frequent two message',
        'countries and the full observed date range, without selecting on root answers.',
        'Those custom parameters are not official substitution or certification results.',
        f"Stress exact result sizes: {[len(answer) for answer in stress_answers]};",
        f"{sum(c==1 for c in counts)} of {len(counts)} per-country counts are one. At fidelity",
        '0.75 an observed single message scales to 1.333, already outside a 20% budget',
        'for a true count of one. This is a sparse-count quantization limit, not a',
        'reason to silently relax the target or hide missing people.',
        '',
        'Before either run, the fixed quality target is recall >= 0.9 and maximum',
        'relative x/y/combined count error <= 0.2. Missing exact top-20 people count',
        'as 100% errors, rather than being removed from accuracy statistics. Recall',
        'alone is insufficient; ranking displacement and false people are retained',
        'in raw CSV and ordered answer records. Three blocks reuse eight parameters;',
        'they are not 24 independent query parameters. Bootstrap is descriptive.',
        '',
        'Every candidate request freshly fetches eligible message IDs, transfers them,',
        'samples in Python and executes Cypher. All those costs are included online.',
        'Warmup and stress parameter preparation are separately recorded; import,',
        'test-oracle calls and driver initialization are excluded. The exact population',
        'candidate is necessary to separate a query-plan improvement from sampling.',
        'No answer cache, graph mutation, fitted quality model or adaptive gate is used.',
        'Equal before/after node/edge counts do not detect every possible external edit.',
        '',
        'This is a feasibility pilot. It does not establish full LDBC adaptive gains.',
        'All sampled stress requests fail the predeclared tuple-quality target, and',
        'this ID-fetch implementation is slower than the upstream exact query. It',
        'must not be enabled in the mixed driver. Screening denser aggregate query',
        'families is preferable to calibrating this sparse workload into universal fallback.',
        'A tier that is quicker but fails tuple quality cannot be accepted just because',
        'its COUNT estimate looked confident. Next work requires independent quality',
        'calibration and conservative exact fallback before the mixed-workload adapter.',
        '', '## Reproduction','', '```powershell',
        '$env:NEO4J_DATABASE="your-quiescent-full-snb-database"',
        '# Supply credentials through environment configuration.',
        'python scripts/benchmark_ldbc_ic3_sampling.py --reference PATH_TO_PINNED_IMPL --parameters PATH_TO_PARAMS --output results/local/ic3-official',
        'python scripts/benchmark_ldbc_ic3_sampling.py --reference PATH_TO_PINNED_IMPL --parameters PATH_TO_PARAMS --stress-wide-window --output results/local/ic3-stress',
        f'python scripts/report_ldbc_ic3_sampling.py --official {args.official.as_posix()} --stress {args.stress.as_posix()}',
        '```','',
        'Source: [pinned upstream IC3](https://github.com/ldbc/ldbc_snb_interactive_v1_impls/blob/11db98cc2ba14c33492f6c0c34e68c8be7e22e5f/cypher/queries/interactive-complex-3.cypher).','']
    Path('docs/v018-ldbc-ic3-sampling.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines))


if __name__=='__main__':main()
