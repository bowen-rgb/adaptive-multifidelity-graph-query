"""Rebuild a scoped report from budget-search measurements, including shared setup."""
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
    if meta['status']!='completed':
        raise ValueError('Completed measurements required')
    with (a.source/'runs.csv').open(newline='') as f:
        rows=list(csv.DictReader(f))
    with (a.source/'setup.csv').open(newline='') as f:
        setup={int(r['run']):float(r['setup_ms']) for r in csv.DictReader(f)}
    table=[]
    for method in meta['methods']:
        subset=[r for r in rows if r['method']==method]
        if len(subset)!=meta['runs']:
            raise ValueError('Incomplete method measurements')
        search_ms=mean(float(r['search_ms']) for r in subset)
        full_ms=mean(float(r['search_ms'])+setup[int(r['run'])] for r in subset)
        reference_ms=mean(float(r['exhaustive_ms'])+setup[int(r['run'])] for r in subset)
        regret=[float(r['reference_cost_ratio']) for r in subset if r['reference_cost_ratio']]
        table.append(f"| {method} | {search_ms:.1f} | {full_ms:.1f} | {reference_ms/full_ms:.2f} | "
                     f"{mean(regret):.2f} | {sum(r['heldout_pass']=='True' for r in subset)}/{len(subset)} |")
    oracle_ms=mean(float(r['exhaustive_ms']) for r in rows)
    Path('docs/v013-budgeted-search.md').write_text(f'''# v0.13 — Budgeted measured search

## Research question

Can a small number of measured configurations identify a useful feasible fidelity pair,
at lower search cost than enumeration? The production search has no exhaustive table.
Enumeration remains a separately charged evaluation reference, not a proposed deployment policy.

## Implemented experiment

64 node/edge fidelity pairs, budget {meta['budget']} per method, {meta['runs']} random-rank epochs,
{meta['nodes']:,} synthetic nodes, backend **{meta['backend']}**, error budget {meta['tolerance']:.0%}.
Every objective evaluation executes four real COUNT components on training predicates FR/DE.
All methods use measured candidates only for the returned decision. Their orders are randomized
per epoch. Exhaustive measurement starts only after all budgeted searches finish.
ES/IT/NL predicates are evaluated only after selection. They share the static graph and sampling
epoch; this is a predicate holdout, not an independent graph/generalization guarantee.

Random search samples without replacement. NSGA-II stops when the next novel measurement
would exceed the budget and returns the best feasible measured candidate from its visited set.
The surrogate uses distance-weighted regression of measured cost/error, a charged exact anchor,
and periodic exploration of distant configurations. It learns configuration quality;
**answer bias correction and calibrated uncertainty are not implemented in this experiment**.

## Measured result

| Method | Search ms | Setup + search ms | Enumeration / method incl. setup | Selected cost / reference optimum | Held-out budget passes |
|---|---:|---:|---:|---:|---:|
{chr(10).join(table)}

Mean enumeration search time: {oracle_ms:.1f} ms. Shared setup includes rank preparation and
10 exact truth queries; `setup.csv` records it explicitly. It is charged once to either method
in the setup-inclusive comparison, not divided across methods to manufacture a win.
Verification executes six additional held-out components per returned configuration;
its cost is separately recorded in `runs.csv` and excluded from the above search-only endpoint.
The entire experimental job also executes every method and enumeration; these comparisons
are alternative method costs, not the runtime of the whole experimental job.

Reducing 64 evaluations to 16 is a budget assignment, not evidence that the learned method
beats the other budgeted methods. Quality, feasible coverage, and held-out failures must be
considered together. Runtime minima in a noisy measured oracle can exaggerate regret;
single-machine cache/order effects and this small domain prevent a broad superiority claim.
No full SNB throughput, calibrated accuracy guarantee, or production query acceleration is claimed.

## Next acceptance gates

1. Repeat each configuration timing and pair orders to reduce winner/noise bias.
2. Add independent fit/calibration/test predicates and a measured bias-correction ablation.
3. Compare learning and no-learning variants across budgets 8/16/32, against random and NSGA-II.
4. Expand beyond 64 configurations only with meaningful query/sample design choices.
5. Evaluate across graph scales/topologies; count preparation, training, verification and amortization.

```powershell
python scripts/benchmark_budget_search.py --backend memory --runs 5 --budget 16 --output results/local/new-budget-smoke
# Neo4j: existing validated synthetic import; rank preparation is recorded, no graph reimport.
python scripts/benchmark_budget_search.py --backend neo4j --runs 10 --budget 16 --output results/local/new-budget-live
python scripts/report_budget_search.py --source {a.source.as_posix()}
```

Input graph fingerprint, seeds, evaluations and selected configurations are retained in the source
directory. This first experiment tests search efficiency; it does not replace the earlier reference validation.
''',encoding='utf-8')
    print('\n'.join(table))


if __name__=='__main__':
    main()
