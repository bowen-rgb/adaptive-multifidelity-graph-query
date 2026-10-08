"""Audit existing immutable measurements and create a CV-ready evidence summary."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_evidence import schedule_audits, service_metrics


def evidence_sha256(path):
    # Text artifacts use Git LF normalization; hash the same canonical bytes on both OSes.
    return hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--matrix',type=Path,default=Path('results/neo4j/ldbc-full-v012/mixed-tcr10'))
    p.add_argument('--output',type=Path,default=Path('results/neo4j/ldbc-evidence-v013'))
    a=p.parse_args()
    matrix=json.loads((a.matrix/'matrix.json').read_text())
    if matrix['status']!='processes_completed' or len(matrix['runs'])!=2*matrix['blocks']:
        raise ValueError('Complete paired matrix required')
    evidence=[]; operation_rows=[]; sources=[]
    for run in matrix['runs']:
        root=a.matrix/f'block-{run["block"]}-{run["variant"]}'/'driver'
        result=root/'driver-results/LDBC-SNB-results.json'
        audits=schedule_audits((root/'driver.log').read_text(encoding='utf-8'),expected_phases=2)
        if not audits['measurement_pass']:
            raise ValueError('Measurement phase scheduling must pass independently of warmup')
        measured=service_metrics(json.loads(result.read_text()))
        coverage=measured.pop('operations')
        evidence.append(dict(block=run['block'],variant=run['variant'],**measured,
                             preparation_ms=(run['preparation'] or {}).get('build_ms',0),
                             ic14_mean_ms=coverage['LdbcQuery14']['mean_ms'],
                             ic14_count=coverage['LdbcQuery14']['count'],
                             measurement_schedule_pass=audits['measurement_pass']))
        operation_rows.extend(dict(block=run['block'],variant=run['variant'],operation=k,**v) for k,v in coverage.items())
        sources.append(dict(path=result.as_posix(),sha256=evidence_sha256(result),normalization='CRLF to LF'))
    a.output.mkdir(parents=True,exist_ok=True)
    write_csv(a.output/'service-cost.csv',evidence)
    write_csv(a.output/'operation-cost.csv',operation_rows)
    pairs=[]
    for block in range(matrix['blocks']):
        rows={r['variant']:r for r in evidence if r['block']==block}
        base,changed=rows['reference'],rows['materialized']
        if base['actual_operations']!=changed['actual_operations']:
            raise ValueError('Matched request counts required')
        pairs.append(dict(block=block,reference_service_ms=base['cumulative_operation_ms'],
                          materialized_service_ms=changed['cumulative_operation_ms'],
                          service_ratio=base['cumulative_operation_ms']/changed['cumulative_operation_ms'],
                          service_plus_build_ratio=base['cumulative_operation_ms']/(changed['cumulative_operation_ms']+changed['preparation_ms'])))
    write_csv(a.output/'paired-service.csv',pairs)
    names=sorted({r['operation'] for r in operation_rows if r['variant']=='reference'})
    hot=[]
    for name in names:
        rows=[r for r in operation_rows if r['operation']==name and r['variant']=='reference']
        hot.append(dict(operation=name,mean_total_ms=mean(r['total_ms'] for r in rows)))
    hot.sort(key=lambda x:x['mean_total_ms'],reverse=True)
    write_csv(a.output/'baseline-hotspots.csv',hot)
    summary=dict(status='completed',tcr=matrix['tcr'],paired_blocks=matrix['blocks'],sources=sources,
        measurements=evidence,pairs=pairs,baseline_hotspots=hot,
        reference_mean_service_ms=mean(r['reference_service_ms'] for r in pairs),
        materialized_mean_service_ms=mean(r['materialized_service_ms'] for r in pairs),
        overall_service_speedup=mean(r['reference_service_ms'] for r in pairs)/mean(r['materialized_service_ms'] for r in pairs),
        saturated_throughput_measured=False,approximate_controller_on_full_snb=False,
        interpretation='Matched paced workload; cumulative operation durations are not CPU time or saturated throughput. Single host/graph; no cross-scale inference.')
    ic9_path=a.output/'ic9-local-topk/metadata.json'
    ic9_text='IC9 局部 top-k 候选尚未运行，不接入正式 driver。'
    if ic9_path.exists():
        ic9=json.loads(ic9_path.read_text(encoding='utf-8'))
        summary['ic9_candidate_evidence']=dict(path=ic9_path.as_posix(),sha256=evidence_sha256(ic9_path),normalization='CRLF to LF',
                                            status=ic9['status'],adopted=ic9.get('adopted',False))
        if ic9['status']=='completed':
            ic9_text=(f"IC9 局部 top-k 候选完成 {ic9['timed_queries']} 次计时查询、"
                f"{len(ic9['parameters'])} 组参数 × {ic9['blocks']} 块 × 两种变体，"
                f"所有有序完整结果一致。基线 {ic9['reference_mean_ms']:.2f} ms，"
                f"候选 {ic9['candidate_mean_ms']:.2f} ms，比值 {ic9['speedup']:.3f}。"
                "本轮没有采用候选；结果来自参考回放后的单个 SF0.1 图、热缓存和查询耗时，"
                "不能推断完整工作负载收益。保留 requests.csv 与失败方向，以免只报告有利结果。")
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    table='\n'.join(f'| {r["block"]} | {r["reference_service_ms"]/1000:.3f} | {r["materialized_service_ms"]/1000:.3f} | {r["service_ratio"]:.3f} |' for r in pairs)
    hot_table='\n'.join(f'| {r["operation"]} | {r["mean_total_ms"]/1000:.3f} |' for r in hot[:5])
    Path('docs/current-goal-audit.md').write_text(f'''# 原计划与 CV 证据审计 — 2026-10-08

项目已经具备可放入 CV 的数据库研究工程成果。原研究假设——降低 fidelity 在控制误差下
改善完整查询工作负载成本——仍未证明。本文重读原始 technical note、路线图和原始官方
driver JSON；没有改变旧实验或期望答案。

后续 [v0.15 算法实验](v015-dlss-history.md) 已在静态合成 COUNT 长流中观察到计入记录中
训练/准备成本的收益。这是有限条件下的算法证据，不改变完整 SNB、自适应跨图和正式
基准仍待验证的判断。

## 距离目标的差距

| 原目标 | 当前可核验状态 | 验收仍缺什么 |
|---|---|---|
| Neo4j + Cypher 与可运行原型 | 已完成；离线 fallback、真实数据库实验 | CV 可写 |
| LDBC SNB 工作负载 | SF0.1 全模式与 138,474 条参考操作、29 类型全部通过 | 最新 update1 修复的全文件回放；跨规模、正式长时协议 |
| 性能提升 | IC14 精确物化单项 8.68×，全元组核对、维护和构建成本可追溯 | 全 workload 的服务成本/最大可持续吞吐优势 |
| 自适应缩放与档位 | COUNT 校准、误差门控、滞回、构建感知和审计已实现 | 同条件消融与完整图查询上的优势；不能称已证明的新算法 |
| NSGA-II | 与穷举对照，64 档组合上的算法验证 | 更广测量空间、未见数据和搜索预算优势 |
| 内存/能耗 | RSS 和能耗接口存在 | 独立的内存节省证据；真实 joules，能耗目标仍禁用 |
| 研究报告与申请材料 | 分版报告、可复现记录、CI 和本页 CV 文案 | 统一方法报告、相关工作与面试讲解掌握 |

不能给这些项目平均分后说“已完成百分之多少”：基础工程、单项优化已成立，
整个自适应研究假设还需要实验结果支持。正式认证需要外部审计，当前未取得。

## 修正整体性能的测量口径

固定 TCR=0.1 的正式阶段每轮实际统计 9,895 条操作。六轮都通过最终 measurement
schedule audit；短运行实际执行 **28** 类，Update1 未执行，29 类仅在全参考回放中全部覆盖。
两种变体的 paced throughput 都约 27.87 ops/s，这是给定到达率下的观察值，不能推断
它们的最大可持续处理能力相同。

从非本地化 JSON 对每类 count × mean runtime 求和，得到实际操作服务成本：

| 块 | 基线累计服务 s | 物化累计服务 s | 基线/物化 |
|---:|---:|---:|---:|
{table}

服务均值 {summary['reference_mean_service_ms']/1000:.3f} → {summary['materialized_mean_service_ms']/1000:.3f} s，
比值 {summary['overall_service_speedup']:.3f}；三块均不支持整体服务加速。权重构建还需另外收费。
累计服务不是 CPU 时间、焦耳或端到端墙钟；不同类型的延迟变化可能来自缓存/机器噪声等，
这三块不支持将变化因果归于物化本身。固定到达率下的墙钟主要还包括等待。

基线最耗时的五种操作（按实际调用频率加权）为：

| 操作 | 每块平均累计服务 s |
|---|---:|
{hot_table}

### 本轮继续实施的结果

{ic9_text}

下一步先检查 IC9/IC3 的执行计划与高代价扩展，候选必须通过完整结果比较和正向测量，
再用相同输入的混合工作负载检查全成本。随后回放最新 update1 查询版本的完整参考序列，
再做跨规模与自适应消融，不能把单项精确优化归为自适应算法收益。

## CV 可用表述

见 [CV 项目文案](cv-project.md)。已有贡献是可复现图数据库实验系统、完整参考覆盖和
经过测量的精确查询优化。自适应原型单独写为 implemented/prototyped，不能把精确
物化的提升算作 DLSS 或 NSGA-II 的增益。

## 可复核记录

`python scripts/report_project_evidence.py` 可从原 JSON 重建全部表格；来源 SHA-256、
逐类型服务成本与真实执行覆盖保存在 `results/neo4j/ldbc-evidence-v013`。
文本证据 SHA-256 按 CRLF 转为 LF 后计算，跨 Windows/Linux 和 Git 检出保持一致；
原始旧文件未改写。
调度判断已修正为检查最后的正式阶段，预热 PASS 不再掩盖正式阶段 FAIL。
77 项旧测试表示总发现数，其中 9 项实时测试跳过，不应写成 77 个都实际执行通过。
旧 live 与 LDBC 空库测试须隔离运行：旧测试先创建夹具才导致 2,004 节点断言失败，
没有证据说明 Neo4j CREATE OR REPLACE 本身失效。
''',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('sources','measurements','pairs','baseline_hotspots')},indent=2))


if __name__=='__main__':
    main()
