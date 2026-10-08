# v0.16 — What actually helps, and public evidence

## Acceptance scope

The project has a reproducible, measurable use: calibration-guided approximate COUNTs
can save query computation on known static predicates at explicit error budgets.
This supports a scoped CV engineering/research claim. It does not establish an original
DLSS algorithm, superiority over every search method, complete SNB approximate speedup,
or accuracy guarantees under changed graphs. The v0.15 longer stream demonstrated a
1.78× ratio across recorded training/preparation/online phases at a 20% budget.

## Changing-budget ablations

50,000-node synthetic graph, six independent new rank epochs, 60 request pairs/epoch,
FR/DE, identical inputs per method. Error budgets change through 20%, 5%, 10%, 20%, 5%,
20%, exercising tightening and relaxation. Every output/probe COUNT matches the raw oracle.
All variants use the same static-session fingerprint boundary and generation guards.
Session construction is measured here. No answer cache is used.

- `full`: forecast + accepted-tier history + incremental escalation.
- `no_history`: recalculates the forecasted start for each request, keeps current-sample gating.
- `no_incremental`: same history/start decisions but re-queries the full selected sample.
- `cold_incremental`: starts at the lowest tier every request and uses incremental escalation.
- `exact`: fresh exact node/edge queries without learning or sample requirements.

| Method | Online ratio vs exact | Paired bootstrap 95% interval | Budget failures | Mean COUNT attempts |
|---|---:|---:|---:|---:|
| exact | 1.00 | [1.00, 1.00] | 0/720 | 1.00 |
| full | 1.56 | [1.53, 1.60] | 0/720 | 1.16 |
| no_history | 1.70 | [1.61, 1.82] | 0/720 | 1.13 |
| no_incremental | 1.63 | [1.54, 1.76] | 0/720 | 1.16 |
| cold_incremental | 0.83 | [0.78, 0.89] | 0/720 | 3.29 |

The bootstrap resamples whole paired seed epochs, not individual repeated requests.
Six blocks on one host are a small descriptive uncertainty estimate, not a general
significance/coverage guarantee. Sampling/training startup is excluded in this table;
the separate long-stream v0.15 comparison charges it explicitly. All methods share
warm-server conditions and randomized per-epoch order without cache flushing.
These short streams do not amortize startup: 50k `no_history`: 0.18× including recorded training/build/online phases. 100k: 0.19× on the same basis.
That phase-cost comparison excludes graph import, profile loading and offline checks;
each strategy is charged the shared recorded training and all epoch builds once.

## Independent graph-size check

Second scale: 100,000 nodes; independently refit/recalibrated, 6 fresh test epochs.

| Method | Online ratio vs exact | Paired bootstrap 95% interval | Budget failures | Mean COUNT attempts |
|---|---:|---:|---:|---:|
| exact | 1.00 | [1.00, 1.00] | 0/720 | 1.00 |
| full | 2.37 | [2.26, 2.49] | 20/720 | 1.09 |
| no_history | 2.53 | [2.35, 2.81] | 9/720 | 1.13 |
| no_incremental | 2.39 | [2.31, 2.49] | 20/720 | 1.09 |
| cold_incremental | 1.39 | [1.31, 1.47] | 20/720 | 2.50 |

This refits for each size; it is not zero-shot transfer of the 50k profile. Both graphs
use the same generator/topology family and two known predicates. Nonrepeating queries,
different topology, stale-profile detection and update workloads remain acceptance gaps.
At 100k, `no_history` misses the requested budget on 9/720 components (1.25%);
the combined variant misses on 20/720 (2.78%). The raw COUNT checks validate query
implementation, not the extrapolated estimates. Empirical bounds are not certified
coverage guarantees. The faster 100k result must be reported with these violations.

## Interpretation and implementation decision

History and incrementality must earn their cost rather than being assumed helpful.
On the 50k fixture the forecast/current-uncertainty variant without history was faster
than the combined variant, and removing incremental accumulation did not harm its
mean latency. The cold-start variant was slower than exact despite sampling.
The strongest supported mechanism is calibration-guided starting fidelity and acceptance,
not temporal history or delta accumulation in this workload. The prototype exposes
these mechanisms as optional ablations; none is presented as a proven universal improvement.
Failed demotion now resets hysteresis patience to avoid retrying the same futile low
probe on every request. Precision losses and preparation costs stay explicit.

## Public repository and CV

Repository: https://github.com/bowen-rgb/adaptive-multifidelity-graph-query (PUBLIC).
Before exposure, reachable Git history was scanned for the known session credential,
common API/token/key signatures and unredacted driver properties. No findings were
reported; this is a signature check, not security certification. Large input archives,
database credentials and environments are not tracked. Official query snapshots retain
the pinned upstream attribution, Apache LICENSE and NOTICE under `third_party/ldbc`.
No new license grant for original project code is inferred from public visibility.

[CV wording](cv-project.md) states measured scope and known limitations. Prefer the
calibration/sampling result for algorithm roles, and official-reference validation for
database roles. Be ready to reproduce and explain the contribution and error/cost trade-off.

```powershell
python scripts/benchmark_dlss_ablation.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 6 --requests 60 --output results/local/new-ablation
python scripts/report_dlss_ablation.py --source results/neo4j/dlss-ablation-v016
python scripts/benchmark_sample_correction.py --backend neo4j --nodes 100000 --runs 3 --output results/local/new-100k-profile
python scripts/benchmark_dlss_ablation.py --backend neo4j --source results/local/new-100k-profile --epochs 6 --requests 60 --output results/local/new-100k-ablation
python scripts/audit_publication.py --output results/local/new-publication-audit.json
```
