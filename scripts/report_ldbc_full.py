"""Consolidate complete contiguous published-reference validation and paired timings."""
import argparse
import json
import re
from pathlib import Path
from statistics import mean
from graph_mf.benchmark import write_csv

p=argparse.ArgumentParser()
p.add_argument('--results',default='results/neo4j/ldbc-full-v012')
p.add_argument('--mixed',help='Optional completed mixed-run matrix directory')
p.add_argument('--output',default='docs/v012-full-ldbc.md')
a=p.parse_args()
root=Path(a.results)
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def driver_service_metrics(path):
    """Parse the official driver's final (run, not warmup) summary."""
    lines=Path(path).read_text(encoding='utf-8',errors='replace').splitlines()
    counts=[(i,line) for i,line in enumerate(lines) if 'Operation Count:' in line]
    if len(counts)<2:
        raise ValueError(f'Expected warmup and run summaries in {path}')
    i=counts[-1][0]
    count=int(re.sub(r'\D','',lines[i].split(':',1)[1]))
    duration=re.search(r'(\d+):(\d+)\.(\d+)\.(\d+)',lines[i+1])
    throughput=float(re.search(r'([0-9]+,[0-9]+)',lines[i+2]).group(1).replace(',','.'))
    seconds=(int(duration.group(1))*60+int(duration.group(2))+int(duration.group(3))/1000+int(duration.group(4))/1_000_000) if duration else None
    block='\n'.join(lines[i:])
    q14=re.search(r'^    LdbcQuery14\s*$.*?^        Mean:\s+([0-9]+,[0-9]+)',block,re.M|re.S)
    q14_mean=float(q14.group(1).replace(',','.')) if q14 else None
    return dict(actual_operations=count,duration_s=seconds,throughput_ops_s=throughput,
                ic14_mean_ms=q14_mean,schedule_audit_pass='PASSED SCHEDULE AUDIT' in block)
sequence=read(root/'validation-sequence.json')
parts=[read(root/'sf01-weighted-validation/metadata.json'),read(root/'sf01-weighted-validation-suffix/metadata.json')]
if not all(x.get('validation_pass') and x.get('status')=='completed' for x in parts):
    raise ValueError('Both complete reference parts must pass')
if [x['validation_sha256'] for x in parts]!=[sequence['prefix_sha256'],sequence['suffix_sha256']]:
    raise ValueError('Reference segment checksums mismatch')
counts={}
for part in parts:
    for name,values in part['operation_coverage'].items():
        totals=counts.setdefault(name,dict(correct=0,total=0))
        for k in totals: totals[k]+=values[k]
if len(counts)!=29 or sum(x['total'] for x in counts.values())!=sequence['total_operations'] or any(x['correct']!=x['total'] for x in counts.values()):
    raise ValueError('All 29 operations and the complete published sequence must be covered')
audit=read(root/'weight-audit.json')
if not audit['all_pair_weights_match'] or audit['incorrect_friendship_weights']:
    raise ValueError('Global exact view audit must pass')
summary=dict(status='completed',total_operations=sequence['total_operations'],operation_types=29,
             counts=counts,source_sha256=sequence['source_sha256'],contiguous_parts=True,
             validation_ms=sum(x['elapsed_ms'] for x in parts),preparation_ms=parts[0]['preparation']['build_ms'],
             global_weight_audit=audit,certified_audit=False)
(root/'full-validation-summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
write_csv(root/'operation-coverage.csv',[dict(operation=k,**v) for k,v in sorted(counts.items())])
imported=read(root/'sf01-import-v4.json')
materialized=read(root/'ic14-materialized/metadata.json')
bound=read(root/'ic14-paired/metadata.json')
coverage='\n'.join(f'| {name} | {v["correct"]} / {v["total"]} |' for name,v in sorted(counts.items()))
mix='混合负载与调度实验尚未完成，不能将 IC14 单项收益写为整体吞吐提升。'
if a.mixed:
    matrix=read(Path(a.mixed)/'matrix.json')
    if matrix['status']!='processes_completed':
        raise ValueError('Completed paired mixed runs required')
    for run in matrix['runs']:
        meta=read(Path(a.mixed)/f'block-{run["block"]}-{run["variant"]}'/'driver/metadata.json')
        if not meta.get('schedule_audit_pass') or meta.get('status')!='completed':
            raise ValueError('Every mixed run must pass scheduling')
    rows=[]
    service_rows=[]
    for block in range(matrix['blocks']):
        pair={r['variant']:r for r in matrix['runs'] if r['block']==block}
        base=pair['reference'];candidate=pair['materialized']
        base_cost=base['import_preparation_driver_ms'];new_cost=candidate['import_preparation_driver_ms']
        rows.append(dict(block=block,reference_lifecycle_ms=base_cost,materialized_lifecycle_ms=new_cost,
                         lifecycle_ratio=base_cost/new_cost))
        for variant,run in pair.items():
            metrics=driver_service_metrics(Path(a.mixed)/f'block-{block}-{variant}'/'driver/driver.log')
            service_rows.append(dict(block=block,variant=variant,**metrics))
    write_csv(root/'mixed-lifecycle.csv',rows)
    write_csv(root/'mixed-service.csv',service_rows)
    text='\n'.join(f'| {r["block"]} | {r["reference_lifecycle_ms"]/1000:.2f} | {r["materialized_lifecycle_ms"]/1000:.2f} | {r["lifecycle_ratio"]:.3f} |' for r in rows)
    ratio=mean(r['reference_lifecycle_ms'] for r in rows)/mean(r['materialized_lifecycle_ms'] for r in rows)
    mix=f'''{matrix['blocks']} 组配对、每轮新初始快照、全部 29 类型启用；各轮通过调度审计。
固定 TCR={matrix['tcr']}，请求数参数 {matrix['operations']}，预热数参数 {matrix['warmup']}。
生命周期为实际导入 + 权重构建 + Java 启动/预热/执行；维护在更新耗时中。

| 配对块 | 基线生命周期 s | 物化生命周期 s | 基线/物化 |
|---|---:|---:|---:|
{text}

均值比 {ratio:.3f}。该字段不是官方 throughput；导入噪声及固定到达率也会影响生命周期。
实际业务服务延迟、吞吐、执行覆盖与错误必须另看 driver-results 和逐轮日志。
不以较短 wall time 自动断言最大可持续吞吐提升。'''
    service_text='\n'.join(f'| {r["block"]} | {r["variant"]} | {r["actual_operations"]} | {r["throughput_ops_s"]:.2f} | {r["ic14_mean_ms"] if r["ic14_mean_ms"] is not None else "n/a"} |' for r in service_rows)
    mix += f'''\n\n正式阶段服务摘要（driver 日志，另含预热阶段）：\n\n| 块 | 变体 | 实际操作数 | 吞吐 ops/s | IC14 均值 ms |\n|---:|---|---:|---:|---:|\n{service_text}'''
text=f'''# v0.12：完整 SNB Interactive v1 验证与性能主线

用户指定优先完成真实性能与完整 SNB，暂缓额外微型校准、能耗仪表及故障参数扩展。
本版接入完整 Interactive v1 14 复杂读、7 短读、8 更新；所有查询保留精确语义。
这项精确权重优化与 DLSS 式允许误差的方法分别报告，不能作为后者的增益证明。

## 正式数据与完整参考文件

[官方数据入口](https://ldbcouncil.org/benchmarks/snb/datasets/)的 SF0.1 初始图：
{imported['nodes']:,} 节点、{imported['relationships']:,} 关系，全部 32 张实体/关系表。
CsvComposite/LongDateFormatter 的 ID、UTC 毫秒、数组、空字段与类型标签按官方导入布局处理。
原始数据和参考文件保留在 work/datasets；GitHub 仅保存来源/哈希、代码和测量。
独立数据库与完整端点/总数核对保护原项目数据。混合独立运行前恢复初始图。

固定实现提交：`11db98cc2ba14c33492f6c0c34e68c8be7e22e5f`。
Java 1.2.0 driver + 原 Cypher client 加显式数据库路由；查询修正 IC1/SQ7 的 null 判断、
update1 的 speaks/WORK_AT 一致性。首次错误导入/验证及被否定的改写全部保留。

官方公开 SF0.1 参考文件的全部 **{summary['total_operations']:,}** 条操作均执行并通过。
两段为前 37,332 条及剩余 101,142 条，在同一数据库上连续执行；中间不恢复或重新抽取。
分段 SHA-256 与原文件完整 SHA-256 可核对；没有删去前序更新或修改期望答案。
参考 SHA-256：`{summary['source_sha256']}`。零 missing handler、零 crashed、零 incorrect。
总验证时间 {summary['validation_ms']/1000:.2f} s；首次权重构建 {summary['preparation_ms']/1000:.2f} s。

| 操作 | 正确 / 执行 |
|---|---:|
{coverage}

## 精确 IC14 物化与维护

先聚合双向回复：Comment→Post 权重 1、Comment→Comment 权重 0.5。
Person 对的精确权重另存，并复制到已有 KNOWS；IC14 原最短路径和权重排序保持精确。
Update7 在 Comment 创建事务更新 Person 对/已有友谊；Update8 创建新友谊时复制已有权重。
空 tagIds 先维护再 UNWIND；其余六个插入不改变既有回复权重。
写入静止后全量重算 {audit['reply_pairs']:,} 个 Person 对，核对 {audit['friendships']:,} 条友谊，
全部匹配，重算与缓存哈希一致。额外存储并未被称为内存节省。
任意外部修改/删除、其他工作负载及未经验证的多线程执行不在支持范围。

## 单项查询与准备成本

官方 IC14 参数文件实际 15 对；请求随机交错，5 个计时块，完整路径/权重每次核对。
绑定端点改写从 {bound['reference_mean_ms']:.2f} ms 变为 {bound['bound_mean_ms']:.2f} ms，
慢 {bound['bound_mean_ms']/bound['reference_mean_ms']:.2f} 倍；保留失败，不采用。
精确物化在已执行 5,000 条参考操作的图上，从 {materialized['reference_mean_ms']:.2f} ms
变为 {materialized['bound_mean_ms']:.2f} ms，查询均值比 {materialized['speedup']:.2f}。
条件于单图固定参数的计时块 bootstrap 区间为
[{materialized['conditional_block_bootstrap_95'][0]:.2f}, {materialized['conditional_block_bootstrap_95'][1]:.2f}]。
构建 {materialized['construction_ms']/1000:.2f} s，约 {materialized['materialization_break_even_requests']:.0f} 次请求回本。
75 次候选计时请求本身不足回本，不能将这次短计时的 query-only 比当作生命周期收益。
当前这是可复现的局部精确优化，尚不证明跨规模或 DLSS 自适应收益。

## 混合工作负载

{mix}

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
'''
Path(a.output).write_text(text,encoding='utf-8')
print(a.output)
