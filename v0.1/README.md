# Adaptive Multi-Fidelity Query Processing for Graph Data — MVP v0.1

This repository is a **proof-of-concept continuation** of an earlier academic study on
multi-objective optimisation of graph databases under performance–energy trade-offs.

## Research question

Can a graph query process only a fraction of the graph while keeping the answer within a
user-defined accuracy tolerance?

The MVP studies three ideas:

1. **Exact query** on the full graph as ground truth.
2. **Fixed-fidelity approximate queries** at 10%, 25%, 50%, 75%, and 100%.
3. A first **Adaptive Fidelity Controller** that progressively increases the sampled
   fraction until an uncertainty target is reached.

## Current scope

- Synthetic graph data generated in Python/NumPy.
- Aggregate node-count and structural edge-count queries.
- Uniform node sampling with simple unbiased scaling estimators.
- Accuracy and execution latency measurements.
- Reproducible CSV results and figures.

## What this MVP does NOT claim

- It does **not** yet benchmark Neo4j or another production graph DB.
- It does **not** yet measure energy consumption.
- It does **not** yet implement NSGA-II.
- The adaptive controller is a proof-of-concept heuristic, **not a claimed novel algorithm**.

These are planned next milestones.

## Run

```bash
pip install -r requirements.txt
python run_experiment.py
```

Outputs are written to `results/` and `figures/`.

## Next milestones

- M1: move the workload to Neo4j and Cypher.
- M2: replace the synthetic workload with LDBC SNB queries.
- M3: add memory and energy instrumentation.
- M4: implement NSGA-II as a multi-objective baseline.
- M5: design and evaluate a stronger adaptive controller against the baselines.
