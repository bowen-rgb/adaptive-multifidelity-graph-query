# CV project — supported claims

## Compact entry for today's applications

**Adaptive Graph Query Optimization — Python / Neo4j Research Project**

- Built a Neo4j/Cypher benchmarking pipeline on LDBC SNB SF0.1 (327k nodes, 1.48M relationships), validating 138,474 reference operations across 29 types.
- Implemented jointly calibrated adaptive COUNT sampling; measured 1.34× improvement in recorded training/preparation/query cost over 6,000 static-graph request pairs, with a 20% error budget and maximum observed error of 11.26%.

**Optimisation adaptative de requêtes de graphes — Python / Neo4j**

- Développement d'une chaîne de mesure Neo4j/Cypher sur LDBC SNB SF0.1 : 327 000 nœuds, 1,48 million de relations et validation de 138 474 opérations couvrant 29 types.
- Échantillonnage COUNT adaptatif avec calibration conjointe : amélioration de 1,34× du coût des phases mesurées sur 6 000 paires de requêtes, sous un budget d'erreur de 20 % (maximum observé : 11,26 %).

Repository: https://github.com/bowen-rgb/adaptive-multifidelity-graph-query

These bullets describe repository deliverables. Use first-person implementation
claims only for work you actually contributed to and can explain; if your current
contribution is setup/replication/analysis, replace "Implemented" with "Evaluated"
and "Built" with "Configured and reproduced". The measured scope below still applies.

## English (recommended for applications)

**Adaptive Graph Query Optimization — Independent Research Project**
Python, Neo4j, Cypher, LDBC SNB, NSGA-II · 2026

- Built a reproducible Neo4j benchmarking pipeline for LDBC SNB Interactive v1, loading 327k nodes and 1.48M relationships and validating 138,474 reference operations across all 29 operation types.
- Implemented transaction-maintained reply-weight materialization for exact shortest-path queries; measured an 8.68× IC14 query speedup on SF0.1, with construction cost and break-even analysis.
- Implemented jointly calibrated adaptive COUNT sampling; measured 1.34× acceleration across recorded training, preparation and query phases on 6,000 static-graph request pairs under a 20% error budget (maximum observed error: 11.26%; no observed budget violations).

For two bullets, use the first and third for algorithm-focused applications, or
the first two for database engineering. The 1.34× result covers one synthetic graph,
three rank epochs and known repeated predicates; graph import, profile loading and test-oracle checking are
excluded, and measured phases were recorded separately. No full SNB adaptive speedup
is claimed. Evolutionary/exhaustive search comparisons are a separate experiment.
Independent changing-budget ablations at 50k and 100k nodes measured 1.70× and
2.53× online ratios for the forecast policy without history (six test epochs/size).
Those exclude training/preparation and incur 0/720 and 9/720 budget violations;
they support the mechanism's measured trade-off, not a guaranteed error bound.
See [the ablation report](v016-ablation-publication.md) before quoting these figures.
Joint calibration subsequently observed zero budget violations across 100 fresh
sampling epochs per size (2,400 components each), compared with 5 and 4 for the
unchanged marginal policy. The new 1.34× phase-cost check is separate from the
earlier v0.15 1.78× result; see [the joint-policy experiment](v017-joint-calibration.md).
The 8.68× result is a
single-query, warm-cache result on one graph and fixed parameters; the full mixed
workload did not demonstrate overall acceleration. Do not describe this as a
certified benchmark or a demonstrated new DLSS algorithm.

## Français

**Optimisation adaptative de requêtes de graphes — Projet de recherche personnel**
Python, Neo4j, Cypher, LDBC SNB, NSGA-II · 2026

- Développement d'une chaîne d'expérimentation reproductible sur Neo4j : 327 000 nœuds, 1,48 million de relations et validation de 138 474 opérations de référence couvrant les 29 types de SNB Interactive v1.
- Implémentation d'une matérialisation exacte des poids de réponses, maintenue dans les transactions ; accélération mesurée de 8,68× pour IC14 sur SF0.1, avec mesure du coût de construction et du seuil d'amortissement.
- Développement d'un échantillonnage COUNT adaptatif avec calibration conjointe : accélération de 1,34× sur les phases mesurées pour 6 000 paires de requêtes sur un graphe synthétique statique, sous un budget d'erreur de 20 % (maximum observé : 11,26 % ; aucun dépassement observé).

## 面试时需要能解释的五件事

1. Node、Label、Property、Relationship 和一条 Cypher 查询。
2. COUNT 抽样的 inclusion probability；多跳路径为何不能直接使用 1/f²。
3. IC14 的最短路径、回复权重及 update7/update8 如何维护缓存。
4. 查询加速、构建回本、实际服务成本、固定到达率吞吐之间的区别。
5. 全参考序列验证与正式认证的区别，以及已有失败结果说明的适用边界。

个人 CV 应写自己实际参与、能够解释和复现的工作。项目使用 AI 辅助开发；
若目前仍不能解释全部代码，先从数据建模、实验复现与结果分析等实际掌握的贡献表述。
