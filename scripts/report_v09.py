"""Generate the measured v0.9 interval/recovery report from completed live blocks."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', type=Path, default=Path('results/neo4j/audit-v09'))
    args = parser.parse_args()
    parent = json.loads((args.live/'metadata.json').read_text(encoding='utf-8'))
    if parent['status'] != 'completed' or parent['backend'] != 'neo4j':
        raise ValueError('Completed live comparison required')
    summaries, streams, total = {}, {}, 0
    for case in parent['cases']:
        folder = args.live/case['name']
        meta = json.loads((folder/'metadata.json').read_text(encoding='utf-8'))
        if meta['status'] != 'completed' or meta['backend'] != 'neo4j' or not meta['all_counts_match_numpy']:
            raise ValueError('Completed validated live block required')
        total += meta['timed_requests']
        summaries[case['name']] = read(folder/'summary.csv')
        streams[case['name']] = read(folder/'streams.csv')
    def row(case, scenario, mode='audited'):
        return next(r for r in summaries[case] if r['scenario'] == scenario and r['mode'] == mode)
    full, targeted = row('timing-full', 'timing_fault'), row('timing-targeted', 'timing_fault')
    saving = 1-float(targeted['recovery_ms_mean'])/float(full['recovery_ms_mean'])
    paired = []
    for epoch in range(meta['epochs']):
        selected = [next(r for r in streams[c] if int(r['epoch']) == epoch and r['mode'] == 'audited')
                    for c in ('timing-full', 'timing-targeted')]
        paired.append(float(selected[1]['online_ms_per_request'])-float(selected[0]['online_ms_per_request']))
    rng = np.random.default_rng(9090)
    intervals = np.quantile(np.mean(rng.choice(paired, size=(3000, len(paired)), replace=True), axis=1), [.025, .975])
    evidence = dict(status='completed', timed_requests=total,
        recovery_preparation_reduction=saving, matched_stream_delta_ms=paired,
        bootstrap_interval_ms=intervals.tolist(), independent_unit='paired sample-seed stream, only three seeds',
        limitations='fixed block order, one predicate/tier/fault onset, static graph, no energy or universal speedup claim')
    source = Path('results/neo4j/deep-v06/synthetic-50000/profile.json')
    base = json.loads(source.read_text(encoding='utf-8'))
    for profile in (args.live/'timing-targeted').glob('recovered-*.json'):
        assert json.loads(profile.read_text(encoding='utf-8'))['levels'] == base['levels'], 'Accuracy model changed'
    evidence['source_profile_sha256'] = hashlib.sha256(source.read_text(encoding='utf-8').replace('\r\n', '\n').encode()).hexdigest()
    (args.live/'comparison.json').write_text(json.dumps(evidence, indent=2)+'\n', encoding='utf-8')
    n = meta['epochs']*meta['requests_per_stream']
    lines = ['# v0.9：审计间隔与定向计时恢复', '',
        '本轮优先解决 v0.8 的全量恢复开销，并把“审计间隔”作为明确的误差/成本取舍。',
        '完整的剩余计划和 v1.0 验收条件见 [路线图](roadmap-to-v1.md)。', '',
        '## 设计和可比较范围', '',
        f'完成 {total:,} 次真实 Neo4j 请求；5 万节点的既有静态图、DE 谓词和 performance 预算。',
        f"每个场景/模式为 {meta['epochs']} 个独立运行样本种子，每条流 {meta['requests_per_stream']} 次请求。",
        '比较间隔 5/10/20 下的健康/增益失真场景；另比较计时失真后的完整恢复与定向恢复。',
        '场景种子、预算、故障相位、精确/无审计/有审计路径保持一致。块内模式顺序随机化，块间顺序固定。',
        '所有故障从第 6 次请求开始，第 31 次前恢复；未改变图数据或制造真实服务器变慢。',
        'cached 选档用于覆盖近似路径，新样本构建和完整恢复成本都收费；不是短流最优策略。',
        '所有成功原始 COUNT，包括恢复计时查询，都与同种子 NumPy 参考核对。', '',
        '## 审计间隔', '',
        f'| 间隔 | 场景 | 精度抽查次数 | 返回值超预算/{n} | 全成本 ms/请求 | 首次隔离请求 |',
        '|---:|---|---:|---:|---:|---|']
    for interval in (5, 10, 20):
        case = f'interval-{interval}'
        for scenario in ('healthy', 'gain_fault'):
            selected = row(case, scenario)
            detections = [r['first_detection'] for r in streams[case] if r['mode']=='audited' and r['scenario']==scenario]
            lines.append(f"| {interval} | {scenario} | {selected['audits']} | {selected['served_violations']} | {float(selected['online_ms_per_request']):.2f} | {', '.join(d or '无' for d in detections)} |")
    lines += ['', '墙钟成本未随抽查次数单调变化；各块实际构建耗时不同且块序固定，不能据此认定哪个间隔最快。',
        '固定第 6 次发生故障时，5/10 间隔都在第 10 次检出，漏过第 6–9 次；20 间隔到第 20 次才检出。',
        '所以此处不能把 5 次间隔称为比 10 次更有效，也不能据此推荐所有负载的最佳间隔。',
        '在“所有请求均近似、永久失真、固定周期审计”的简化模型中，间隔 k 的最坏漏过数量为 k−1；',
        '若发生相位在周期中均匀分布，平均为 (k−1)/2。这是解析模型，不是本轮实测覆盖保证。', '',
        '## 单纯计时漂移：保留校准和抽样', '',
        '`refresh_timing(predicate)` 仅允许用于 timing_drift 隔离。它重测一个谓词的 2×8×2=32 个 COUNT，',
        '不重新拟合增益/误差界、不重建抽样；保留训练种子，使用运行样本收集计时反馈。',
        '这不是独立精度校准，也不能修复误差预算失败。新表完整验证后才发布；失败继续隔离。',
        '首次恢复近似结果仍需要精确锚点通过；如果新表只选择精确档，则状态仍为 probing。', '',
        f'| 恢复方式 | 准备均值 ms | 全成本 ms/请求 | 返回值超预算/{n} | 真正恢复近似的流数/{meta["epochs"]} |',
        '|---|---:|---:|---:|---:|']
    for name, selected in [('完整独立恢复', full), ('定向计时恢复', targeted),
                           ('完整块精确对照', row('timing-full', 'timing_fault', 'exact')),
                           ('定向块精确对照', row('timing-targeted', 'timing_fault', 'exact'))]:
        lines.append(f"| {name} | {float(selected['recovery_ms_mean']):.2f} | {float(selected['online_ms_per_request']):.2f} | {selected['served_violations']} | {selected['recovered_streams']} |")
    lines += ['', f'本轮定向恢复准备耗时比完整恢复低 **{100*saving:.1f}%**。',
        f'按相同运行种子配对，完整流成本差（定向−完整）均值为 {mean(paired):.2f} ms/请求，',
        f'三种子 bootstrap 95% 区间为 [{intervals[0]:.2f}, {intervals[1]:.2f}] ms/请求。',
        '只有三对种子且块间顺序固定，区间不能排除跨块环境偏差，不代表跨部署或总体加速。',
        '本轮定向恢复流仍慢于精确对照；改善恢复开销不等于整套系统胜过精确查询。', '',
        '## 成本、测试和下一步', '',
        '完整流成本包含实际初始构建、草稿/升档、选档、锚点、全部恢复准备和恢复后的实际构建。',
        '每条流的两个预热精确 COUNT、原始图导入及最初 v0.6 校准/计时成本未摊入。',
        '未测能耗；图仍完整存储，无内存节省结论。',
        '内存回退完成 1,920 次烟雾请求；定向计时是否选近似受回退计时表影响，不能当 Neo4j 性能证据。',
        '58 项测试全部通过，包含 5 项真实 Neo4j 集成测试；基础示例另通过无 NumPy/Neo4j 安装包检查。',
        '新增测试覆盖保留抽样/校准、禁止精度故障走计时恢复、计时失败不发布部分模型。',
        '下一步按路线图：先确认真实能耗仪表可用性，再扩展能耗目标与工作负载/统一报告。',
        '审计方面仍需多故障相位、多预算/谓词、自动恢复调度和更新版本协议。', '',
        '```powershell',
        'python scripts/compare_audit_v09.py --backend neo4j --epochs 3 --requests 60 --output results/local/new-comparison',
        'python scripts/report_v09.py --live results/local/new-comparison', '```', '',
        f'![抽查间隔与恢复成本](../{args.live.as_posix()}/comparison.png)', '',
        f'[完整对照摘要](../{args.live.as_posix()}/comparison.json)；',
        f'[块列表与执行顺序](../{args.live.as_posix()}/metadata.json)。',
        '每块目录保留 raw-results.csv、streams.csv、summary.csv、恢复记录、校准模型与状态事件。', '']
    Path('docs/v09-audit-optimization.md').write_text('\n'.join(lines), encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].bar(['5', '10', '20'], [int(row(f'interval-{i}', 'gain_fault')['served_violations']) for i in (5, 10, 20)])
    axes[0].set_xlabel('Audit interval, fault starts at request 6')
    axes[0].set_ylabel(f'Served budget violations / {n} requests')
    axes[1].bar(['Full recovery', 'Timing-only'], [float(r['recovery_ms_mean']) for r in (full, targeted)])
    axes[1].set_ylabel('Measured recovery preparation, ms')
    fig.tight_layout()
    fig.savefig(args.live/'comparison.png', dpi=160)
    plt.close(fig)
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == '__main__':
    main()
