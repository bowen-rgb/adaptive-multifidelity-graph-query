# Adaptive Graph Query Optimization

A Python/Neo4j research prototype for trading aggregate-query precision for lower
computation cost. The focus is COUNT queries on static graphs, with explicit error
budgets and separately measured preparation cost. Developed with AI assistance.

## Problem and approach

Exact graph queries can repeatedly scan nodes and relationships. If an application
accepts approximate aggregate answers, a smaller reusable sample may reduce that work.
The challenge is choosing a sample large enough for the requested precision while
avoiding repeated probes and recovering the cost of preparation.

The prototype assigns each node a reproducible uniform rank. At fidelity f it selects
nodes with rank < f. Node COUNT estimates scale by 1/f; edges with both endpoints
selected scale by 1/f². Calibration checks the actual errors rather than assuming
that these estimators are precise on every realization. General multi-hop queries
do not inherit this simple scaling rule.

Fitting seeds define residual scales; separate calibration seeds provide a joint
maximum over known countries, COUNT kinds and tiers. At runtime the controller
starts from a calibrated tier, checks current sample size and escalates when needed.
Unknown predicates use exact queries. Current requests never receive the exact
answer as a selection input; benchmark oracle checks run afterward.

## Evidence an interviewer can inspect

| Result | Experiment | Interpretation |
|---|---|---|
| 1.34× recorded phase-cost improvement | 50k-node static graph, 6,000 request pairs, 20% budget | Exact 303.14 s vs joint 226.15 s, including recorded training/builds/session/query cost |
| 0/12,000 observed budget violations; max error 11.26% | Same long stream, three new rank epochs | Amortization test; repeated requests are correlated |
| 0/2,400 observed violations per size | 100 fresh sampling epochs at each of 50k/100k nodes | Independent accuracy check; most answers still use samples |
| 138,474 reference operations validated, 29 types | Official SNB Interactive v1 reference sequence on SF0.1 | Engineering/semantic validation, separate from approximate COUNT research |

The long-stream phase sum excludes graph import, profile reading and test-oracle
checking; training was measured previously. The original training workflow includes
its own validation. These are recorded phases, not one continuous lifecycle wall clock.
Strict 5% budgets and short streams did not show useful overall savings. Empirical
bounds and zero observed violations are not production guarantees.

## Deliverables and reproduction

- [Executable demo](../scripts/demo_joint_sampling.py): fit, calibrate and query a synthetic graph without Neo4j; `--nodes 2000` selects a smaller smoke fixture.
- [Controller](../graph_mf/incremental_sampling.py) and [calibration](../graph_mf/sample_correction.py).
- [Measured report](v017-joint-calibration.md), [raw long-stream records](../results/neo4j/joint-long-50k-v017) and [figure](figures/v017-evidence.png).
- [Full SNB runbook](ldbc-full-runbook.md), [tests](../tests) and [CI workflow](../.github/workflows/checks.yml).

From the repository root:

```sh
python -m pip install -e ".[experiments]"
python -m graph_mf --backend memory smoke
python scripts/demo_joint_sampling.py
python -m unittest discover -s tests -v
```

The demo is a functional illustration, not a performance replication. Full measured
replication requires Neo4j, the recorded graph/profile preparation and the commands
in the report. Data import and training cost must remain visible.

## Research status

Established here: functioning graph-query pipeline, conditional measured savings,
independent calibration/accuracy tests and official-reference semantic validation.
Open: unseen topology, nonrepeating parameters, concurrent graph updates, full SNB
adaptive acceleration, real energy measurements and algorithmic novelty. NSGA-II,
random and surrogate search comparisons are retained without a superiority claim.
