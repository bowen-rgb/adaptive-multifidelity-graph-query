# LDBC SNB v1 reference attribution

Source: https://github.com/ldbc/ldbc_snb_interactive_v1_impls

Pinned commit: `11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`.

The optional downloader retrieves two official micro-fixture CSVs and their upstream
Apache-2.0 LICENSE/NOTICE. Data are not redistributed in this project. Original notices
are retained here and with downloaded inputs.

The namespace-scoped IS3 Cypher implementation follows upstream IS3 result semantics;
labels, namespace filter and integer identifier storage are adapted for isolation.
The Python oracle, loader, benchmark and derived COUNTs are project implementations.
Only exact IS3 is a selected official read semantic check. Derived COUNTs are custom,
not replacements for official SNB queries or an audited benchmark result.

v0.12 also builds the pinned upstream Java/Cypher implementation and stores query
snapshots with experiment outputs. These upstream query files remain Apache-2.0.
Modified files: Java connection routing accepts `neo4j.database`; IC1/SQ7 use
explicit null checks; update1 uses consistent `speaks` and `WORK_AT`; optional IC14
materialization rewrites IC14 and maintains exact weights in updates7/8. The rejected
bound-endpoint rewrite is retained as a measured unfavorable experiment.
Full-data download/streaming import and exact weight maintenance are project code.

v0.18 `graph_mf/ldbc_ic3_sampling.py` contains an IC3-derived Cypher constant
(`CANDIDATES`) under the upstream Apache-2.0 license. Changes supply sampled
Message IDs, retain exact Person/KNOWS eligibility and scale message counts by 1/f.
The read-only pilot, Bernoulli selection and tuple-quality analysis are project code.
This candidate is not enabled in the official mixed driver: stress quality and
upstream-cost comparisons failed. The original LICENSE.txt and NOTICE.txt above apply
to the IC3-derived Cypher as well as the retained upstream query snapshots.

v0.19 `graph_mf/ldbc_ic5_sampling.py` derives its IC5 Cypher structure from the
same pinned upstream Apache-2.0 query. Changes preserve exact friendship and
membership eligibility, use private sampled container relationships, retain forum
IDs and scale counts by 1/f. The Python CSV oracle, calibration and experiments
are project code. This candidate is not enabled in the official mixed driver.
The retained LICENSE.txt and NOTICE.txt also apply to this derived Cypher.
