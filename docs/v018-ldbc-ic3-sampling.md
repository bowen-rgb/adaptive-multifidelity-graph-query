# v0.18 — IC3 message-sampling feasibility

Read-only runs on a quiescent SF0.1 database after prior reference updates,
not a fresh initial snapshot or a complete mixed workload. The official query
is pinned upstream; the candidate retains exact Person/KNOWS candidates and
Bernoulli-samples Message IDs. Counts scale by 1/f. Full-tier ordered tuples
are checked against the upstream query before accepting each measured block.

## Results

| Parameters | Mode | vs upstream | vs population exact (95% paired block bootstrap) | Nonempty quality passes | Mean recall | Worst count error |
|---|---|---:|---:|---:|---:|---:|
| official substitutions | fixed_10 | 2.95 | 3.69 [1.00, 5.23] | 0/0 | n/a | n/a |
| official substitutions | fixed_25 | 1.52 | 1.90 [1.08, 2.58] | 0/0 | n/a | n/a |
| official substitutions | fixed_50 | 1.05 | 1.31 [1.01, 2.60] | 0/0 | n/a | n/a |
| official substitutions | fixed_75 | 3.01 | 3.75 [0.89, 4.57] | 0/0 | n/a | n/a |
| official substitutions | population_exact | 0.80 | 1.00 [1.00, 1.00] | 0/0 | n/a | n/a |
| official substitutions | reference | 1.00 | 1.25 [0.14, 3.44] | 0/0 | n/a | n/a |
| custom wide-window stress | fixed_10 | 0.04 | 1.14 [1.08, 1.18] | 0/24 | 0.000 | 100.0% |
| custom wide-window stress | fixed_25 | 0.04 | 1.18 [1.13, 1.21] | 0/24 | 0.000 | 100.0% |
| custom wide-window stress | fixed_50 | 0.04 | 1.13 [1.10, 1.16] | 0/24 | 0.188 | 100.0% |
| custom wide-window stress | fixed_75 | 0.04 | 1.10 [1.06, 1.15] | 0/24 | 0.854 | 100.0% |
| custom wide-window stress | population_exact | 0.03 | 1.00 [1.00, 1.00] | 24/24 | 1.000 | 0.0% |
| custom wide-window stress | reference | 1.00 | 29.27 [20.28, 39.04] | 24/24 | 1.000 | 0.0% |

## Interpretation and limits

The first eight randomly selected official substitutions return empty exact
answers. Empty/empty agreement is reported but does not validate preservation
of nonempty rankings. That initial run also contains candidate compilation cost.
The stress trial uses the same roots, the globally most frequent two message
countries and the full observed date range, without selecting on root answers.
Those custom parameters are not official substitution or certification results.
Stress exact result sizes: [1, 2, 1, 1, 1, 1, 1, 1];
13 of 18 per-country counts are one. At fidelity
0.75 an observed single message scales to 1.333, already outside a 20% budget
for a true count of one. This is a sparse-count quantization limit, not a
reason to silently relax the target or hide missing people.

Before either run, the fixed quality target is recall >= 0.9 and maximum
relative x/y/combined count error <= 0.2. Missing exact top-20 people count
as 100% errors, rather than being removed from accuracy statistics. Recall
alone is insufficient; ranking displacement and false people are retained
in raw CSV and ordered answer records. Three blocks reuse eight parameters;
they are not 24 independent query parameters. Bootstrap is descriptive.

Every candidate request freshly fetches eligible message IDs, transfers them,
samples in Python and executes Cypher. All those costs are included online.
Warmup and stress parameter preparation are separately recorded; import,
test-oracle calls and driver initialization are excluded. The exact population
candidate is necessary to separate a query-plan improvement from sampling.
No answer cache, graph mutation, fitted quality model or adaptive gate is used.
Equal before/after node/edge counts do not detect every possible external edit.

This is a feasibility pilot. It does not establish full LDBC adaptive gains.
All sampled stress requests fail the predeclared tuple-quality target, and
this ID-fetch implementation is slower than the upstream exact query. It
must not be enabled in the mixed driver. Screening denser aggregate query
families is preferable to calibrating this sparse workload into universal fallback.
A tier that is quicker but fails tuple quality cannot be accepted just because
its COUNT estimate looked confident. Next work requires independent quality
calibration and conservative exact fallback before the mixed-workload adapter.

## Reproduction

```powershell
$env:NEO4J_DATABASE="your-quiescent-full-snb-database"
# Supply credentials through environment configuration.
python scripts/benchmark_ldbc_ic3_sampling.py --reference PATH_TO_PINNED_IMPL --parameters PATH_TO_PARAMS --output results/local/ic3-official
python scripts/benchmark_ldbc_ic3_sampling.py --reference PATH_TO_PINNED_IMPL --parameters PATH_TO_PARAMS --stress-wide-window --output results/local/ic3-stress
python scripts/report_ldbc_ic3_sampling.py --official results/neo4j/ldbc-ic3-sampling-v018 --stress results/neo4j/ldbc-ic3-stress-v018
```

Source: [pinned upstream IC3](https://github.com/ldbc/ldbc_snb_interactive_v1_impls/blob/11db98cc2ba14c33492f6c0c34e68c8be7e22e5f/cypher/queries/interactive-complex-3.cypher).
