# v0.14 — Confidence-driven progressive sampling

The requested DLSS-style behavior is implemented as a sequential sampling controller:
start at low fidelity, inspect the measured sample, accept if empirical uncertainty fits
the error budget, otherwise increase fidelity. Unknown predicates and sparse unsupported
realizations fall back to exact. Server pressure does not relax the error budget.

## Independent learning and calibration

On the 50,000-node static synthetic graph, four fitting seeds learn a multiplicative
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

## Observed result — neo4j

| Mode | Known predicate budget failures | Unseen predicate failures | Approximate answers | Mean attempts | Online ms | Full pipeline s |
|---|---:|---:|---:|---:|---:|---:|
| exact | 0/40 | 0/60 | 0/100 | 1.00 | 1963.4 | 1.96 |
| fixed_raw | 5/40 | 14/60 | 100/100 | 1.00 | 1725.3 | 28.64 |
| fixed_corrected | 7/40 | 14/60 | 100/100 | 1.00 | 1698.1 | 93.42 |
| gated_raw | 1/40 | 0/60 | 40/100 | 1.00 | 2724.9 | 94.45 |
| gated_corrected | 1/40 | 0/60 | 40/100 | 1.00 | 2579.5 | 94.30 |
| dynamic_raw | 0/40 | 0/60 | 40/100 | 2.60 | 4179.1 | 95.90 |
| dynamic_corrected | 1/40 | 0/60 | 40/100 | 2.70 | 4540.1 | 96.26 |

Error budget is 5%. Fixed policies use 25% fidelity. `gated_*` select the cheapest profiled
component satisfying a static bound; `dynamic_*` probe progressively and inspect current
raw count. All raw COUNTs, including discarded probes, match the independent Python graph.
`probes.csv` retains every step, uncertainty, accept/reject decision and query cost.

Training workflow: 64.81 s. Test sample preparation: 26.91 s.
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
python scripts/report_sample_correction.py --source results/neo4j/dynamic-correction-v014
```

The Neo4j runner requires the existing validated synthetic import and changes only its sample
ranks. Original v0.1, full LDBC results and earlier negative experiments remain preserved.
