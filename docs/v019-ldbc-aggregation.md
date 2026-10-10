# v0.19 — Dense aggregation and remaining validation

The full adaptive SNB benefit is still unproven. This release screens official
IC5/IC6/IC12 density, tests IC5 physical post sampling on fresh root holdouts,
and records negative quality results rather than enabling a failed mixed adapter.

## Official aggregate screening

| Query | Unique substitutions | Nonempty results | Median top count | Positive groups with count 1 |
|---|---:|---:|---:|---:|
| IC5 | 15 | 13 | 0 | 131/177 |
| IC6 | 15 | 15 | 1 | 559/578 |
| IC12 | 15 | 14 | 1 | 14/21 |

The screen uses the prior updated SF0.1 snapshot, not the new initial IC5
experiment database. All exact top tuples match the pinned upstream query.
Each supplied substitution file contains 15 usable unique rows; failed
24-row requests are retained as failed metadata, not measured experiments.
Custom IC5 minDate=-1 increases the median top count to 19 (maximum 61),
but these are custom wide-window parameters, not official substitutions.

## Fresh-root IC5 calibration and confirmation

Fit: 5 roots / 4 rank seeds. Calibration: 5 disjoint roots / 20 rank seeds.
Test: 10 new roots / 6 new rank seeds. Approximate tiers 25/50/75/90% all
fail the calibration target: top-20 recall >= 90% and maximum count error
<= 20%. Missing true forums count as errors. Forum IDs distinguish equal titles.
A missing positive-count forum incurs 100% error under this contract; hence
the maximum-count criterion effectively requires retaining all positive true
top-20 forums, even though the separate recall threshold is 90%. A contract
that permits missing items would be different and needs a new preregistered
calibration/holdout experiment; these results do not rule out every estimator.
The empirical seed-max calibration is not a formal new-root confidence bound.
The profile is frozen for independent confirmation; no test oracle chooses a tier.

| Run | Policy | Quality passes | Approximate requests | Upstream online ratio (95% seed bootstrap) | Ratio charging test view bundle |
|---|---|---:|---:|---:|---:|
| concurrent pilot | adaptive | 60/60 | 0 | 1.031 [0.985, 1.077] | 0.039 |
| concurrent pilot | exact | 60/60 | 0 | 1.034 [1.008, 1.066] | 1.034 |
| concurrent pilot | fixed_75 | 12/60 | 60 | 1.040 [1.011, 1.078] | 0.039 |
| concurrent pilot | fixed_90 | 25/60 | 60 | 1.006 [0.956, 1.061] | 0.039 |
| concurrent pilot | reference | 60/60 | 0 | 1.000 [1.000, 1.000] | 1.000 |
| isolated confirmation | adaptive | 60/60 | 0 | 0.899 [0.741, 1.112] | 0.032 |
| isolated confirmation | exact | 60/60 | 0 | 0.789 [0.688, 0.875] | 0.789 |
| isolated confirmation | fixed_75 | 7/60 | 60 | 0.943 [0.808, 1.083] | 0.032 |
| isolated confirmation | fixed_90 | 25/60 | 60 | 0.855 [0.709, 1.022] | 0.032 |
| isolated confirmation | reference_augmented | 60/60 | 0 | 0.847 [0.777, 0.920] | 0.847 |
| isolated confirmation | reference_pristine | 60/60 | 0 | 1.000 [1.000, 1.000] | 1.000 |

Pilot timings overlapped full reference replay and dataset preparation; they
are not isolated performance claims. Confirmation runs after that work ends,
against an additional pristine initial database with no sample relationships.
The augmented upstream baseline is also recorded to expose storage/plan effects.
Each block reuses ten roots; sixty records are not sixty independent parameters.
Oracle checks warm these roots and query plans before timing; this is a
warm-cache holdout comparison, not cold first-use parameter latency.
Bootstrap uses six entire seed blocks and is descriptive on one machine.
All four physical views are charged as actually built, including discarded probes.
Training/preparation in the pilot takes 553.95 s; no lifecycle gain is claimed.
A calibration-rejected policy would skip view construction in deployment; the
charged test bundle above represents this experiment, not necessary exact-only cost.
Graph import, warmup, profile file reading and test-oracle work are excluded online.
Confirmation also checks 240 sampled answers against an independently loaded CSV oracle.

## Update safety

Controlled insertion: stale rejection, exact fallback, changed-source rebuild refusal, old-generation rejection and legitimate empty answers all pass. Fallback 159.76 ms; restored-snapshot recovery 22.61 s.
The mutation explicitly invalidates sample state atomically. This is not an
arbitrary external-write detector or a concurrent update/full official Update6 proof.
Source totals detect this insertion, but not property edits or same-size rewrites.
Two overlapping development attempts are marked interrupted and excluded.

## SF1 quality only

| Fidelity | Nonempty holdout quality passes | Failed seed epochs | Maximum count error |
|---|---:|---:|---:|
| 0.25 | 0/900 | 50/50 | 180.0% |
| 0.5 | 0/900 | 50/50 | 100.0% |
| 0.75 | 8/900 | 50/50 | 100.0% |
| 0.9 | 75/900 | 50/50 | 100.0% |
| 1 | 900/900 | 0/50 | 0.0% |

Official initial SF1: 9,892 people, 90,492 forums, 1,003,605 posts. Five calibration roots / 20 seeds and 20 other test roots / 50 seeds; custom full membership window.
2 of 20 test roots have empty results; their empty/empty agreement is excluded from the table. Quality-only calibration selects fidelity 1. This selection omits the database cost gate and is not live adaptive performance.
Raw CSV inputs stay outside Git; table hashes and row counts are published.
This is not SF1 Neo4j throughput, official substitution coverage or certification.

## New parameter stress

Three previously fitted topology profiles each face 100 new rank seeds and
3,000 unique intervals, disjoint from training, pilot and confirmation.
Each topology: 0/4,000 supported node/edge answers violate their individual
5/10/20% budget. The 1,000 sparse and 1,000 unknown-country answers all run
exactly. This offline quality replay adds no database speedup evidence.
Seeds and graph generator are shared across topologies for controlled comparison,
not 300 independent graph trials. Zero observed failures is not a guarantee.

## Full reference replay and decision

The latest exact implementation passes the entire 138,474-operation reference
file, all 29 operation types, after the update1 repair.
In validate_database mode the whole reference file is processed; the
operations_requested=10000 benchmark setting does not truncate that file.
This validation is not an adaptive mixed-workload speed result or certified audit.
The earlier long-path import failure is retained separately; the successful
run uses a new database and never reuses the partially imported one.

Dense counts alone do not make top-k approximation safe: close/tied cutoff
groups can swap rank. Retain exact execution for these ranked queries.
The next useful approximation target is a count-only SUM/COUNT analytical
workload without a fragile top-20 boundary (e.g. separately scoped SNB BI),
with independent calibration, a pristine baseline, and a mixed read/update
test only after a per-query quality-and-total-cost gate passes.
The CV claim remains the prior scoped 1.34x static synthetic COUNT result.
