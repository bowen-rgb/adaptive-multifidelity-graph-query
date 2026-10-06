"""Report actual capability and COUNT instrumentation; never invent unavailable joules."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def read(path):
    with path.open(encoding='utf-8', newline='') as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', type=Path, default=Path('results/neo4j/energy-v010'))
    args = parser.parse_args()
    meta = json.loads((args.live/'metadata.json').read_text(encoding='utf-8'))
    if meta['status'] != 'completed' or meta['backend'] != 'neo4j' or not meta['all_counts_match_numpy']:
        raise ValueError('Completed validated Neo4j instrumentation required')
    probe = json.loads((args.live/'energy-capability.json').read_text(encoding='utf-8'))
    rows = read(args.live/'energy-streams.csv')
    queries = read(args.live/'queries/summary.csv')
    lines = ['# v0.10：能耗采集接口与本机可用性', '',
        '**本机 CPU 焦耳数未取得，能耗优化目标未启用。** 本版完成采集路径和缺失状态处理，不是能耗优化完成版。',
        '路线图的能耗实测验收项仍待完成；旧版本计时、校准与实验记录继续保留。', '',
        '## 本机探测', '',
        f"系统：{probe['platform']}。CPU 测量状态：`{probe['cpu_energy_status']}`。",
        f"原因：`{probe['cpu_energy_reason']}`。",
        '当前项目只实现只读 Linux powercap CPU-package 适配器；这次 Windows 环境没有已配置的可读 CPU 能量源。',
        '检查未发现运行中的 HWiNFO/LibreHardwareMonitor/Intel Power Gadget 采集进程；常见安装位置与命令未发现 PowerLog。',
        '该检查不表示硬件永远无法测量，也不是对所有 Windows 能耗工具的完整发现。', '',
        'GPU 可以返回 `nvidia-smi power.draw` 快照；它没有被积分或用于任何能耗目标。',
        'GPU 板卡功率不覆盖此处的 CPU Neo4j 查询；字段时间平均口径也不当作瞬时功率保证。',
        '说明依据：[NVIDIA 官方功率字段](https://docs.nvidia.com/deploy/nvidia-smi/index.html)。', '',
        '## 已实现的采集口径', '',
        '只读取 CPU package 顶层域的 `energy_uj` 和 `max_energy_range_uj`，不写入或重置硬件计数器。',
        'package 下 core/uncore 子域不与父域相加，避免重复计入。多 package 则逐域求差后相加。',
        '单位转换、回绕模数来自 [Linux 内核 powercap 文档](https://www.kernel.org/doc/html/latest/power/powercap/powercap.html)。',
        '采样线程记录原始计数器。采样间隔若可能容纳多次回绕、跳变超出用户配置的功率上界、读数失败或全窗口无进展，则结果 invalid。',
        '`max-package-watts` 默认 500 W 是每个 package 的歧义检查上界假设，不是测量功率；不用于生成焦耳数。',
        '实际使用者应确认上界足够保守并缩短采样间隔；没有外部重置是前提，部分重置无法与回绕可靠区分。',
        '硬件适配器仅通过跨平台计数器夹具测试；本机无真实 RAPL，因此未建立 Linux 真实硬件验证证据。', '',
        '读数包含 package 上 Python、数据库、其他进程和采样线程，不能称数据库进程专属能耗或整机能耗。',
        '流前后各测空闲窗口，用两者平均功率做描述性基线扣除，负值保留；背景负载变化可能使扣除失真。',
        '本机因为计数器缺失，没有执行虚假的空闲能耗测量，所有能耗列保持空白/null。',
        'Python CPU 时间以 `process_time()` 单列，包含该进程所有线程；不是数据库 CPU 时间，不能换算焦耳。', '',
        '## 真实查询路径验证', '',
        f"{meta['timed_requests']} 次 Neo4j 请求：3 个运行样本种子 × exact/cached/amortized 三种模式 × 30 次。",
        '既有 5 万节点图、五个谓词和混合档位；全部 raw COUNT 与同种子 NumPy 参考一致。',
        '模式执行顺序随机化，保留实际延迟构建；原图导入、初始校准/计时、预热查询未计入在线查询成本。',
        '能耗窗口范围比请求耗时求和更大：包括 Python 参考校验与采样器；CSV/报告写入位于窗口外。', '',
        '| 模式 | 原有请求全成本 ms/请求 | 采集窗口均值秒 | Python CPU 秒/流 | 能耗状态 | 焦耳/请求 |',
        '|---|---:|---:|---:|---|---|']
    for mode in ('exact', 'cached', 'amortized'):
        selected = [r for r in rows if r['mode']==mode]
        query = next(r for r in queries if r['mode']==mode)
        states = ', '.join(sorted({r['status'] for r in selected}))
        energies = [float(r['joules_per_request']) for r in selected if r['joules_per_request']]
        lines.append(f"| {mode} | {float(query['online_ms_per_request']):.2f} | {mean(float(r['window_seconds']) for r in selected):.3f} | {mean(float(r['python_cpu_seconds']) for r in selected):.3f} | {states} | {mean(energies):.6f} |" if energies else
                     f"| {mode} | {float(query['online_ms_per_request']):.2f} | {mean(float(r['window_seconds']) for r in selected):.3f} | {mean(float(r['python_cpu_seconds']) for r in selected):.3f} | {states} | unavailable |")
    lines += ['', 'exact 与 amortized 在短流都跳过抽样构建，计时差异不代表算法加速；本轮目的为验证采集路径。',
        '缺失能耗、GPU 范围、零/非有限值或无效计数器不能通过能耗目标检查；本版所有能耗目标保持禁用。', '',
        '## 验证', '',
        '65 项测试全部通过，包含 5 项真实 Neo4j 集成测试；另完成 30 次内存采集路径烟雾请求。',
        '无 NumPy/Neo4j 的新安装包通过基础示例及探测命令检查；GitHub CI 添加能耗探测/内存路径。', '',
        '## 后续验收', '',
        '1. 在有可读 powercap 的同机 Linux 环境实测，或增加经过确认的 Windows/外部功率仪适配器。',
        '2. 明确硬件/测量范围、采样分辨率、空闲基线、后台负载、重复与准备成本；获取可追溯的焦耳数据。',
        '3. 再建立共享预算/工作负载的精确、固定档、穷举、NSGA-II、自适应能耗比较，随后才能启用能耗目标。',
        '4. 此等待期间继续独立的标准工作负载语义/覆盖与统一报告工作；不以 unavailable 伪装能耗里程碑完成。',
        'Windows Intel PCM 官方步骤涉及其硬件驱动/运行前提，本版没有安装驱动或更改系统配置；',
        '参考：[Intel PCM Windows 说明](https://github.com/intel/pcm/blob/master/doc/WINDOWS_HOWTO.md)。', '',
        '## 复现与文件', '', '```powershell',
        'python -m graph_mf energy-probe --output results/local/new-energy-probe.json',
        'python -m graph_mf --backend memory energy-benchmark --epochs 2 --requests 5 --output results/local/new-energy-smoke',
        'python -m graph_mf --backend neo4j energy-benchmark --epochs 3 --requests 30 --output results/local/new-energy-live',
        'python scripts/report_energy_v010.py --live results/local/new-energy-live', '```', '',
        f'[可用性](../{args.live.as_posix()}/energy-capability.json) · [逐流记录](../{args.live.as_posix()}/energy-streams.csv) · [范围与限制](../{args.live.as_posix()}/metadata.json)。',
        '每条流的 energy-window-*.json 保留原始计数器、空闲与工作窗口；本机原始样本为空，原因可核对。', '']
    Path('docs/v010-energy-instrumentation.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(report='docs/v010-energy-instrumentation.md', requests=meta['timed_requests'], energy_measured=meta['energy_measured'])))


if __name__ == '__main__':
    main()
