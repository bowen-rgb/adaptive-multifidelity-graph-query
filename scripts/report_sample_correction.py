"""Summarize independent correction/calibration and progressive sampling costs."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    a=p.parse_args()
    meta=json.loads((a.source/'metadata.json').read_text())
    if meta['status']!='completed' or not meta['all_raw_counts_match']:
        raise ValueError('Completed, raw-validated results required')
    with (a.source/'requests.csv').open(newline='') as f: rows=list(csv.DictReader(f))
    with (a.source/'setup.csv').open(newline='') as f: setup=list(csv.DictReader(f))
    preparation=sum(float(r['sample_preparation_ms']) for r in setup)
    table=[]; summaries={}
    for mode in meta['summary']:
        selected=[r for r in rows if r['mode']==mode]
        known=[r for r in selected if r['scope']=='known']
        unseen=[r for r in selected if r['scope']=='unseen']
        online=sum(float(r['online_ms']) for r in selected)
        training=0 if mode in ('exact','fixed_raw') else meta['training_ms']
        prep=0 if mode=='exact' else preparation
        total=training+prep+online
        known_fail=sum(r['within_budget']=='False' for r in known)
        unseen_fail=sum(r['within_budget']=='False' for r in unseen)
        approximate=sum(float(r['fidelity'])<1 for r in selected)
        attempts=mean(int(r['attempts']) for r in selected)
        summaries[mode]=dict(online_ms=online,total_ms=total,training_ms=training,preparation_ms=prep,
                            known_failures=known_fail,unseen_failures=unseen_fail,approximate=approximate,
                            mean_attempts=attempts)
        table.append(f'| {mode} | {known_fail}/{len(known)} | {unseen_fail}/{len(unseen)} | '
                     f'{approximate}/{len(selected)} | {attempts:.2f} | {online:.1f} | {total/1000:.2f} |')
    (a.source/'cost-summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    Path('docs/v014-dynamic-sampling.md').write_text(f'''# v0.14 — Confidence-driven progressive sampling

The requested DLSS-style behavior is implemented as a sequential sampling controller:
start at low fidelity, inspect the measured sample, accept if empirical uncertainty fits
the error budget, otherwise increase fidelity. Unknown predicates and sparse unsupported
realizations fall back to exact. Server pressure does not relax the error budget.

## Independent learning and calibration

On the {meta['nodes']:,}-node static synthetic graph, four fitting seeds learn a multiplicative
gain per COUNT component/fidelity from FR/DE. Twenty distinct calibration seeds compute
empirical residual scores, with one seed as the unit and the maximum over both predicates.
Calibration does not refit gains. Ten additional seeds test FR/DE and unseen ES/IT/NL.
Unknown predicates are exact for gated/dynamic methods; this is explicit safe fallback,
not evidence that the learned correction generalizes to them.

The dynamic score uses a count-adjusted residual scale:

`uncertainty = calibrated_score × sqrt(fitting_mean_sample_count / max(current_sample_count, 1))`

The score is calibrated after applying the same count normalization to calibration residuals.
Raw samples smaller than 20 cannot trigger approximate acceptance. The last level is exact.
The gain multiplies the usual node `count/f` or induced-edge `count/f²` estimate. Edge inclusion
is correlated, so this empirical rule is not a binomial edge confidence interval.
Per-level calibration is not a joint or selected-level coverage guarantee; adaptive stopping,
small calibration sets and distribution shift still require held-out evaluation.

## Observed result — {meta['backend']}

| Mode | Known predicate budget failures | Unseen predicate failures | Approximate answers | Mean attempts | Online ms | Full pipeline s |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(table)}

Error budget is 5%. Fixed policies use 25% fidelity. `gated_*` select the cheapest profiled
component satisfying a static bound; `dynamic_*` probe progressively and inspect current
raw count. All raw COUNTs, including discarded probes, match the independent Python graph.
`probes.csv` retains every step, uncertainty, accept/reject decision and query cost.

Training workflow: {meta['training_ms']/1000:.2f} s. Test sample preparation: {preparation/1000:.2f} s.
Full pipeline adds both to online cost for learned policies; exact pays neither, and fixed
raw pays preparation only. The implemented workflow fits and calibrates together, so this
conservative total charges the whole workflow even to fixed corrected, which could in
principle skip calibration. Offline Python checking is outside timed test requests;
training time includes its verification overhead. Every discarded probe is paid.

This tests reliability and stopping behavior, not the previous search-efficiency endpoint.
A gain can worsen an already unbiased estimator: correction must beat the no-correction
ablation rather than being presumed useful. Zero observed failures can result from many
exact fallbacks and does not establish a universal accuracy guarantee. A speedup claim
requires lower full cost against exact at matched acceptable error, not just fewer samples.

Current larger-fidelity probes rerun COUNTs over nested ranks; they do not incrementally
reuse previous scans. Cache/order effects and one static graph limit performance inference.
There is no GPU integration, learned machine-load policy or automatic latency-pressure switch.
Next work should optimize probe reuse and amortization, validate across budgets/graphs, and
merge validated confidence gates into budgeted search. A variance-aware method may be
more useful than multiplicative correction on these unbiased synthetic counts.

```powershell
python scripts/benchmark_sample_correction.py --backend memory --runs 5 --output results/local/new-correction
python scripts/benchmark_sample_correction.py --backend neo4j --runs 10 --output results/local/new-live-correction
python scripts/report_sample_correction.py --source {a.source.as_posix()}
```

The Neo4j runner requires the existing validated synthetic import and changes only its sample
ranks. Original v0.1, full LDBC results and earlier negative experiments remain preserved.
''',encoding='utf-8')
    print('\n'.join(table))


if __name__=='__main__': main()
