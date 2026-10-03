# Technical Note — MVP v0.1

## Objective
This proof-of-concept tests whether reducing graph fidelity can trade a controlled loss of
query accuracy for lower execution cost.

## Method
A synthetic graph with node property `country` and undirected edges is generated.
The full graph provides exact answers. Approximate queries use uniform node sampling at
multiple fidelity levels. A node-count query is scaled by `1/f`, while an edge-count query
is scaled by `1/f^2`.

## Adaptive controller
A simple controller starts from low fidelity and increases the sample size until the
estimated 95% confidence interval is compatible with a requested relative uncertainty.
This is a baseline heuristic and is not presented as a novel method.

## Interpretation
The experiment is intended to validate the research workflow:
problem formulation -> exact baseline -> approximation -> measurable error -> adaptive
selection. It is deliberately smaller than the planned Neo4j/LDBC study.

## Limitations
The graph is synthetic; execution is in memory rather than in a graph DBMS; latency is
Python execution time; no energy measurement is included. Therefore the results must not
be presented as evidence about Neo4j or production graph databases.

## Planned extension
Neo4j + Cypher + LDBC SNB, followed by NSGA-II and a stronger adaptive multi-fidelity
controller.
