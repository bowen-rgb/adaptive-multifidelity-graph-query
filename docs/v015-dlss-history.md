# v0.15 — Speed/accuracy tiers with reusable work

## DLSS-inspired scope

The controller trades allowed COUNT error for computation: quality 5%, balanced 10%,
performance 20%. These are explicit application error budgets, not NVIDIA presets.
It uses empirical calibration and history to choose the first probe, then escalates
if current uncertainty is too high. Demotion is considered after three sufficiently
confident requests. There is no neural rendering, GPU-pressure integration or formal
per-request confidence guarantee. Unseen predicates fall back to exact.

## What changed

- Start from a measured feasible forecast or the last accepted fidelity, rather than
  replaying every low tier for every request.
- Incremental node probes count only the new rank interval. Edge probes partition
  newly included directed edges into new-source/any-destination and old-source/new-
  destination groups. Parallel edges remain separate and are counted once.
- Keep graph validation at the static-session boundary and guard incremental queries
  against rank-generation replacement using published ready state. Concurrent arbitrary
  graph writers and in-place graph mutation are unsupported. Exact fallback remains exact.
- Execute fresh COUNTs for every request: no cached answer table. Only sampling ranks,
  calibration and controller history are reused. Exact terminal probes discard already
  paid approximate work. All intermediate counts match the direct Python reference.

## Short matched streams

One static 50k-node synthetic graph, FR/DE, three held-out rank epochs, 60 request pairs
per tier/epoch; mode order randomized, warm server cache without flushes. A pair is node
and edge COUNT. Repeated requests on an epoch are correlated; the epoch is the repeat
unit, not each COUNT. The fixture has only two known predicates, so this does not show
unseen-query or cross-graph generalization. No correction gain is used in either dynamic
variant because v0.14 did not establish a correction benefit.

| Tier | Method | Online ratio vs exact | Max actual error | Budget failures | Mean COUNT attempts | Ratio incl. recorded startup |
|---|---|---:|---:|---:|---:|---:|
| quality | exact | 1.00 | 0.00% | 0 | 1.00 | 1.000 |
| quality | history_incremental | 1.42 | 3.99% | 0 | 1.01 | 0.110 |
| quality | progressive | 0.41 | 3.99% | 0 | 4.97 | 0.093 |
| balanced | exact | 1.00 | 0.00% | 0 | 1.00 | 1.000 |
| balanced | history_incremental | 1.89 | 6.41% | 0 | 1.01 | 0.123 |
| balanced | progressive | 0.75 | 11.72% | 56 | 2.97 | 0.112 |
| performance | exact | 1.00 | 0.00% | 0 | 1.00 | 1.000 |
| performance | history_incremental | 2.91 | 11.72% | 0 | 1.00 | 0.116 |
| performance | progressive | 1.00 | 11.72% | 0 | 2.23 | 0.108 |

## Longer stream and amortization

- exact: 8,000 request pairs, online 372.74 s, recorded startup 0.00 s, phase total 372.74 s, phase-total ratio 1.00×, max error 0.00%, 0 budget failures.
- history_incremental: 8,000 request pairs, online 137.51 s, recorded startup 71.94 s, phase total 209.45 s, phase-total ratio 1.78×, max error 7.66%, 0 budget failures.

The phase-total comparison sums separately measured training from v0.14, sample builds
for this comparison and measured online controller/query durations. Training is charged
once to each alternative method; each tier is considered a separate deployment.
Exact pays no training or sample build. This is a composition of measured phases,
not one continuous timed lifecycle. The existing graph import, source-profile loading,
session constructor and offline oracle checking are excluded. Harness wall time includes
validation and is retained separately. No energy or whole-machine throughput claim is made.
Long runs use distinct held-out seeds; only two independent epochs and one graph limit
statistical confidence. Do not infer general 1.x/2.x speedups from these local observations.

Break-even estimates in summary.json use measured mean savings, assuming unchanged future
workload, cache, sample validity and timing. A nonpositive saving has no break-even.
Higher tiers may still overshoot empirical error estimates, and history can become stale.
Results include the slower original progressive policy and its budget failures.
Most optimized requests used one probe, so the measured gain cannot be attributed
specifically to incremental deltas. Calibration hot starts, accepted-tier reuse and
moving fingerprint work to the static-session boundary are combined here; separate
ablations against fixed calibrated tiers remain necessary.

## Reproduce

```powershell
python scripts/benchmark_dlss_history.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 3 --requests 60 --output results/local/new-frontier
python scripts/benchmark_dlss_history.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 2 --seed-start 20000 --requests 4000 --tiers performance --modes exact history_incremental --output results/local/new-long-stream
python scripts/report_dlss_history.py --source results/neo4j/dlss-history-v015-complete --long-source results/neo4j/dlss-history-v015-long
```

Existing valid synthetic import is required; no graph is deleted/reimported. Sample ranks
are explicitly refreshed once per epoch. Original experiments and full LDBC results remain.
Next gates are more independent epochs/topologies, nonrepeating parameterized aggregates,
and explicit stale-profile/update detection before deployment.
