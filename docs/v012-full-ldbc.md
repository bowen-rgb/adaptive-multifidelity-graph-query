# v0.12：完整 SNB Interactive v1 验证与性能主线

用户指定优先完成真实性能与完整 SNB，暂缓额外微型校准、能耗仪表及故障参数扩展。
本版接入完整 Interactive v1 14 复杂读、7 短读、8 更新；所有查询保留精确语义。
这项精确权重优化与 DLSS 式允许误差的方法分别报告，不能作为后者的增益证明。

## 正式数据与完整参考文件

[官方数据入口](https://ldbcouncil.org/benchmarks/snb/datasets/)的 SF0.1 初始图：
327,588 节点、1,477,965 关系，全部 32 张实体/关系表。
CsvComposite/LongDateFormatter 的 ID、UTC 毫秒、数组、空字段与类型标签按官方导入布局处理。
原始数据和参考文件保留在 work/datasets；GitHub 仅保存来源/哈希、代码和测量。
独立数据库与完整端点/总数核对保护原项目数据。混合独立运行前恢复初始图。

固定实现提交：`11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`。
Java 1.2.0 driver + 原 Cypher client 加显式数据库路由；查询修正 IC1/SQ7 的 null 判断、
update1 的 speaks/WORK_AT 一致性。首次错误导入/验证及被否定的改写全部保留。

官方公开 SF0.1 参考文件的全部 **138,474** 条操作均执行并通过。
两段为前 37,332 条及剩余 101,142 条，在同一数据库上连续执行；中间不恢复或重新抽取。
分段 SHA-256 与原文件完整 SHA-256 可核对；没有删去前序更新或修改期望答案。
参考 SHA-256：`887dff7c7b52cfb080fdbfaf6050fd2552a7a7ae972cf13952242d5ee07d0c81`。零 missing handler、零 crashed、零 incorrect。
总验证时间 1995.63 s；首次权重构建 2.33 s。

| 操作 | 正确 / 执行 |
|---|---:|
| LdbcQuery1 | 6051 / 6051 |
| LdbcQuery10 | 6051 / 6051 |
| LdbcQuery11 | 6051 / 6051 |
| LdbcQuery12 | 6050 / 6050 |
| LdbcQuery13 | 6051 / 6051 |
| LdbcQuery14 | 6051 / 6051 |
| LdbcQuery2 | 6051 / 6051 |
| LdbcQuery3 | 6051 / 6051 |
| LdbcQuery4 | 6051 / 6051 |
| LdbcQuery5 | 6051 / 6051 |
| LdbcQuery6 | 6050 / 6050 |
| LdbcQuery7 | 6050 / 6050 |
| LdbcQuery8 | 6050 / 6050 |
| LdbcQuery9 | 6051 / 6051 |
| LdbcShortQuery1PersonProfile | 8100 / 8100 |
| LdbcShortQuery2PersonPosts | 8100 / 8100 |
| LdbcShortQuery3PersonFriends | 8100 / 8100 |
| LdbcShortQuery4MessageContent | 5367 / 5367 |
| LdbcShortQuery5MessageCreator | 5367 / 5367 |
| LdbcShortQuery6MessageForum | 5367 / 5367 |
| LdbcShortQuery7MessageReplies | 5367 / 5367 |
| LdbcUpdate1AddPerson | 6 / 6 |
| LdbcUpdate2AddPostLike | 985 / 985 |
| LdbcUpdate3AddCommentLike | 639 / 639 |
| LdbcUpdate4AddForum | 94 / 94 |
| LdbcUpdate5AddForumMembership | 2425 / 2425 |
| LdbcUpdate6AddPost | 1195 / 1195 |
| LdbcUpdate7AddComment | 2548 / 2548 |
| LdbcUpdate8AddFriendship | 104 / 104 |

## 精确 IC14 物化与维护

先聚合双向回复：Comment→Post 权重 1、Comment→Comment 权重 0.5。
Person 对的精确权重另存，并复制到已有 KNOWS；IC14 原最短路径和权重排序保持精确。
Update7 在 Comment 创建事务更新 Person 对/已有友谊；Update8 创建新友谊时复制已有权重。
空 tagIds 先维护再 UNWIND；其余六个插入不改变既有回复权重。
写入静止后全量重算 51,589 个 Person 对，核对 14,177 条友谊，
全部匹配，重算与缓存哈希一致。额外存储并未被称为内存节省。
任意外部修改/删除、其他工作负载及未经验证的多线程执行不在支持范围。

## 单项查询与准备成本

官方 IC14 参数文件实际 15 对；请求随机交错，5 个计时块，完整路径/权重每次核对。
绑定端点改写从 25.32 ms 变为 341.89 ms，
慢 13.51 倍；保留失败，不采用。
精确物化在已执行 5,000 条参考操作的图上，从 26.10 ms
变为 3.01 ms，查询均值比 8.68。
条件于单图固定参数的计时块 bootstrap 区间为
[8.06, 9.39]。
构建 3.00 s，约 130 次请求回本。
75 次候选计时请求本身不足回本，不能将这次短计时的 query-only 比当作生命周期收益。
当前这是可复现的局部精确优化，尚不证明跨规模或 DLSS 自适应收益。

## 混合工作负载

3 组配对、每轮新初始快照、全部 29 类型启用；各轮通过调度审计。
固定 TCR=0.1，请求数参数 10000，预热数参数 1000。
生命周期为实际导入 + 权重构建 + Java 启动/预热/执行；维护在更新耗时中。

| 配对块 | 基线生命周期 s | 物化生命周期 s | 基线/物化 |
|---|---:|---:|---:|
| 0 | 562.65 | 557.89 | 1.009 |
| 1 | 565.43 | 563.12 | 1.004 |
| 2 | 551.29 | 602.92 | 0.914 |

均值比 0.974。该字段不是官方 throughput；导入噪声及固定到达率也会影响生命周期。
实际业务服务延迟、吞吐、执行覆盖与错误必须另看 driver-results 和逐轮日志。
不以较短 wall time 自动断言最大可持续吞吐提升。

正式阶段服务摘要（driver 日志，另含预热阶段）：

| 块 | 变体 | 实际操作数 | 吞吐 ops/s | IC14 均值 ms |
|---:|---|---:|---:|---:|
| 0 | reference | 9895 | 27.87 | 25.92 |
| 0 | materialized | 9895 | 27.87 | 2.53 |
| 1 | materialized | 9895 | 27.87 | 1.86 |
| 1 | reference | 9895 | 27.87 | 31.45 |
| 2 | reference | 9895 | 27.87 | 38.93 |
| 2 | materialized | 9895 | 27.86 | 3.97 |

## 验证、边界与下一项

离线套件 77/77 通过（需要数据库的 9 项按条件跳过）；新 LDBC 专用空库的 3/3
实时回归通过，包括空属性、类型标签、多最短路径、零长度路径、未连通、空标签维护、
新友谊继承及故意损坏权重检测。旧版 Neo4j live 套件需使用自己的隔离库；混用旧夹具
时曾留下节点，已作为环境卫生失败保留。无 NumPy/Neo4j 驱动环境安装包与原内存 smoke
可运行。原 v0.1 结果和后续实测保留。

完整 138,474 条参考回放使用固定的、已记录哈希的查询快照；随后新增的 update1 空
标签/学校/工作组合修复已由独立 8 组合实时回归覆盖，并补上查询结尾 RETURN，
但这项修复没有冒充已经重放的完整金标准序列。

这是完整类型、完整公开参考序列的 SF0.1 验证与本地研究测量，**不是第三方认证成绩**。
更大 SF、正式预热/测量时长、最优 TCR 搜索、并发、安全恢复及重复实验仍需具体测量。
能耗没有可读 CPU joules，DLSS/NSGA-II 尚未与这一全查询工作负载统一比较。
下一项以混合服务延迟与最大可持续吞吐为准；不能靠版本号或局部收益宣告整个项目目标完成。

[复现步骤](ldbc-full-runbook.md) · [覆盖记录](../results/neo4j/ldbc-full-v012/operation-coverage.csv) ·
[完整验证汇总](../results/neo4j/ldbc-full-v012/full-validation-summary.json)。
