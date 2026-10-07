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
