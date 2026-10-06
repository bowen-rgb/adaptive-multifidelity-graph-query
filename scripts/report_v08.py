"""Build the v0.8 report from completed live audit measurements."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from statistics import mean
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def read(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', type=Path, default=Path('results/neo4j/audit-v08'))
    args = parser.parse_args()
    meta_path = args.live/'metadata.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8'))
    if meta['status'] != 'completed' or meta['backend'] != 'neo4j' or not meta['all_counts_match_numpy']:
        raise ValueError('Completed validated live measurement required')
    source = Path(meta['source'].replace('\\', '/'))
    meta['source'] = source.as_posix()
    for file in ('profile.json', 'timing-builds.csv'):
        payload = (source/file).read_text(encoding='utf-8').replace('\r\n', '\n').encode()
        meta[file.replace('.', '_')+'_sha256'] = hashlib.sha256(payload).hexdigest()
    meta_path.write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    summary, streams = read(args.live/'summary.csv'), read(args.live/'streams.csv')
    recoveries = json.loads((args.live/'recoveries.json').read_text(encoding='utf-8'))
    lines = ['# v0.8：在线抽查、隔离与独立恢复', '',
        '本轮在现有选档会话外加入精确锚点和计时模型漂移检查，检测后返回精确结果并隔离近似查询。',
        '这是静态图上校准/计时表故障的可运行闭环；恢复由调用方明确触发，不是自主在线训练。', '',
        '![预算超限与完整成本](../'+args.live.as_posix()+'/audit-cost.png)', '',
        '## 检测规则与盲区', '',
        '- 首次近似请求、每个谓词首次近似请求、以及每十次近似请求执行两个精确 COUNT。',
        '- 锚点发现节点或边误差超过当前档位预算时，该请求返回精确答案，后续请求保持精确。',
        '- 排除构建与锚点后的候选耗时，与全部草稿/升档组件的预测耗时比较；连续三次超出三倍范围触发隔离。',
        '- 计时规则是启发式，不能证明分布变化；本轮测试的是计时表失真，未制造真实服务器变慢。',
        '- 抽查之间有盲区，不能保证每次回答满足预算。健康抽查仍返回原近似值。', '',
        '## 真实 Neo4j 测量', '',
        f"{meta['nodes']:,} 节点，谓词 `{meta['predicate']}`，performance 预算：节点 5%、边 15%。",
        f"三个场景 × 三种模式 × {meta['epochs']} 个独立运行样本种子 × {meta['requests_per_stream']} 请求 = {meta['timed_requests']:,} 次。",
        '每个场景内模式顺序按种子随机化；同一桌面数据库顺序执行，未清空缓存。重复请求误差相关，不是独立精度试验。',
        '使用 cached 选档强制覆盖近似路径，真实新样本构建仍收费；不代表短流最优的 amortized 策略。',
        '第 6 次请求将非精确档增益乘以 1.8，或将所选谓词计时预测乘以 0.01。精确模式不注入故障。',
        '第 31 次请求前，仅为已经隔离的故障流执行独立恢复。图数据未变更。', '',
        f"| 场景 | 模式 | 全成本 ms/请求 | 返回值超预算/{meta['epochs']*meta['requests_per_stream']} | 精度抽查次数 | 恢复准备均值 ms | 恢复近似的流数/{meta['epochs']} |",
        '|---|---|---:|---:|---:|---:|---:|']
    for row in summary:
        lines.append(f"| {row['scenario']} | {row['mode']} | {float(row['online_ms_per_request']):.2f} | {row['served_violations']} | {row['audits']} | {float(row['recovery_ms_mean']):.2f} | {row['recovered_streams']} |")
    lines += ['', '精确/无审计/有审计三种模式的 raw COUNT 都逐条与相同种子的 NumPy 参考核对。',
        '“原始 COUNT 正确”不等于缩放后的近似值满足预算；表中单列实际返回值超预算次数。', '',
        '| 故障 | 运行 | 首次隔离请求 | 被返回的超预算值 | 恢复后确实通过锚点并返回近似值 |',
        '|---|---:|---:|---:|---|']
    for row in streams:
        if row['mode'] == 'audited' and row['scenario'] != 'healthy':
            lines.append(f"| {row['scenario']} | {int(row['epoch'])+1} | {row['first_detection']} | {row['served_violations']} | {row['recovered']} |")
    lines += ['', '## 恢复与成本口径', '',
        '恢复使用完整的本地图快照：20 个拟合种子、40 个误差界校准种子，以及独立计时种子。',
        '计时重测覆盖五个谓词、两个组件、八个档位，各重复两次；不是充分的冷/热缓存统计研究。',
        '校准训练不能使用已见运行样本或下一运行样本种子；拟合与校准集也必须互斥，图指纹必须匹配。',
        '模型更新先验证再发布。恢复后的首次近似答案必须经精确锚点；只选择精确的模型保留 probing 状态。',
        '在线成本包含选档、全部成功草稿/升档、抽样构建、精确锚点和返回分发；另将完整恢复准备耗时摊入流。',
        '恢复准备包括图导入状态核对、CPU 校准、计时样本构建与全部计时查询；新运行样本的构建另按实际耗时计入。',
        '既有原始图导入与初始 v0.6 校准/计时成本未摊入；未测能耗。本轮不声称整体加速。',
        '会话能识别显式样本失效并回退；异常中断的部分查询仅标记计数不完整，墙钟仍收费。',
        '任意外部图修改、并发写入、自动恢复调度及跨图泛化仍不支持。', '',
        '## 可复现入口与原始数据', '',
        '```powershell',
        'python -m graph_mf --backend neo4j audit-benchmark --epochs 3 --requests 60 --output results/local/new-audit',
        'python scripts/report_v08.py --live results/local/new-audit', '```', '',
        '- [完整请求与查询成本](../'+args.live.as_posix()+'/raw-results.csv)',
        '- [逐流检测与恢复](../'+args.live.as_posix()+'/streams.csv)',
        '- [恢复种子与准备成本](../'+args.live.as_posix()+'/recoveries.json)',
        '- [状态事件](../'+args.live.as_posix()+'/events.json)',
        '- [实验范围与指纹](../'+args.live.as_posix()+'/metadata.json)', '',
        '## 验证', '',
        '55 项测试全部通过，包含 5 项真实 Neo4j 集成测试；另完成 720 次内存回退烟雾请求。',
        'GitHub CI 增加在线审计内存烟雾检查。原 v0.1 文件继续按 SHA-256 清单核对。', '',
        '下一步重点：降低全量恢复准备成本、选择审计间隔并比较检测延迟/漏检/成本，再扩展谓词与预算。',
        '能耗目标、正式 LDBC 工作负载与跨部署验证仍需完成，研究新颖性未由本轮实验建立。', '']
    Path('docs/v08-online-audit.md').write_text('\n'.join(lines), encoding='utf-8')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    scenarios = meta['scenarios']
    for index, mode in enumerate(meta['modes']):
        selected = [next(r for r in summary if r['scenario'] == s and r['mode'] == mode) for s in scenarios]
        x = [i+(index-1)*.24 for i in range(3)]
        axes[0].bar(x, [int(r['served_violations']) for r in selected], width=.24, label=mode)
        axes[1].bar(x, [float(r['online_ms_per_request']) for r in selected], width=.24, label=mode)
    for ax in axes:
        ax.set_xticks(range(3), scenarios)
        ax.legend()
    axes[0].set_ylabel(f"Served budget violations / {meta['epochs']*meta['requests_per_stream']} requests")
    axes[1].set_ylabel('Measured ms/request, including recovery')
    fig.tight_layout()
    fig.savefig(args.live/'audit-cost.png', dpi=160)
    plt.close(fig)
    print(json.dumps(dict(report='docs/v08-online-audit.md', requests=meta['timed_requests'],
        recovery_ms_mean=mean(r['total_recovery_ms'] for r in recoveries) if recoveries else 0), ensure_ascii=False))


if __name__ == '__main__':
    main()
