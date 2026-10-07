# 完整 SNB Interactive v1 运行步骤

本项目的“完整 LDBC”主线明确为 **SNB Interactive v1：14 个复杂读、7 个短读、8 个更新**。
BI、Interactive v2、第三方认证审计属于其他范围。各操作均执行精确语义；DLSS 式允许误差的
研究实验不能替代此验证。启用全部操作不等于每个操作已实际执行，必须检查覆盖表。

## 工具与固定来源

- Neo4j 独立实验数据库；现有学习/COUNT 数据库保留。
- Java JDK 11 和 Maven；参考实现编译目标为 Java 8，此环境使用 JDK 11。
- `pip install -e ".[ldbc]"`，提供 Neo4j 驱动与 zstd 解压。原来的内存模式不需要这些依赖。
- [官方实现固定提交](https://github.com/ldbc/ldbc_snb_interactive_v1_impls/tree/11db98cc2ba14c33492f6c0c34e68c8be7e22e5f)。
- [官方数据入口](https://ldbcouncil.org/benchmarks/snb/datasets/)：CsvComposite + LongDateFormatter、
  同规模参数和单分区更新流。下载哈希记录到 manifest；不是独立发布校验和认证。
- [官方验证参数](https://datasets.ldbcouncil.org/interactive-v1/validation_params-interactive-v1.0.0-sf0.1-to-sf10.tar.zst)。
  保留原文件，验证按其原始顺序执行，不能删掉较早的更新后再抽取后面的读。

```powershell
git clone https://github.com/ldbc/ldbc_snb_interactive_v1_impls.git work/ldbc-reference
git -C work/ldbc-reference checkout 11db98cc2ba14c33492f6c0c34e68c8be7e22e5f
python scripts/prepare_ldbc_reference.py --reference work/ldbc-reference
mvn -f work/ldbc-reference/pom.xml package -DskipTests -Pcypher
python scripts/download_ldbc_full.py --scale-factor 0.1 --output results/local/sf01-input
```

Java 补丁只添加显式数据库路由，避免默认数据库被写入。查询快照在每次运行中固定：
IC1/SQ7 的 null 判断、update1 的语言字段与工作关系类型修正有独立参考结果检验。
原始与修改文件的来源及 Apache LICENSE/NOTICE 在 `third_party/ldbc`。

## 导入与恢复

在 Neo4j 创建专用数据库（例如 `ldbcmfbench01`），环境变量指向它。
`NEO4J_PASSWORD` 只在本地进程环境设置，不写到项目文件。
加载器拒绝 `neo4j`/`system` 和已有节点的数据库；失败时保留状态，不能在部分导入上继续测量。
节点/关系 CSV 全表要求存在；按官方 header 位置解析，空字符串按 admin-import 语义省略，
ID 与日期存为整数、属性数组保留。所有边端点与全表节点/关系总数核对。

```powershell
$env:NEO4J_DATABASE="ldbcmfbench01"
python scripts/load_ldbc_full.py --dataset-path results/local/sf01-input/initial/social_network-sf0.1-CsvComposite-LongDateFormatter --reference work/ldbc-reference --output results/local/import.json
```

**更新会持久化**。每次验证/混合计时前，恢复初始快照或重新创建专用实验数据库并导入。
不能在前一轮已有更新的图上开始下一轮。数据库导入与可选权重准备单独计时；同输入比较应同时
给出查询服务阶段、物化准备摊销及含导入的完整生命周期成本。

## 官方驱动

```powershell
python scripts/run_ldbc_driver.py --reference work/ldbc-reference --java path/to/jdk/bin/java.exe --parameters results/local/sf01-input/parameters/substitution_parameters-sf0.1 --updates results/local/sf01-input/updates/social_network-sf0.1-numpart-1 --validation-file path/to/validation_params-sf0.1.csv --mode validate_database --output results/local/validation
# 恢复初始数据库后，执行全部启用的混合负载：
python scripts/run_ldbc_driver.py --reference work/ldbc-reference --java path/to/jdk/bin/java.exe --parameters results/local/sf01-input/parameters/substitution_parameters-sf0.1 --updates results/local/sf01-input/updates/social_network-sf0.1-numpart-1 --mode execute_benchmark --output results/local/mixed --operations 10000 --warmup 1000 --threads 1 --tcr 0.001
```

运行后必须检查 `driver.log` 的验证结论、逐类型正确/总数、调度审计、实际操作数、吞吐与延迟。
进程 exit code 0 不能单独证明通过。若调度未通过，应在新初始快照上调整 TCR 重新运行，保留失败。
当前小规模、短时长、单读线程测试不能写成认证成绩；官方认证运行另要求长预热、长测量与外部审计。

## 精确 IC14 权重物化

`--materialized-ic14` 在驱动前实际构建精确回复权重：回复 Post 权重 1，回复 Comment 权重 0.5，
两个方向求和。新增 Comment 与 Friendship 在同一业务操作事务维护权重，其他六种插入不改变
既有回复权重。空标签数组仍先维护权重，不能因后续 UNWIND 为空而漏掉维护。

驱动验证和混合比较都可加此参数。物化构建不是免费的，更新维护也在业务耗时中。
任意外部写入、删除和其他工作负载版本不支持；未验证的多线程并发不能推断可靠。
不使用事后答案、不绕过官方 driver，也不把这项精确优化称为 DLSS 自适应算法的增益。

```powershell
python scripts/benchmark_ldbc_ic14.py --reference work/ldbc-reference --parameters results/local/sf01-input/parameters/substitution_parameters-sf0.1 --output results/local/ic14-paired --materialized
```

完整路径/权重逐次核对；权重相同的路径允许任意内部顺序。计时随机交错、按块记录，包含客户端
和事务开销，报告构建回本点。单图固定参数集的置信区间只描述本工作负载，不外推为整体 SNB 提升。
