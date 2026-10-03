# Verification — 2026-10-03

Environment: Windows, Python 3.12; isolated local virtual environment.
Installed versions: NumPy 2.5.3, pandas 3.0.6, matplotlib 3.11.2, Neo4j driver 6.3.1.

## Live Neo4j follow-up

After the initial offline check, the user installed Neo4j Desktop 2.2.1 and started
a local instance. The server reported **Neo4j Kernel 2026.09.0, enterprise edition**.
Connection and schema/data writes succeeded using the official Python driver.

- `python -m graph_mf --backend neo4j seed`: succeeded.
- `python -m graph_mf --backend neo4j smoke`: passed (3 nodes, 2 directed FRIEND edges,
  1 person in Paris, 2 people aged >=24).
- With `RUN_NEO4J_TESTS=1`, the complete test suite reported **9 passed, 0 skipped**.
  The live test seeds the same fixture twice and compares exact answers with memory.
- A nonexistent city also returned zero, matching memory.
- Returned nodes and relationships confirmed Bowen -> Alice and Bowen -> Bob.
- Machine-readable server metadata and query results are in
  `results/neo4j/tiny-counts.json`. No credentials are recorded or committed.
- No APOC, GDS, Bloom or GenAI plugin was needed.

## Initial offline checks

- `python -S -m graph_mf --backend memory smoke`: passed without third-party packages.
- `python -m unittest discover -s tests -v`: **8 passed, 1 skipped**.
  Six offline/adapter tests, two v0.1 regression tests; live Neo4j test skipped.
- Memory smoke: node count 3, directed edge count 2, Paris count 1, age >=24 count 2.
- Editable installation with the Neo4j extra and original v0.1 requirements: passed.
- `python -m pip check`: no broken requirements.
- Original 50,000-node v0.1 experiment executed from a scratch copy, preserving
  the archived results and figures.
- All non-timing columns in the three regenerated CSVs reproduced the original
  values within numerical tolerance (`rtol=atol=1e-12`). Exact counts: 14,959 FR
  nodes and 13,428 stored edge pairs with both endpoints in FR.
- All ten archived deliverable files matched the SHA-256 hashes of their originals
  after these checks. See `v01-preservation.json`.

## Measurement limits

A Neo4j server was unavailable during the initial checks; that gap is now resolved by
the live validation above. No Neo4j query latency, memory, energy or fidelity benchmark
was measured. Mock adapter tests check Python request structure only; the separate
live test now validates these Cypher statements on the installed server. GitHub's
offline CI still skips the opt-in live test because it has no local database configured.

## Interpretation

The original adaptive controller's 1% target selected 75% fidelity but yielded about
1.10% actual relative error on this seed. Estimated uncertainty is a selection heuristic,
not an accuracy guarantee. Original timings have a single exact-query measurement reused
at full fidelity; rerun timings differed on this host. Neither run establishes a Neo4j
performance improvement.
