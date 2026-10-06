"""Report semantic coverage and sparse COUNT failures on the pinned SNB micro-fixture."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from graph_mf.benchmark import write_csv
from graph_mf.snb import COMMIT, UPSTREAM


def read(path):
    with path.open(encoding='utf-8',newline='') as handle:
        return list(csv.DictReader(handle))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',type=Path,default=Path('results/neo4j/snb-v011'))
    args = parser.parse_args()
    meta = json.loads((args.live/'metadata.json').read_text(encoding='utf-8'))
    if meta['status']!='completed' or meta['backend']!='neo4j' or not meta['all_raw_counts_match'] or not meta['is3_all_ordered_tuples_match']:
        raise ValueError('Completed validated Neo4j semantic run required')
    summary, raw = read(args.live/'summary.csv'), read(args.live/'raw-results.csv')
    groups = [('0',lambda d:d==0),('1–4',lambda d:1<=d<=4),('5–15',lambda d:5<=d<=15),('16+',lambda d:d>=16)]
    strata = []
    for name,accept in groups:
        for f in (.1,.25,.5,.75,1.):
            selected = [r for r in raw if r['kind']=='friends_count' and float(r['requested_fidelity'])==f and accept(int(r['degree']))]
            if selected:
                strata.append(dict(degree_group=name,fidelity=f,requests=len(selected),
                    mean_error=mean(float(r['relative_error']) for r in selected),
                    max_error=max(float(r['relative_error']) for r in selected),
                    empty_sample_positive_truth=sum(int(r['raw_count'])==0 and int(r['exact'])>0 for r in selected)))
    write_csv(args.live/'degree-strata.csv',strata)
    lines = ['# v0.11：官方微型数据与查询语义覆盖', '',
        '**本轮为 SNB v1 微型数据投影上的 IS3 语义核对，加上两个自定义 COUNT。不是完整 LDBC、SF1 或合规性能基准。**', '',
        '## 数据与导入', '',
        f'使用 [官方参考仓库]({UPSTREAM}/tree/{COMMIT}/cypher/test-data/vanilla/dynamic) 的固定提交 `{COMMIT}`。',
        f"实际 {meta['nodes']} 个 Person、{meta['edges']} 条 KNOWS；保留 Person ID/名字及 friendship creationDate。",
        '两个 CSV 下载前后用硬编码 SHA-256 核对，原始数据留在 work/datasets，未放入 GitHub。',
        'Apache-2.0 LICENSE/NOTICE 与来源说明保存到 third_party/ldbc；下载器同时保留在数据目录。',
        '整数 ID 保持 64 位数值；官方 LongDateFormatter 时间戳保持 UTC 毫秒，不将毫秒误当秒或 ISO 文本。',
        'KNOWS CSV 的两个端点列同名，使用位置解析；拒绝未知端点、重复无向边和自环。',
        '数据库投影使用 MFSNBPerson/MFKNOWS 和指纹命名空间，图中原有各版数据保留。',
        '导入两次后完整核对人物属性与边/时间戳。抽样一次事务提交全部 rank 与 generation；旧连接在下一请求检查替换/重导入。',
        '状态检查与 COUNT 为分开的请求，不支持并发写入竞态，也不识别任意外部属性修改；实验使用静态单写者。', '',
        '## 查询与估计器覆盖矩阵', '',
        '| 查询 | 性质 | 结果语义 | 抽样支持 |',
        '|---|---|---|---|',
        '| IS3 好友列表 | 官方选定读语义 | 好友 ID/名字/姓氏/关系创建时间，按时间降序、数值 ID 升序 | 完整有序元组始终精确；低档请求拒绝 |',
        '| friends_count | 自定义 IS3 派生计数 | 固定起点的一跳好友数量 | 仅好友均匀抽样，raw_count/f；尚无校准预算保证 |',
        '| reach_2_count | 自定义多跳计数 | 距离 1 或 2 的不同 Person，排除起点、路径去重 | 低档请求回退精确；不得直接用 1/f² |',
        '| 其余复杂/短读、更新、完整驱动 | 未实现 | 不声称覆盖 | 未实现 |', '',
        f'IS3 字段与排序依据：[固定版本官方 Cypher]({UPSTREAM}/blob/{COMMIT}/cypher/queries/interactive-short-3.cypher)。',
        'Python 邻接表实现为独立核对路径；它与我们的 Cypher 都基于同一字段解释，未执行官方 Java 驱动验证。',
        '一跳起点不抽样，好友包含概率为 f，因此 1/f。不同两跳目标有不同数量/重叠的路径，包含概率不能统一写成 f²。', '',
        '## 真实 Neo4j 结果', '',
        f"共 {meta['timed_requests']} 次业务查询：所有 {meta['nodes']} 个 Person 的完整 IS3 输出，加上 32 个度分位起点 × 3 个独立 rank 种子 × 7 个 COUNT 配置。",
        f"数据含 {meta['exact_zero_degree_persons']} 个零度 Person，最大度 {meta['max_degree']}。",
        'IS3 完整元组逐一匹配；所有原始 COUNT 与同种子内存参考一致。96 次低档多跳请求均实际执行精确查询。',
        '查询耗时包含返回分发和近似状态核对，不含导入或 sample-builds.csv 中的真实抽样构建。',
        '固定配置执行顺序、微型图、共享桌面实例，不具备代表性的性能/吞吐比较条件；不宣称加速。', '',
        '| 类型 | 请求档位 | 平均相对误差 | 最大相对误差 | 非零真值但空样本次数 | 精确回退次数 | 查询均值 ms |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"| {r['kind']} | {r['requested_fidelity']} | {100*float(r['mean_error']):.2f}% | {100*float(r['max_error']):.2f}% | {r['zero_sample_nonzero_truth']} | {r['fallbacks']} | {float(r['mean_query_ms']):.2f} |")
    lines += ['', '## 稀疏度揭示的缺口', '',
        '| 起点度 | Fidelity | 请求数 | 平均相对误差 | 空样本且真值非零 |',
        '|---|---:|---:|---:|---:|']
    for r in strata:
        if r['fidelity'] in (.1,.5):
            lines.append(f"| {r['degree_group']} | {r['fidelity']} | {r['requests']} | {100*r['mean_error']:.2f}% | {r['empty_sample_positive_truth']} |")
    lines += ['', '均匀抽样不保证单次结果准确；低度 Person 的零样本不能当作真实零好友。原始错误保留，未由事后调参消除。',
        '本轮均值为度分位起点集合的描述，不代表全部 Person 的均匀分布；零度起点误差为 0，故另按度分层。',
        '所有起点共享一个 rank 向量；独立单位是样本种子，不是 96 次请求。只有三个种子，不能据此给出正式覆盖保证。',
        '原有 country COUNT 校准、门控和 NSGA-II 不能直接迁移到这个起点参数化查询；本版尚未集成。',
        '下一步需针对一跳查询单独校准、最低有效样本/零样本回退，并在留出参数/种子上检验预算。', '',
        '## 验证与未完成项', '',
        '72 项测试通过，含 6 项真实 Neo4j 集成测试。测试覆盖日期单位、重复列头、有序元组、路径去重、固定起点和旧样本拒绝。',
        '334 次内存烟雾业务查询通过；不依赖 NumPy 的安装包也能加载官方投影与执行内存查询。',
        '正式规模数据、完整 SNB 读/更新、参数/驱动协议、冷缓存重复、能耗目标与统一研究报告仍待完成。',
        '当前只补齐标准数据与一项读语义的基础验证，不能把本轮计时写成 LDBC 官方性能结果。', '',
        '```powershell',
        'python scripts/download_snb_micro.py --output results/local/snb-input',
        'python -m graph_mf --backend memory snb-benchmark --dataset-path results/local/snb-input --epochs 2 --roots 8 --output results/local/snb-smoke',
        'python -m graph_mf --backend neo4j snb-benchmark --dataset-path results/local/snb-input --epochs 3 --roots 32 --output results/local/snb-live',
        'python scripts/report_snb_v011.py --live results/local/snb-live', '```', '',
        f'[语义核对](../{args.live.as_posix()}/is3-validation.csv) · [逐请求记录](../{args.live.as_posix()}/raw-results.csv) · [稀疏度分层](../{args.live.as_posix()}/degree-strata.csv) · [来源与范围](../{args.live.as_posix()}/metadata.json)。', '']
    Path('docs/v011-snb-semantics.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(report='docs/v011-snb-semantics.md',requests=meta['timed_requests'])))


if __name__ == '__main__':
    main()
