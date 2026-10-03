# Changelog

## 0.2.0 — 2026-10-03

- Follow-up: validate real Neo4j 2026.09.0 exact queries and idempotent seeding;
  all 9 tests pass locally, and commit the credential-free query results.
- Preserve original v0.1 code, results and figures unchanged under `v0.1/`.
- Add a shared three-person fixture and parameterized Cypher schema, seed and COUNT queries.
- Add exact-query backend contract, optional Neo4j driver and dependency-free memory fallback.
- Add Chinese learning walkthrough, configuration template and optional Docker Compose setup.
- Add correctness checks, v0.1 regression checks and opt-in live Neo4j integration test.
- No Neo4j performance result or database approximate-query controller is claimed.
