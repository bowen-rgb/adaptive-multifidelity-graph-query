# v0.18 — Topology and held-out parameter validation

20,000 nodes and the same 59,993 directed edge records per graph. Country attributes
are identical; connectivity is uniform, 85% within ID-block communities, or
weighted toward hub IDs. Parallel edges remain separate; self loops are excluded.
The experiment refits for each graph; it is not zero-shot cross-topology transfer.

Queries count nodes or edges with both endpoints in a country and a half-open
node-ID interval. Training uses eight fixed predicates, four fitting rank seeds
and twenty independent calibration seeds. Each test parameter tuple is unique
and absent from training. Node/edge pairs and methods share parameters intentionally.
Fidelity selection transfers empirical family calibration to unseen intervals;
the finite training predicate set does not guarantee accuracy on all intervals.

The cost guard uses only fitting-time forecasts: choose the cheapest feasible
tier if its predicted cost is at least 10% below exact, otherwise execute exact.
This rule was fixed after the pilot and before six new confirmation ranks and
new query parameters. Pilot outcomes are not used as per-query oracle answers.

## Live results

| Trial | Topology | Policy | Online ratio (paired 95% bootstrap) | Failures | Approximate | Phase ratio with training/builds |
|---|---|---|---:|---:|---:|---:|
| pilot | uniform | adaptive | 1.33 [1.14, 1.59] | 0/480 | 282/480 | 0.07 |
| pilot | community | adaptive | 1.17 [1.06, 1.30] | 0/480 | 300/480 | 0.07 |
| pilot | hub | adaptive | 0.97 [0.84, 1.14] | 0/480 | 212/480 | 0.05 |
| confirmation | uniform | adaptive | 0.72 [0.46, 1.10] | 0/480 | 279/480 | 0.07 |
| confirmation | uniform | cost_guard | 1.08 [1.04, 1.13] | 0/480 | 279/480 | 0.07 |
| confirmation | community | adaptive | 1.12 [1.06, 1.16] | 0/480 | 306/480 | 0.06 |
| confirmation | community | cost_guard | 1.15 [1.11, 1.20] | 0/480 | 306/480 | 0.06 |
| confirmation | hub | adaptive | 1.07 [1.01, 1.15] | 0/480 | 213/480 | 0.05 |
| confirmation | hub | cost_guard | 1.07 [1.03, 1.13] | 0/480 | 213/480 | 0.05 |

## Measurement boundaries

Each trial has six paired rank epochs, forty distinct parameter pairs per epoch
and changing 5%/10%/20% error budgets. Bootstrap resamples epochs, not correlated
node/edge answers. These are descriptive host-local intervals on a warm server.
Training includes rank construction and raw-oracle checks; all discarded runtime
probes and exact fallbacks are charged online. Import is measured separately and
excluded from the phase ratio; profile loading/test-oracle checking are excluded.
The pilot did not separately time controller initialization; confirmation does.
Previously measured training is charged once to each non-exact confirmation policy.
These short streams do not establish a startup-inclusive performance improvement.
No observed budget failures would still not establish a production guarantee.
The confirmation guard and baseline chose identical tiers and probe counts;
timing differences therefore do not establish a causal cost-guard benefit.

The v0.17 1.34× amortization result remains a different known-predicate long-stream
experiment. Do not transfer that number to this parameter family or every topology.
Custom interval COUNTs are not LDBC operations. See the separate
[LDBC adaptive acceptance plan](ldbc-adaptive-acceptance.md) for remaining work.

## Reproduction

```powershell
python scripts/benchmark_parameter_transfer.py --backend neo4j --nodes 20000 --epochs 6 --queries 40 --output results/local/new-parameter-pilot
python scripts/benchmark_parameter_cost_guard.py --backend neo4j --source results/local/new-parameter-pilot --epochs 6 --queries 40 --output results/local/new-parameter-confirmation
python scripts/report_parameter_transfer.py --source results/neo4j/parameter-transfer-v018 --confirmation results/neo4j/parameter-cost-guard-v018
```
