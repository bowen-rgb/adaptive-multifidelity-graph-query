# Adaptive Multi-Fidelity Graph Query — v0.14.0

## Confidence-driven dynamic sampling

The [dynamic sampling experiment](docs/v014-dynamic-sampling.md) starts at low
fidelity and escalates when a calibrated, count-adjusted empirical uncertainty exceeds
the error budget. Fitting, calibration and testing use disjoint sampling seeds.
Every discarded probe is charged; unknown predicates fall back to exact. This is an
empirical stopping policy, not a per-request probabilistic guarantee or GPU integration.
The live ablation retains correction failures and the unfavorable full-cost comparison.

## Current algorithm focus: budgeted measured search

The [budgeted search experiment](docs/v013-budgeted-search.md) evaluates candidates
with actual COUNT queries instead of reading a precomputed objective table. Random,
NSGA-II and a learned cost/error surrogate each receive 16 measurements over 64
fidelity pairs. Enumeration runs afterward as an independent reference. Shared setup,
search and held-out verification are recorded separately. This experiment learns
configuration quality; answer correction and calibrated uncertainty remain next steps.
It does not yet establish superiority of the surrogate over the other budgeted methods.

The [current goal audit](docs/current-goal-audit.md) distinguishes completed engineering
from the remaining research hypothesis; [CV wording](docs/cv-project.md) is available in
English and French. Reference validation covered 138,474 operations across 29 types.
The short mixed runs actually executed 28 types. Their mean cumulative service cost
was 39.04 s for the reference and 46.43 s for materialization: no overall service win.
Fixed-arrival throughput does not measure maximum sustainable throughput.

An additional paired IC9 experiment compared 150 timed queries across 15 parameters
and five blocks. Full ordered results matched, but local top-k slowed mean latency
from 79.28 to 114.60 ms; the candidate remains experimental and was not adopted.
v0.12.1 also fixes schedule evidence so warmup PASS cannot mask measurement FAIL.

## Main objective: measured performance and complete SNB Interactive v1

The priority is a fair end-to-end improvement and the complete official Interactive
v1 workload: 14 complex reads, 7 short reads and 8 updates. Full exact validation
and approximate research experiments are reported separately. Energy extensions
and further micro-fixture tuning are deferred until the main comparison is established.

v0.12 adds a full CsvComposite/LongDateFormatter streaming loader, a pinned official
Java-driver build/routing workflow, validation and mixed-workload launchers, and
exact IC14 reply-weight materialization maintained by comment/friendship updates.
The official SF0.1 snapshot has **327,588 nodes and 1,477,965 relationships**.
Original experiments and the dependency-free memory fallback remain available.

On one updated SF0.1 graph, exact IC14 averaged 26.10 ms versus 3.01 ms with weights
(8.68× query-only speedup), but construction took 3.00 s: approximately 131 requests
to amortize. A bound-endpoint rewrite instead slowed the query by 13.5× and is retained.
These are fixed-parameter warm-cache experiments; they do not prove mixed-workload
throughput improvement or a DLSS-adaptive benefit. The official driver must verify
actual operation coverage and scheduling separately.

See [the full runbook](docs/ldbc-full-runbook.md) for separate databases, restore/reload,
all-operation validation, mixed workloads, exact maintenance and measurement boundaries.

## v0.11: pinned SNB micro-fixture and query semantics

The official SNB v1 test projection contains 222 Person nodes and 825 KNOWS edges.
Two CSVs are hash-pinned to upstream commit `11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`;
raw inputs stay outside Git. Attribution and upstream notices are in `third_party/ldbc`.
IS3 ordered friend tuples are checked for every Person against the Python reference.
The Person/KNOWS projection uses isolated labels and a fingerprint namespace.

```powershell
python scripts/download_snb_micro.py --output results/local/snb-input
python -m graph_mf --backend memory snb-benchmark --dataset-path results/local/snb-input --epochs 2 --roots 8 --output results/local/snb-smoke
python -m graph_mf --backend neo4j snb-benchmark --dataset-path results/local/snb-input --epochs 3 --roots 32 --output results/local/snb-live
```

The additional one-hop and distinct 1–2-hop COUNTs are custom. One-hop sampling holds
the root fixed and scales sampled neighbors by `1/f`; full IS3 stays exact. Multi-hop
requests fall back to exact because target inclusion probabilities are not generally
`f²`. Sample generation checks reject sequential replacement/reimport; concurrent
writers and arbitrary external edits are unsupported. The existing country controller
and NSGA-II are not yet calibrated/integrated for this parameterized COUNT workload.

**Measured:** 894 live business queries passed tuple/raw-count validation. At 10%
one-hop fidelity mean error was 65.24%, with 49 empty samples despite nonzero truth
among 96 selected queries. This is a micro-fixture semantic experiment, not full SNB,
SF1, an official driver run or representative performance evidence.
See [the report and coverage matrix](docs/v011-snb-semantics.md).

## v0.10: energy instrumentation, hardware measurement still pending

`energy-probe` distinguishes CPU-package counters from GPU-only power snapshots.
`energy-benchmark` instruments the existing exact/cached/amortized COUNT streams.
Linux powercap support reads top-level package counters, samples wrap intervals,
rejects ambiguous gaps/jumps, and records before/after idle baselines. No overlapping
core/uncore domains are added. `--max-package-watts` (default 500) is a user-confirmed
per-package ceiling for ambiguity checks, never a power estimate for computing joules.
No concurrent counter resets are allowed. The Linux adapter has fixture tests;
physical RAPL validation has not been performed on this Windows host.

```powershell
python -m graph_mf energy-probe --output results/local/new-probe.json
python -m graph_mf --backend memory energy-benchmark --epochs 2 --requests 5 --output results/local/new-energy-smoke
python -m graph_mf --backend neo4j energy-benchmark --epochs 3 --requests 30 --output results/local/new-energy-live
```

**This host:** CPU joules are unavailable, the GPU snapshot is excluded, and the
energy objective stays disabled. Missing energy is null, not zero. Python process
CPU time is recorded separately and is never converted to energy. All 270 live COUNT
requests passed raw validation. See [the report](docs/v010-energy-instrumentation.md).
The v1.0 measured-energy acceptance item remains open; instrumentation alone does not
complete it. Existing experiment files and default query behavior are preserved.

## v0.9: audit intervals and targeted timing recovery

The [roadmap to v1.0](docs/roadmap-to-v1.md) reconstructs the original milestones,
later gap-filling releases, and remaining energy/workload/report acceptance criteria.

`AuditedSession.refresh_timing(predicate)` is restricted to timing-drift quarantine.
It measures 32 component COUNTs on the retained sample, preserves gains/bounds and
training seeds, and requires an exact anchor before resuming approximate answers.
An accuracy fault still requires independent full recalibration; partial profiling
failures leave the quarantine and active profile intact. Exact-only plans stay probing.

```powershell
python scripts/compare_audit_v09.py --backend memory --epochs 2 --requests 40 --output results/local/new-audit-comparison
python scripts/compare_audit_v09.py --backend neo4j --epochs 3 --requests 60 --output results/local/new-live-comparison
python -m graph_mf --backend memory audit-benchmark --recovery-strategy timing_only --audit-every 5 --epochs 2 --requests 40 --output results/local/targeted-smoke
```

The matched comparison covers audit intervals 5/10/20 and full versus targeted timing
recovery. Block order is fixed; mode order within blocks is randomized. Only one fault
onset, predicate and tier are tested. Timing feedback is collected on the runtime sample;
it is not new independent accuracy calibration. See [v0.9 results](docs/v09-audit-optimization.md).

**Measured:** 4,320 live requests passed raw COUNT validation. Timing-only recovery
preparation averaged 382 ms versus 9,676 ms for full recovery (96.1% reduction).
Its complete stream cost was 88.33 ms/request versus exact at 35.47 ms; this does
not establish overall speedup. Interval comparisons test only a fault at request six.

## v0.8: audit, quarantine and independent recovery

`AuditedSession` wraps the cost-aware controller with an exact anchor on the first
approximate answer, the first approximate answer for each predicate, and every ten
approximate requests. An error-budget failure or three consecutive timing deviations
beyond a factor of three switches the detected request and later requests to exact.
Explicit `refresh` requires disjoint training/calibration/evaluation seeds on the same
static graph; the first new approximate answer must pass another exact anchor.
An exact-only refreshed plan remains in the probing state.

```powershell
python -m graph_mf --backend memory audit-benchmark --epochs 2 --requests 40 --output results/local/audit-smoke
python -m graph_mf --backend neo4j audit-benchmark --epochs 3 --requests 60 --output results/local/audit-live
```

The default experiment uses the retained v0.6 50k graph and profile, one predicate and
the performance tier. It corrupts correction coefficients or timing predictions;
it does not mutate graph data or create real server slowdowns. Sample builds, exact
anchors and independent recovery preparation are charged. Original startup/import
cost is excluded. The memory fallback is a functional check, not Neo4j timing evidence.

**Periodic checks have a blind window:** unaudited responses can violate the budget
before detection. This is not a per-response error guarantee or automatic graph-update
support. See [the v0.8 measured report](docs/v08-online-audit.md).

## v0.7: decide whether sample construction is worthwhile

The split controller now supports explicit `amortized` planning: predicted query cost
plus one shared sample build divided by a known reuse horizon. If exact is cheaper,
it executes exact COUNT without a low draft or sample construction. Approximate
streams materialize lazily and retain calibrated escalation and demotion hysteresis.
`cached` remains the default for compatibility with the v0.6 experiment.

NSGA-II adds optional duplicate elimination. A matched ablation compares unique
32/48-individual populations and search parameters on frozen v0.6 objectives.
No exhaustive oracle or unseen candidates are injected into the search population.
The 64-candidate space remains small; exhaustive runtime selection is still appropriate.

Python callers can use `CostAwareSession(backend, profile, build_ms=forecast,
reuse_requests=75)` and `session.request("FR", "performance")`. The session owns one
lazy sample and returns both COUNT steps, actual `build_ms` and complete `online_ms`.

```powershell
python scripts/compare_search_v07.py --output results/local/new-search
python -m graph_mf --backend memory cost-benchmark --epochs 2 --horizons 15 30 --output results/local/cost-smoke
# Uses the existing imported 50k synthetic dataset; set Neo4j credentials locally.
python -m graph_mf --backend neo4j cost-benchmark --epochs 3 --horizons 75 500 --output results/local/new-live-cost
```

See [the v0.7 Chinese report](docs/v07-cost-aware.md). These are known-horizon,
static-graph decisions; v0.8 adds profile-drift auditing. Energy measurement remains future work.

**Measured:** 5,175 live requests passed raw COUNT validation. For 75-request streams,
the cost-aware session skipped construction in all three runs (40.17 ms/request versus
137.99 ms for the previous controller including construction). For 500-request streams,
it measured 34.47 ms versus exact at 33.05 ms; stable speedup is not established.
The improved search configuration matched exhaustive choices on all four frozen v0.6
profiles; that is engineering validation on existing data, not independent generalization.

## v0.6: public topology, scale, memory and coupled policies

The new `deep-benchmark` compares exact COUNT, four fixed levels, exhaustive selection,
NSGA-II selection and the adaptive controller through the same component query interface.
Node and edge fidelity can differ: eight levels per component give 64 candidate pairs.
All approximate policies share frozen correction gains and uncertainty bounds; timing,
calibration and held-out sample seeds are disjoint. Runtime NSGA-II uses only the final
population of predeclared seed zero. Exhaustive search is a comparison oracle.
This comparison targets query latency with an already-built sample; the three search
objectives are component latency, node uncertainty and edge uncertainty. Build costs
are then charged explicitly in the standalone scenario. The v0.5 amortized planner
remains available. NSGA-II fitness uses the frozen timing table, not new live queries.

The public [SNAP Facebook graph](https://snap.stanford.edu/data/ego-Facebook.html) provides
real topology. Our degree-bucket COUNT predicates are custom; this is not an official
LDBC workload. Undirected input edges are stored once. The legacy `country` field holds
degree-bucket labels for this dataset. Synthetic cases use 50k, 100k and 200k nodes.

Process RSS is sampled separately for Python and an optional Neo4j server PID. These
are whole-process working-set measurements on Windows; the server retains earlier
datasets. Sampled maxima do not establish per-graph memory use or memory savings.

```powershell
python -m pip install -e ".[neo4j,experiments]"
python scripts/download_snap.py --output results/local/facebook_combined.txt.gz
python -m graph_mf --backend memory deep-benchmark --sizes 200 --epochs 2 --timing-epochs 2 --output results/local/deep-smoke
# Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD locally; never commit credentials.
python -m graph_mf --backend neo4j deep-benchmark --snap-path results/local/facebook_combined.txt.gz --sizes 50000 100000 200000 --server-pid YOUR_NEO4J_PROCESS_ID --output results/local/deep-live
```

Use a new output directory. Memory mode validates functionality, not Neo4j performance.
The full live suite builds and refreshes benchmark samples and imports datasets into
the configured database. Profiling/calibration/import/optimizer costs are recorded
separately. Query latency includes drafts, escalation, state checks and correction;
sample preparation is also allocated across the actual mixed stream when it uses a
sampled call (including a discarded draft). Exact-only policy streams need no build. Five held-out
seed epochs give preliminary within-run intervals, not broad performance guarantees.
Energy measurement, full LDBC workloads and online calibration remain future work.

See [the v0.6 measured report](docs/v06-deepening.md).
The [Chinese methods note](docs/v06-methods.md) explains the estimator, seeds,
64-pair search and accounting step by step.

**Measured on 2026-10-06:** 12,000 live requests across four graphs passed raw-count
validation. At 200k nodes, adaptive request latency was 107.44 ms versus 140.80 ms
for exact, but charging preparation over this short stream raised it to 265.68 ms.
No build-inclusive adaptive speedup was observed. All 40 tests passed including
the four opt-in live cases. Original v0.1 files remain unchanged.

Research question: can graph queries use a fraction of the data while keeping aggregate
answers within an accuracy tolerance?

v0.1 is the original NumPy proof of concept: synthetic graph, fixed fidelity levels,
and a heuristic adaptive node-count controller. **All original source, CSV results,
figures, README and technical note are preserved unchanged in `v0.1/`.**

v0.2 introduced an exact-query foundation for Neo4j/Cypher and a dependency-free memory
backend. It does not yet migrate the approximate controller into Neo4j. The tiny
dataset tests correctness and teaches graph concepts; it is not a performance workload.

**Live validation completed on 2026-10-03:** Neo4j 2026.09.0 Enterprise
in Desktop 2.2.1. All nine tests passed, including repeated seeding and exact COUNT
comparison against memory. See `results/neo4j/tiny-counts.json` and `docs/verification.md`.
No plugins were required. No Neo4j performance benchmark was measured.

v0.3 adds a matched synthetic workload with real Neo4j fixed-fidelity COUNT queries,
NumPy answer validation, repeated warm-cache latency measurements and explicit
sampling preparation costs. The original v0.1 controller remains available unchanged;
the controller has not yet been migrated into Neo4j.

**v0.3 measured on 2026-10-05:** 50,000 nodes, 149,996 edge records, 20 repeats.
At 10% fidelity, the median combined COUNT query time was 13.05 ms versus 45.76 ms
for exact COUNT. Charging fresh sample preparation raised the approximate request
to 1,806.75 ms. Query-only savings therefore do not establish an online speedup.
All sampled counts matched NumPy. See [the measured report](docs/v03-benchmark.md).

## v0.5 DLSS-inspired adaptive aggregate scaling

This implements the mechanism agreed with the project owner: a low-fidelity draft,
calibrated correction, uncertainty-based escalation and delayed demotion. It is a
graph COUNT research prototype inspired by the scaling analogy, not NVIDIA DLSS,
a neural reconstruction model, or a demonstrated novel algorithm.

| Tier | Node relative-error budget | Edge relative-error budget |
|---|---:|---:|
| performance / 性能 | 5% | 15% |
| balanced / 均衡 | 2% | 5% |
| quality / 质量 | 1% | 2% |
| exact / 精确 | 0% | 0% |

These are controller decision budgets on calibrated uncertainty, not guaranteed
per-query error limits. The controller chooses among **5/10/15/25/35/50/75/100%**
fidelity levels. A tier sets the error budget; it is not permanently tied to one level.

For each sampled COUNT: raw node estimate = count / f; raw edge estimate = count / f².
Fitting seeds learn multiplicative corrections. Separate calibration seeds set joint
residual bounds across all five countries, seven approximate levels and both metrics.
Each entire sample seed is one calibration unit, avoiding correlated-query pseudoreplication.
Held-out evaluation seeds never fit corrections, bounds or the latency profile.

The first approximate request executes and charges a low draft. Unsafe bounds or
too few sampled nodes/edges trigger higher-level queries; **every escalation call is
included in request latency**. Tighter budgets promote immediately; a cheaper/lower
level requires three consecutive relaxed requests. Country/sample-generation changes
reset history. Unknown countries or mismatched graph fingerprints use exact COUNT.
The persisted profile never stores exact answers for runtime reconstruction.

Two explicit planning policies:

- `amortized` (default): compare profiled request latency + mean build cost / expected
  reuse count. This can prefer exact COUNT even if an approximate query alone is faster.
- `cached`: compare request latency after the sample has already been built. This is a
  sunk-cost planning scenario; the benchmark still reports construction amortization.

Run new measurements (optional experiment dependencies required):

```sh
python -m graph_mf --backend neo4j adaptive-benchmark --output results/local/new-adaptive
python -m graph_mf --backend memory adaptive-benchmark --nodes 200 --epochs 2 --timing-epochs 2 --repeats-per-tier 3 --output results/local/adaptive-smoke
```

Run an actual query using the measured cached-sample profile and last measured sample:

```sh
python -m graph_mf --backend neo4j adaptive-query --profile results/neo4j/adaptive-long-reuse-50k-v05/profile.json --sample-seed 7001 --tier performance --cost-policy cached
python -m graph_mf --backend neo4j adaptive-query --profile results/neo4j/adaptive-long-reuse-50k-v05/profile.json --tier exact
```

If the sample has been refreshed, use its current seed or explicitly run `sample-build`
with the desired seed. Approximate queries do not implicitly rebuild samples. The exact
tier needs no sample. CLI processes start fresh controller history; use the Python
`AdaptiveController` instance for a stream that retains hysteresis.

Live results, scope and costs are in [the v0.5 measured report](docs/v05-adaptive.md).
The supported workload remains static synthetic graphs and five fixed country predicates;
calibration is not transferred to arbitrary predicates, graph sizes or changing graphs.
NSGA-II remains the separate v0.4 baseline; this controller is not implemented as NSGA-II.

## v0.4 Pareto and NSGA-II baseline

This release analyzes the existing v0.3.1 measurements offline. It minimizes three
objectives: modeled request cost, mean node error, and mean edge error. For each
fixed reuse scenario (1 / 10 / 100 / 1000 requests), exhaustive enumeration provides
the reference front; categorical NSGA-II searches the five recorded fidelity levels.
All 120 seeded final populations recovered the complete reference front in this run.
This small search space does not demonstrate an evolutionary search advantage.

```sh
python -m graph_mf optimize --output results/local/my-pareto-run
python -m graph_mf select-fidelity --reuse-requests 100 --node-tolerance 0.02 --edge-tolerance 0.05
```

Both commands use only the Python standard library, require no running Neo4j server,
and read `results/neo4j/reuse-50k-v031` by default. Use `--source` to analyze another
completed reuse run. Output folders must be new or empty. Error tolerances are fractions,
so `0.02` means 2%. Selection uses exhaustive candidates, rather than a possibly
incomplete evolutionary front. It does not issue a database query or build a sample.

**学习：什么是 Pareto 前沿？** 假设 A 比 B 更快，而且节点和边的误差都不更大，
至少一项严格更好，我们说 A「支配」B。没有被其他方案支配的方案组成 Pareto 前沿。
前沿通常包含多个取舍，并没有一个同时在所有方面最好的档位。

**NSGA-II 做什么？** 它把候选档位当作种群，按支配关系分层，再用拥挤距离保留
不同取舍；通过父代选择、交叉和变异产生新候选，并从父代和子代中择优保留。
这里仅有一个离散档位参数，交叉继承父母之一的档位，变异切换到另一个档位。
穷举结果只用于事后核对，没有传给算法作为答案。

**本次结果怎么读？** 复用 100 次时前沿为 10%、25%、100%；50% 和 75% 的模型成本
比完整查询更高，误差也更大，因此被支配。若节点平均误差允许 2%、边允许 5%，
选择 25%。要求节点 1%、边 2% 时，在这一复用情景下选择完整查询。
这些是同一批历史样本上的平均误差，不是未来每次查询的误差保证。

Cost uses recorded mean request time plus recorded mean build time divided by the
assumed reuse count. Only the 100-request scenario matches the measured reuse length;
other lengths are modeled extrapolations. No new Neo4j performance run was performed.
At v0.4 the adaptive method remained future work; v0.5 adds the agreed prototype.
Larger parameter-space evaluation remains future work. See [the v0.4 report](docs/v04-optimization.md) and
[the NSGA-II paper](https://doi.org/10.1109/4235.996017).

## v0.3.1 reusable samples

v0.3 rebuilt sample ranks between repetitions. v0.3.1 separates **sample construction**
from **read-only query requests**. Neo4j stores a ready-state record identifying the graph,
sample seed and generation. A later process can attach to the same sample without
rewriting ranks. Query timing includes a database readiness/generation check.

**v0.3.1 measured on 2026-10-05:** all 10,000 timed COUNT pairs matched NumPy.
At 10% fidelity, mean request cost including sample construction amortized over
100 requests was 35.94 ms versus 47.21 ms for exact COUNT (about 24% lower).
Mean node/edge relative errors were 2.07% / 7.46%. This result requires repeated
use of an unchanged sample on a static graph. See [the reuse report](docs/v031-reuse-benchmark.md).

With the synthetic graph already imported by the v0.3 benchmark:

```sh
python -m graph_mf --backend neo4j sample-build --sample-seed 1000
python -m graph_mf --backend neo4j sample-count --sample-seed 1000 --fidelity 0.1
python -m graph_mf --backend neo4j sample-count --sample-seed 1000 --fidelity 0.5
```

On the first use of a new graph, add `--import-graph` to `sample-build`. Importing resets
ranks and invalidates an old materialization; it is not part of a read-only query.
Repeating `sample-build` for a matching ready seed returns `reused: true` and does not
prepare ranks again. To create a fresh generation explicitly:

```sh
python -m graph_mf --backend neo4j sample-build --sample-seed 1001 --refresh
```

Changing the seed changes the sample. Refreshing with the same seed rebuilds the same
sample membership. Approximate `sample-count` never silently rebuilds missing/stale
samples. It fails if the published state is not ready or its generation changed.

Run the reuse experiment:

```sh
python -m graph_mf --backend neo4j reuse-benchmark --nodes 50000 --epochs 20 --requests 100 --output results/local/new-reuse-run
```

This measures 20 independent sample epochs × 100 requests × 5 fidelities = 10,000
COUNT pairs. Within each epoch, each sample is built once, then reused. Accuracy is
averaged across 20 independent samples, not across 2,000 repeated answers per fidelity.
Each fidelity stream is charged the full build cost divided by its 100 requests;
the benchmark does not discount that cost for sharing a sample across different levels.
Raw results and build costs are checkpointed after each epoch. Only metadata with
`status: completed` represents a completed run; existing output folders are preserved.

Offline reuse is available in one process:

```sh
python -m graph_mf --backend memory reuse-benchmark --nodes 200 --epochs 2 --requests 3 --warmups 1 --output results/local/reuse-smoke
```

Memory samples last only for that process. Standalone `sample-count` requires Neo4j
because its materialization persists between processes.

The supported workload is a static synthetic graph with one client and no concurrent
refresh/data mutation. Graph imports and direct rank preparations invalidate ready
state. Partial/failed sample builds do not become ready. Arbitrary manual edits outside
these APIs are not detected by the state check. Repeated use saves preparation cost,
but repeated answers retain the same sampling error; they are not new accuracy trials.
No TTL policy or adaptive controller is added in this release.

## v0.3 synthetic benchmark

Install the optional dependencies:

```sh
python -m pip install -e ".[neo4j,experiments]"
```

After configuring the same Neo4j environment variables described below:

```sh
python -m graph_mf --backend neo4j benchmark --nodes 50000 --repeats 20 --warmups 2 --output results/local/my-neo4j-run
```

Offline fallback (experiment dependencies required, no server or Neo4j driver required):

```sh
python -m graph_mf --backend memory benchmark --nodes 50000 --repeats 20 --warmups 2 --output results/local/my-memory-run
```

Use a new output folder for each run; existing measurements are not overwritten.
Outputs: raw CSV, summary CSV, metadata JSON and an accuracy/latency figure.
The committed Neo4j run is in `results/neo4j/synthetic-50k-v03/`.

### 这一阶段在研究什么？

先建立同一份 50,000 节点合成图，计算所有 `country='FR'` 的节点数量，以及
两端都满足这个条件的边数量。这两个完整答案是 ground truth。

然后给每个节点生成一个 `[0, 1)` 的随机数，保存在 `sample` 属性里。
10% fidelity 使用 `sample < 0.10` 的节点；25% 使用 `sample < 0.25`，依此类推。
同一轮的各档位使用同一组随机数，因此样本是嵌套的，和原 v0.1 的随机种子一致。

- 节点估计 = 采样后的目标节点数量 / fidelity。
- 边估计 = 两端均被采样的目标边数量 / fidelity²。
- 误差 = |估计值 − 完整答案| / 完整答案。

本项目会把每次 Neo4j 得到的原始计数与 NumPy 的同一份样本比较，任何不一致
都会终止实验。100% 档位使用完整查询，并在每轮重新计时。

准备样本需要生成随机数、写回数据库、维护索引。这些费用在 CSV 里单独列出；
`query_ms` 只计算准备完毕后的两条 COUNT，`with_preparation_ms` 给每个近似档位
计入完整的一次准备费用。不能只看查询加速就声称整个流程更快。

### Workload and timing contract

The generator produces exactly the v0.1 country and endpoint arrays for the same seed.
`MFNode` and `MF_EDGE` isolate this workload from the three-person exercise. The
dataset identifier incorporates a SHA-256 graph fingerprint. Each stored v0.1 edge
record becomes one directed relationship with a distinct `edge_id`; parallel endpoint
pairs remain separate and are counted once, matching v0.1 aggregate semantics.
No reverse edges are inserted. Schema constraints and batched MERGE allow serial
imports to be rerun without duplication. Import can be resumed after failure; unrelated
datasets are never cleared. Do not concurrently import or change sample properties
for the same dataset during a benchmark.

Composite indexes cover `(dataset, country)` and `(dataset, country, sample)`.
Each repeat materializes a fresh Bernoulli rank vector in batches of 2,000 nodes.
Import time is recorded separately. Warm-up precedes the timed workload, and each
repeat shuffles the five fidelity levels using recorded seeds. Timing uses client wall
time for two sequential COUNT requests via the same driver API, including transaction
and connection overhead; it is not server execution time alone. Both queries are
timed independently as well as summed. Index plans are saved with EXPLAIN.

Each preparation is reused across four approximate levels in the experiment, but its
full cost is charged to every approximate row for a single-level request comparison.
Do not sum those charged rows to infer total experiment wall time. Exact rows are
charged zero preparation because the exact query does not require sample properties.
Memory timing excludes server/network costs and is not directly comparable to Neo4j.
This is one warm-cache run on one host; no cold-cache, energy or memory claim follows.

## Run immediately, without Neo4j

From this repository's root, with Python 3.10 or later:

```sh
python -m graph_mf --backend memory smoke
python -m graph_mf --backend memory count node_count
python -m graph_mf --backend memory count edge_count
python -m graph_mf --backend memory count city_count --city Paris
python -m graph_mf --backend memory count age_count --min-age 24
python -m unittest discover -s tests -v
```

Expected counts: **3 people, 2 directed FRIEND relationships, 1 person in Paris,
2 people aged at least 24.** Memory is the default backend. It evaluates the same
fixed predicates in Python; it does not interpret arbitrary Cypher.
JSON output names the actual backend. An explicit `--backend neo4j` never silently
falls back to memory. `neo4j_measured: false` means no Neo4j **benchmark** has been
measured by this CLI; `neo4j_query_executed` separately identifies real query execution.

## 学习第一步：Node、Label、Property、Relationship

我们的练习图：

```text
Bowen (24, Paris) ──FRIEND──> Alice (22, Lyon)
        │
        └──────────FRIEND──> Bob (27, Lille)
```

| 词 | 意义 | 本项目的例子 |
|---|---|---|
| Node（节点） | 一个独立实体 | Bowen 这个人 |
| Label（标签） | 节点所属类别；一个节点可以有多个标签 | `:Person` |
| Property（属性） | 保存的键值数据；节点和关系都可以有属性 | `name: 'Bowen'`、`age: 24` |
| Relationship（关系） | 连接两个节点的有方向、带类型的边 | `(b)-[:FRIEND]->(a)` |

```cypher
(p:Person {name: 'Bowen', age: 24, city: 'Paris'})
```

`p` 是当前查询里的临时变量，不是保存的名字。`:Person` 是 Label，花括号里
是 Properties。`FRIEND` 是关系类型，不是节点 Label。关系有方向；这里用箭头
表示 Bowen 指向 Alice，不自动添加反向边。

### 第一次创建数据（在 Neo4j Browser 中）

在专门的学习数据库里运行以下两条语句，每条单独执行。
`MERGE` 查找匹配对象，没有时才创建；重复运行这个练习不会重复创建同一个人。
`dataset` 属性把本项目数据和其他人的练习隔开。

```cypher
CREATE CONSTRAINT graph_mf_person_identity IF NOT EXISTS
FOR (p:Person) REQUIRE (p.dataset, p.id) IS UNIQUE;
```

```cypher
MERGE (b:Person {dataset: 'graph-mf-tiny-v02', id: 'bowen'})
SET b.name = 'Bowen', b.age = 24, b.city = 'Paris'
MERGE (a:Person {dataset: 'graph-mf-tiny-v02', id: 'alice'})
SET a.name = 'Alice', a.age = 22, a.city = 'Lyon'
MERGE (c:Person {dataset: 'graph-mf-tiny-v02', id: 'bob'})
SET c.name = 'Bob', c.age = 27, c.city = 'Lille'
MERGE (b)-[:FRIEND]->(a)
MERGE (b)-[:FRIEND]->(c);
```

### 第一次查询

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN p;
```

`MATCH` 找到符合模式的节点，`RETURN` 返回结果。然后查看属性：

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN p.name AS name, p.age AS age, p.city AS city
ORDER BY name;
```

第一条 exact COUNT 查询（完整计数，不采样）：

```cypher
MATCH (p:Person {dataset: 'graph-mf-tiny-v02'})
RETURN count(p) AS count;
```

结果应为 `3`。下面数关系，结果应为 `2`：

```cypher
MATCH (:Person {dataset: 'graph-mf-tiny-v02'})-[r:FRIEND]->(:Person {dataset: 'graph-mf-tiny-v02'})
RETURN count(r) AS count;
```

查看 Bowen 指向的朋友：

```cypher
MATCH (b:Person {dataset: 'graph-mf-tiny-v02', id: 'bowen'})-[:FRIEND]->(friend:Person)
RETURN friend.name AS friend;
```

在 Desktop 的 **Query** 页面选择本地实例和 `neo4j` 数据库，运行下面这条，
切到图形结果即可看到三个人和两条关系：

```cypher
MATCH (a:Person {dataset: 'graph-mf-tiny-v02'})-[r:FRIEND]->(b:Person {dataset: 'graph-mf-tiny-v02'})
RETURN a, r, b;
```

你现在可以先理解这三件事：节点保存人，关系保存连接，COUNT 返回完整数据的
确切数量。后续近似查询才会与 exact COUNT 这个 ground truth 比较误差。

## Use a real Neo4j database

Use Neo4j Desktop or an existing Neo4j 5.26+ database. Install the optional official
Python driver:

```sh
python -m pip install -e ".[neo4j]"
```

PowerShell configuration (replace the password):

```powershell
$env:NEO4J_URI = "bolt://localhost:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "your-local-password"
$env:NEO4J_DATABASE = "neo4j"
python -m graph_mf --backend neo4j seed
python -m graph_mf --backend neo4j count node_count
python -m graph_mf --backend neo4j smoke
```

Linux/macOS: set the same variables using `export NAME=value`.
`.env.example` is a configuration template; the Python CLI reads environment variables
and does **not** automatically load `.env`.

If Docker is already installed, copy `.env.example` to `.env`, replace its password,
then run `docker compose up -d`. Compose reads `.env`; set the same password in your
shell for the Python CLI. Visit `http://localhost:7474` for Neo4j Browser. Ports bind
only to localhost. The volume retains the database; restarting a volume with a new
password does not reset existing database credentials. Stop with `docker compose down`.

The seed command creates a unique `(dataset, id)` constraint and loads three Person
nodes and two FRIEND edges in one data transaction. It sets only fixture properties,
does not clear the database, and can be rerun serially without duplication. Use a
dedicated learning database; extra nodes or edges carrying the same dataset marker
affect these counts. `smoke` reads existing Neo4j data and does not seed automatically.

To run the opt-in live test (it seeds the fixture twice):

```powershell
$env:RUN_NEO4J_TESTS = "1"
python -m unittest discover -s tests -v
```

Without this opt-in, live tests are skipped. Adapter mock tests verify Python calls,
parameter handling and transaction structure; they do not validate Cypher on a server.

## Preserve and reproduce v0.1

The original files are under `v0.1/`, including `results/`, `figures/`, and
`report/technical_note.md`. `docs/v01-preservation.json` records original file hashes.
Compiled `__pycache__` files from the archive are ignored by Git.

Install its original dependencies with `python -m pip install -r v0.1/requirements.txt`.
To reproduce its 50,000-node experiment **without overwriting archived results**,
copy `v0.1/` outside the preserved folder first:

```powershell
New-Item -ItemType Directory -Path results/local -Force | Out-Null
Copy-Item -LiteralPath v0.1 -Destination results/local/v01-rerun -Recurse
python results/local/v01-rerun/run_experiment.py
```

On Linux/macOS, use `mkdir -p results/local`
and `cp -R v0.1 results/local/v01-rerun` before running the copied script.
New timings depend on the machine; they are Python/NumPy measurements.

## Structure and research limits

```text
graph_mf/data/tiny.json        shared fixture
graph_mf/cypher/               parameterized schema, seed and exact queries
graph_mf/backends.py           common backend contract and implementations
graph_mf/__main__.py           seed / count / smoke CLI
tests/                        offline, adapter, legacy and opt-in live tests
v0.1/                         unchanged original experiments and outputs
docs/                         provenance and verification record
```

v0.1 models stored edge pairs as undirected and can generate duplicate endpoint pairs.
The v0.2 learning fixture uses directed FRIEND relationships. They are separate workloads;
their counts and execution times should not be compared as a migration benchmark.
The v0.1 full-fidelity experiment reuses one exact-query timing across repeats. Its
controller estimates uncertainty, which is not a guarantee of actual relative error,
especially for rare predicates or repeated adaptive decisions.

The v0.3 results provide a first measured Neo4j fixed-fidelity baseline. They establish
neither a general latency improvement nor memory/energy savings. v0.4 implements an
NSGA-II baseline over recorded levels. v0.5 implements calibrated adaptive scaling
and evaluates new sample seeds, without claiming algorithmic novelty. Next milestones:
new graph/workload distributions, a broader NSGA-II parameter space, and mutation-aware
sample freshness with separately measured recalibration costs.

Official references: [Neo4j Python driver](https://neo4j.com/docs/python-manual/current/),
[Cypher MERGE](https://neo4j.com/docs/cypher-manual/current/clauses/merge/).
