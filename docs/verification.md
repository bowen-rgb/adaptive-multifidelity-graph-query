# Verification — 2026-10-03

Environment: Windows, Python 3.12; isolated local virtual environment.
Installed versions: NumPy 2.5.3, pandas 3.0.6, matplotlib 3.11.2, Neo4j driver 6.3.1.

## Completed

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

## Not executed

A Neo4j server and Docker were unavailable in this environment. Installing the driver
does not install a database server. No live Cypher execution, Neo4j query latency,
memory, energy or fidelity benchmark was measured. Mock adapter tests check Python
request structure only. The opt-in integration test remains available for a real
server and checks two serial seed runs against the memory backend.

## Interpretation

The original adaptive controller's 1% target selected 75% fidelity but yielded about
1.10% actual relative error on this seed. Estimated uncertainty is a selection heuristic,
not an accuracy guarantee. Original timings have a single exact-query measurement reused
at full fidelity; rerun timings differed on this host. Neither run establishes a Neo4j
performance improvement.
