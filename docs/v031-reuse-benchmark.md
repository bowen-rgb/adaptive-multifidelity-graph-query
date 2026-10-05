# Reusable sample baseline — v0.3.1

Measured 2026-10-05 on the same 50,000-node / 149,996-edge Neo4j
workload. All **10,000 timed COUNT pairs** matched NumPy. Twenty independent sample
seeds were each reused for 100 requests at each fidelity. Errors across independent
epochs reproduced v0.1 within 1e-12 numerical tolerance. All archived file hashes match.

## Results

| Fidelity | Node / edge mean error | Reused request mean (ms) | Including build amortized over 100 requests (ms) |
|---:|---:|---:|---:|
| 10% | 2.07% / 7.46% | 12.15 | 35.94 |
| 25% | 1.76% / 4.08% | 19.32 | 43.11 |
| 50% | 0.81% / 1.36% | 30.98 | 54.76 |
| 75% | 0.42% / 0.98% | 42.85 | 66.64 |
| 100% | 0.00% / 0.00% | 47.21 | 47.21 |

Request time includes a ready-state/generation check and two sequential COUNT queries.
Connection setup, graph generation/import and CLI startup are excluded. The last column
is measured aggregate request time plus the complete measured build costs, divided by
the 2,000 requests for each fidelity. Each approximate fidelity stream is charged its
own full build cost; the result does not assume sharing the build across different levels.
Exact requests are charged no sample cost because exact COUNT does not need a sample.

First build: **2403.86 ms**. Subsequent refresh mean:
**2377.54 ms**. The ten-percent request mean after construction
was **12.15 ms**, compared with **47.21 ms** for exact COUNT
in the same run. At 100 requests per sample, ten-percent cost including amortized
construction was **35.94 ms/request**.
The modeled break-even request count for ten-percent fidelity was
**68**, computed from mean build cost divided by
mean query savings. This is a cost-model estimate, not an independently measured
threshold. A single approximate request still pays the complete build when no sample exists.

v0.3 measured about 1.81 seconds for a ten-percent request when charging a new sample
every time. v0.3.1 explicitly reuses an unchanged sample. Cross-version timings are
different runs; the meaningful performance comparison above uses contemporaneous exact
and approximate requests within v0.3.1. These observations apply to repeated requests
on a static graph and are not a general online speedup claim.

## Correctness and lifecycle

- A Neo4j MFMaterialization node stores graph fingerprint, seed, algorithm, generation
  and readiness. Sample requests never implicitly construct or refresh it.
- Batched writes publish ready only after all ranks are written. Interrupted or failed
  builds remain unusable; graph import and direct rank writes invalidate previous state.
- Later client processes can attach to a ready sample. The persisted smoke test attached
  in a separate CLI process with `reused=true`, no rank preparation, and returned correct
  counts from another process. See `persistent-smoke.json`.
- Twenty local tests passed, including failed partial rank writes, recovery, reimport
  invalidation, refresh detection, and persistence across connections. Offline fallback
  completed a repeated-request smoke test.
- The graph must remain static. Arbitrary external data edits and concurrent refreshes
  are not supported/detected as a complete mutation protocol. One active sample per graph.
- Repeated answers have the same sampling error. Reusing a sample does not produce
  2,000 independent accuracy trials; error statistics use 20 independent sample epochs.

## Measurement scope

Neo4j 2026.09.0 Enterprise on the same local Windows machine as v0.3. Warm cache, no
cache flush, one serial client, shuffled fidelity order per request round. Raw results,
per-sample build costs and environment information are in this run's result folder.
Each request is a pair of aggregate queries; it is not a single Cypher statement.
No energy, server memory, cold-cache or changing-graph benchmark was performed.
Latency samples may be correlated within a sample epoch and reflect one local run.

## Reproduce

```sh
python -m graph_mf --backend neo4j reuse-benchmark --nodes 50000 --epochs 20 --requests 100 --output results/local/new-reuse-run
```

To reuse the measured last sample (seed 1019) in a new process:

```sh
python -m graph_mf --backend neo4j sample-build --sample-seed 1019
python -m graph_mf --backend neo4j sample-count --sample-seed 1019 --fidelity 0.1
```

## Next milestone

This release supplies a lower-cost repeated-query baseline. NSGA-II and the proposed
DLSS-style adaptive graph scaling method are not implemented yet. Before NSGA-II,
use an exhaustive Pareto baseline for the five current fidelity levels; expand the
parameter space and compare multi-objective choices against measured error and request
cost, explicitly accounting for how often samples are refreshed.
