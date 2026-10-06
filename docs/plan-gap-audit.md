# Original-plan gap audit — 2026-10-06

Audit target: implemented v0.5.0, commit `3eda5d5`.
Compared with the referenced conversation “ENSAM 机器人与具身智能”, the preserved
[v0.1 technical note](../v0.1/report/technical_note.md), current source and recorded results.
This is an implementation/evidence audit; no new benchmark was run.

## Original milestones versus evidence

| Original milestone | Current evidence | Remaining gap |
|---|---|---|
| v0.1 Python graph + fixed fidelity + controller | Preserved source, outputs and regression checks | Complete for its stated proof-of-concept scope |
| v0.2 Neo4j/Cypher real queries | Tiny fixture, optional driver, live COUNT validation, offline fallback | Complete for its stated foundation scope |
| v0.3 Standard workload / larger graph + memory measurement | Real measurements on one 50,000-node synthetic graph and five country COUNT predicates | No LDBC SNB, no measured scale sweep beyond 50k, no actual memory-usage measurements |
| v0.4 NSGA-II baseline | Categorical NSGA-II checked against exhaustive fronts on five recorded levels | Not integrated with live policy selection; no broader measured policy space; no energy objective |
| v0.5 Our adaptive method | Correction, calibrated bounds, escalation, hysteresis, four tiers; live measurements | Prototype completed; no novelty evidence, online error-feedback learning or transfer validation |
| v1.0 Energy + complete benchmark + report | Several honest per-release reports and raw measurements | Energy instrumentation and a unified final benchmark/report remain missing |

Version numbers describe releases, not proof that every original milestone requirement
has been fulfilled. In particular, v0.3 delivered a useful latency baseline but did not
complete the original memory/standard-workload milestone.

## Most important gaps

### 1. Representative workloads and scaling

All current live benchmark graphs share fingerprint
`b9f668062bf1dd230a7de8e63b9f1770deba2ff77d5bed4b108e0a354aef90a8`:
50,000 nodes, 149,996 stored edge records. Different sample seeds do not create new
graphs. Country predicates diversify queries on this same graph; the measured query
types remain node/edge COUNT. No standard LDBC workload, multi-hop query workload,
rare-predicate sweep or topology/size transfer has been measured.

Needed: an imported standard dataset/workload, an explicit mapping of which queries
support the chosen estimators, and graph-size/topology/seed sweeps with held-out graphs.
The `1/f²` edge estimator must not be reused unmodified for arbitrary path queries.

### 2. Actual memory and energy measurements

Recorded heap/page-cache settings are configuration values, not observed RAM use.
There is no per-run resident/peak memory, allocation or energy measurement.
Latency reduction alone does not establish an energy reduction.

The current low-fidelity implementation filters ranks on the full Neo4j graph.
Every node receives a sample rank; the full graph remains stored. It does not build
smaller graph representations or demonstrate lower storage/resident-memory cost.

Needed: define measured boundaries (client, database process, CPU package or whole
machine), collect actual memory/power/energy with idle/background accounting, and report
joules/request separately from latency. If smaller representations are a research goal,
implement and compare them explicitly rather than inferring memory savings from f.

### 3. NSGA-II is not yet the research comparator

`graph_mf/optimization.py` reads the v0.3.1 five-level summary and minimizes modeled
cost, mean node error and mean edge error. It does not optimize the v0.5 eight-level
controller, energy, sampling strategies, refresh policy or hysteresis settings.
`graph_mf/adaptive.py` chooses eligible levels directly with a cost-table minimum;
it does not call NSGA-II. The 120 exact-front recoveries validate this small categorical
integration, not an evolutionary search efficiency advantage.

Needed: compare exact, fixed-fidelity, exhaustive policy selection, NSGA-II-selected
policies and adaptive policies using the same workloads, error budgets and setup costs.
Use a genuinely broader measured policy space and track evaluation budgets. Distinguish
offline policy optimization from runtime controller decisions.

### 4. Adaptive decisions work; online learning remains absent

Runtime gains, uncertainty bounds and latency tables are frozen after calibration.
The controller uses returned counts to reject sparse samples, but does not audit unknown
true error, update gains/bounds from feedback, or learn changing latency profiles.
Its fingerprint checks keep calibration graph-specific; unknown predicates/graphs fall
back to exact. Explicit import/rank overwrites invalidate samples, but arbitrary external
mutations and concurrent updates are outside the supported lifecycle.

Needed: periodic exact audits with fully charged cost, drift detection, bounded profile
refresh, sample freshness and a mutation/version protocol. A persistent streaming/API
entry point would retain hysteresis across requests; separate CLI invocations reset it.

### 5. Performance and error evidence need strengthening

The long-reuse mixed stream averaged 32.63 ms including sample-build allocation versus
34.63 ms for exact, an observed 5.8% reduction. It used only two independent sample
seeds on the same warm-cache graph. Repeated requests are useful for timing but do not
create independent accuracy trials. There is no confidence interval for that cost difference.

Short cached streams had no overall build-inclusive advantage. The balanced tier
violated its budget on 3.3% of requests in that run, with repeated errors correlated
within a sample. Correction improved some metrics and worsened others.
Offline correction fitting and timing profiling were reported separately, not amortized
into the displayed online cost; cold-start/recalibration economics remain untested.

Needed: more independent seeds/graphs/runs, paired or blocked timing analysis, uncertainty
at the correct independent unit, cold/warm cache and short/long streams, and full
startup/recalibration accounting. Preserve the currently reported unfavorable results.

### 6. Novelty and final research presentation

The agreed DLSS-inspired prototype is implemented. A claim of a new research algorithm
requires a precise contribution relative to existing approximate-query/calibration
controllers, meaningful baselines and ablations. Current code and measurements alone
do not establish this. No literature novelty review was performed in this audit.

Needed: a formal algorithm specification, relevant prior-work comparison, ablations
for correction/gating/hysteresis/cost planning, and a unified report that supports the
claims made on the CV. There are currently no robotics/embodied-intelligence experiments.

## Recommended work order

1. Complete the missed standard-workload/scaling and actual-memory milestone.
2. Run a fair exact/fixed/exhaustive/NSGA-II/adaptive comparison with stronger independent evidence.
3. Add online audit/drift/refresh feedback and measure its cost, including budget violations.
4. Add energy measurements and the performance–energy–accuracy objective.
5. Consolidate methods, evidence, limitations and novelty analysis into the v1.0 report.

## Evidence locations

- [Original preserved roadmap](../v0.1/report/technical_note.md)
- [NSGA-II scope and evaluation](v04-optimization.md)
- [Adaptive measurements and limitations](v05-adaptive.md)
- [Adaptive controller](../graph_mf/adaptive.py)
- [Offline NSGA-II experiment](../graph_mf/optimization.py)
- [Full-graph sampling backend](../graph_mf/synthetic.py)
- [Long-reuse metadata](../results/neo4j/adaptive-long-reuse-50k-v05/metadata.json)
