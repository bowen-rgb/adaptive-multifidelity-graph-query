# Changelog

## 0.4.0 — 2026-10-06

- Add exhaustive three-objective Pareto baselines over recorded fidelity levels.
- Add categorical NSGA-II with rank/crowding tournaments and elitist selection.
- Compare final populations and diagnostic discovery against exhaustive fronts across seeds.
- Model sample reuse as fixed scenarios; keep original Neo4j measurements unchanged.
- Add offline empirical mean-error budget selection, provenance and reproducible reports.
- No new database timing, expanded-space search advantage or adaptive scaling claim.

## 0.3.1 — 2026-10-05

- Separate reusable sample construction from read-only COUNT requests.
- Persist graph/sample identity, readiness and generation in Neo4j for later processes.
- Invalidate samples on import/rank overwrite; reject interrupted or refreshed state.
- Add explicit build/refresh/query commands and repeated-request amortization benchmark.
- Record independent sample epochs separately from repeated accuracy answers.
- Checkpoint raw measurements after each completed epoch.

## 0.3.0 — 2026-10-05

- Migrate the matched v0.1 synthetic graph and fixed-fidelity COUNT workload into Neo4j.
- Preserve duplicate edge records with edge identities and idempotent batched imports.
- Add 10/25/50/75/100% Bernoulli node sampling and exact NumPy answer validation.
- Measure repeated warm-cache queries separately from sample preparation and import.
- Export raw/summary CSV, environment and query-plan metadata, and tradeoff figure.
- Keep the tiny dependency-free fallback and all original v0.1 files.

## 0.2.0 — 2026-10-03

- Follow-up: validate real Neo4j 2026.09.0 exact queries and idempotent seeding;
  all 9 tests pass locally, and commit the credential-free query results.
- Preserve original v0.1 code, results and figures unchanged under `v0.1/`.
- Add a shared three-person fixture and parameterized Cypher schema, seed and COUNT queries.
- Add exact-query backend contract, optional Neo4j driver and dependency-free memory fallback.
- Add Chinese learning walkthrough, configuration template and optional Docker Compose setup.
- Add correctness checks, v0.1 regression checks and opt-in live Neo4j integration test.
- No Neo4j performance result or database approximate-query controller is claimed.
