# CV project — supported claims

## English (recommended for applications)

**Adaptive Graph Query Optimization — Independent Research Project**
Python, Neo4j, Cypher, LDBC SNB, NSGA-II · 2026

- Built a reproducible Neo4j benchmarking pipeline for LDBC SNB Interactive v1, loading 327k nodes and 1.48M relationships and validating 138,474 reference operations across all 29 operation types.
- Implemented transaction-maintained reply-weight materialization for exact shortest-path queries; measured an 8.68× IC14 query speedup on SF0.1, with construction cost and break-even analysis.
- Prototyped calibrated multi-fidelity COUNT queries with adaptive escalation, hysteresis and cost-aware sampling; compared evolutionary and exhaustive policy selection and documented accuracy and end-to-end cost limitations.

If space permits only two bullets, retain the first two. The 8.68× result is a
single-query, warm-cache result on one graph and fixed parameters; the full mixed
workload did not demonstrate overall acceleration. Do not describe this as a
certified benchmark or a demonstrated new DLSS algorithm.

## Français

**Optimisation adaptative de requêtes de graphes — Projet de recherche personnel**
Python, Neo4j, Cypher, LDBC SNB, NSGA-II · 2026

- Développement d'une chaîne d'expérimentation reproductible sur Neo4j : 327 000 nœuds, 1,48 million de relations et validation de 138 474 opérations de référence couvrant les 29 types de SNB Interactive v1.
- Implémentation d'une matérialisation exacte des poids de réponses, maintenue dans les transactions ; accélération mesurée de 8,68× pour IC14 sur SF0.1, avec mesure du coût de construction et du seuil d'amortissement.

## 面试时需要能解释的五件事

1. Node、Label、Property、Relationship 和一条 Cypher 查询。
2. COUNT 抽样的 inclusion probability；多跳路径为何不能直接使用 1/f²。
3. IC14 的最短路径、回复权重及 update7/update8 如何维护缓存。
4. 查询加速、构建回本、实际服务成本、固定到达率吞吐之间的区别。
5. 全参考序列验证与正式认证的区别，以及已有失败结果说明的适用边界。

个人 CV 应写自己实际参与、能够解释和复现的工作。项目使用 AI 辅助开发；
若目前仍不能解释全部代码，先从数据建模、实验复现与结果分析等实际掌握的贡献表述。
