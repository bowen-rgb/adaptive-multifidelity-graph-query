# Neo4j fixed-fidelity baseline — v0.3

Measured on 2026-10-05 on the user's local Neo4j instance.
All 100 timed query pairs (20 repeats × 5 fidelities) returned the same raw node and
edge counts as NumPy for the identical sampled graph. Error columns also reproduced
the preserved v0.1 experiment within 1e-12 tolerance. All ten v0.1 file hashes still match.

## Observed results

| Fidelity | Node error | Edge error | Query median (ms) | Including preparation (ms) |
|---:|---:|---:|---:|---:|
| 10% | 2.07% | 7.46% | 13.05 | 1806.75 |
| 25% | 1.76% | 4.08% | 18.90 | 1811.21 |
| 50% | 0.81% | 1.36% | 29.20 | 1827.50 |
| 75% | 0.42% | 0.98% | 37.64 | 1836.96 |
| 100% | 0.00% | 0.00% | 45.76 | 45.76 |

These are mean errors across 20 sample seeds and median client wall times. Query time
is the sum of two sequential COUNT requests, including driver/transaction overhead.
Approximate rows use pre-materialized samples. The last column charges the complete
sample preparation cost to a single-level request; it is not a total across all levels.

The exact query median was 45.76 ms. At 10% fidelity, the query-only median was
13.05 ms, while preparation plus queries took
1806.75 ms. Query-only comparisons do not
establish that an online approximate request is faster. This sample-property rewrite
is a correctness baseline; online preparation cost needs further work.

## Environment and method

- 50,000 nodes, 149,996 stored edge records;
  graph seed 42, requested mean degree 6. Exact FR counts: 14,959 nodes / 13,428 edges.
- Neo4j 2026.09.0 Enterprise, driver 6.3.1; Python 3.12.14,
  NumPy 2.5.3; Windows, Intel Core i9-13950HX (24 cores / 32 logical processors),
  approximately 32 GiB installed RAM.
- Page cache 512.00MiB;
  maximum Java heap 1.00GiB.
- Two warm-ups per fidelity; no cache flush; serial client; shuffled fidelity order
  per repeat. Uniform node ranks use seeds 1000–1019, with nested levels within a repeat.
- Each v0.1 edge record is stored once with an edge identity, retaining parallel
  endpoint pairs. Dataset fingerprint isolates the workload from the tiny learning graph.
- Sample generation, batched property writes and index maintenance are included in
  preparation time. Initial import/connection time is excluded from query measurements
  and recorded separately in metadata. No cold-cache, energy or memory benchmark.

## Query-plan correction

An initial diagnostic run was stopped before completion on 2026-10-03. Its sampled
edge query used MultiNodeIndexSeek followed by Expand(Into), forming candidate endpoint
pairs. Those partial timings were not used in the results above. The corrected query
seeks sampled source nodes and uses Expand(All) to traverse existing edges, then filters
target properties. The target label is omitted because all imported dataset edges have
MFNode endpoints; final counts are checked against the original graph for every sample.
EXPLAIN plans for the completed run are saved in metadata. These are plan diagnostics,
not measured DB-hit or I/O statistics.

## Verification and remaining work

- 14 local tests passed, including real Neo4j idempotence, duplicate edge preservation
  and sampled-count equivalence. The memory benchmark smoke also completed successfully.
- Editable installation and wheel packaging succeeded; packaged JSON and Cypher
  resources loaded correctly, and the tiny memory smoke passed without third-party
  packages. Dependency consistency check passed.
- All original v0.1 code, results and figures remain unchanged.
- The adaptive v0.1 controller remains a separate heuristic. It is not yet connected
  to this database workload. No NSGA-II, energy optimization or novel algorithm claim.
- One host and one completed run: timings are local observations, not general speedup
  guarantees. The next research step is a lower-cost sample strategy and adaptive
  selection evaluated against this exact/fixed-fidelity baseline.

## Reproduce

From the repository root after configuring the Neo4j environment variables:

```sh
python -m pip install -e ".[neo4j,experiments]"
python -m graph_mf --backend neo4j benchmark --nodes 50000 --repeats 20 --warmups 2 --output results/local/new-run
```

The output folder must be new or empty. Raw data, summary, metadata and figure are
under `results/neo4j/synthetic-50k-v03/` for the measured run.
