"""Summarize held-out accuracy independently from isolated live timing."""
import argparse
import csv
import json
from pathlib import Path

from report_dlss_ablation import summarize


def plot_evidence(accuracy_rows, budget_rows, meta, joint, exact):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(13,4.4))
    selected=[(m,r) for m,rows in accuracy_rows for r in rows if r['mode']!='exact']
    labels=[f"{m['nodes']//1000}k\n{'Joint' if r['mode'].startswith('joint') else 'Marginal'}" for m,r in selected]
    axes[0].bar(labels,[r['failures'] for m,r in selected],color=['#b47a45','#257c83']*2)
    for i,(m,r) in enumerate(selected):axes[0].text(i,r['failures']+.12,str(r['failures']),ha='center')
    axes[0].set(title='Held-out budget violations',ylabel='Failures / 2,400 answers per policy')
    for nodes in sorted({r['nodes'] for r in budget_rows}):
        rows=[r for r in budget_rows if r['nodes']==nodes]
        axes[1].plot([r['budget']*100 for r in rows],[r['ratio'] for r in rows],marker='o',label=f'{nodes//1000}k nodes')
    axes[1].axhline(1,color='gray',ls='--',lw=1)
    axes[1].set(title='Joint policy: online trade-off',xlabel='Requested error budget (%)',ylabel='Exact / joint online cost')
    axes[1].legend()
    online=[exact['mean_stream_ms']*meta['epochs']/1000,joint['mean_stream_ms']*meta['epochs']/1000]
    axes[2].bar(['Exact','Joint'],online,color='#257c83',label='Online + session init')
    axes[2].bar(['Exact','Joint'],[0,joint['startup_ms']/1000],bottom=online,color='#b47a45',label='Training/refit/builds')
    axes[2].set(title=f"{meta['epochs']*meta['requests']:,} pairs, 20% budget",ylabel='Recorded phase sum (seconds)')
    axes[2].legend(fontsize=8)
    fig.suptitle('Static known-predicate COUNT experiments — v0.17',fontsize=13)
    fig.text(.5,.01,'100 accuracy epochs per size; warm-server timing. Phase sums exclude graph import and test-oracle checks.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.04,1,.92))
    path=Path('docs/figures/v017-evidence.png');path.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(path,dpi=180);plt.close(fig)


def accuracy(source):
    meta=json.loads((source/'metadata.json').read_text())
    if meta['status']!='completed' or not meta['all_raw_counts_match']:
        raise ValueError('Completed raw-validated evidence required')
    with (source/'requests.csv').open(newline='') as f:
        requests=list(csv.DictReader(f))
    output=[]
    for mode in meta['modes']:
        rows=[r for r in requests if r['mode']==mode]
        if len(rows)!=2*meta['epochs']*meta['requests']:
            raise ValueError('Incomplete accuracy coverage')
        keys=[(r['epoch'],r['request'],r['kind']) for r in rows]
        if len(set(keys))!=len(keys):raise ValueError('Duplicate observations')
        failed=[r for r in rows if r['within_budget']=='False']
        output.append(dict(mode=mode,components=len(rows),failures=len(failed),
            independent_epochs=meta['epochs'],failed_epochs=len({r['epoch'] for r in failed}),
            unique_realizations=len({(r['epoch'],r['country'],r['kind'],r['budget']) for r in rows}),
            max_error=max(float(r['error']) for r in rows),
            approximate_components=sum(float(r['fidelity'])<1 for r in rows)))
    (source/'accuracy-summary.json').write_text(json.dumps(output,indent=2)+'\n')
    return meta,output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--accuracy',type=Path,nargs='+',required=True)
    p.add_argument('--live',type=Path,nargs='+',required=True)
    p.add_argument('--long',type=Path)
    a=p.parse_args()
    accuracy_rows=[];budget_rows=[]
    lines=['# v0.17 — Joint calibration and independent reliability checks','',
        '## Fixed experiment design','',
        'Compare the unchanged marginal `no_history` policy with `joint_no_history` and exact.',
        'Joint calibration normalizes errors using scales computed only from fitting seeds;',
        'one calibration score is the maximum over both known countries, both COUNT kinds',
        'and every fidelity. Its 90% empirical quantile is computed from 20 calibration seeds.',
        'The controller checks current sample size, probes afresh and falls back to exact',
        'for unknown predicates. No held-out test seed tunes the policy or thresholds.',
        'All original training measurements are reused and charged; joint fitting cost is added.',
        '',
        'For each fixed component/tier j, fitting defines a residual scale s_j using',
        'relative error divided by sqrt(reference_sample_count / current_sample_count).',
        'Each calibration epoch supplies a single maximum normalized residual over j',
        'and countries. The 19th ordered maximum of 20 epochs supplies multiplier Q.',
        'Runtime bound_j = Q * s_j * sqrt(reference_count_j / observed_count_j).',
        'If all these bounds cover a particular rank realization, choosing any accepted',
        'tier from this fixed set preserves its requested budget. The empirical quantile',
        'does not establish that condition on every future realization or changed graph.',
        '',
        'Accuracy checks use 100 fresh rank epochs (22000–22099) per size and changing',
        '5%/10%/20% budgets. Live timing uses six separate epochs (23000–23005),',
        'randomized paired order and a warm server. Memory checks supply accuracy evidence only.',
        'Repeated requests share ranks; the epoch, not each repeated request, is the independent unit.',
        '', '## Held-out accuracy','',
        '| Nodes | Policy | Budget failures/components | Epochs with any failure | Approximate components | Max error |',
        '|---:|---|---:|---:|---:|---:|']
    for source in a.accuracy:
        meta,rows=accuracy(source)
        accuracy_rows.append((meta,rows))
        for row in rows:
            lines.append(f"| {meta['nodes']:,} | {row['mode']} | {row['failures']}/{row['components']} | {row['failed_epochs']}/{row['independent_epochs']} | {row['approximate_components']} | {100*row['max_error']:.2f}% |")
    lines+=['','## Isolated live timing','',
        '| Nodes | Policy | Online ratio vs exact (95% paired bootstrap) | Budget failures | Recorded phase ratio including startup |',
        '|---:|---|---:|---:|---:|']
    for source in a.live:
        meta,rows=summarize(source)
        if not meta['performance_measured']:raise ValueError('Live timing required')
        for row in rows:
            lines.append(f"| {meta['nodes']:,} | {row['mode']} | {row['online_speedup']:.2f} [{row['paired_bootstrap_low']:.2f}, {row['paired_bootstrap_high']:.2f}] | {row['failures']}/{row['components']} | {row['phase_total_speedup']:.2f} |")
    lines+=['','## Joint policy by requested budget','',
        '| Nodes | Error budget | Online ratio vs exact | Failures/components | Maximum error |',
        '|---:|---:|---:|---:|---:|']
    for source in a.live:
        meta=json.loads((source/'metadata.json').read_text())
        with (source/'requests.csv').open(newline='') as f:requests=list(csv.DictReader(f))
        for budget in sorted({r['budget'] for r in requests},key=float):
            selected=[r for r in requests if r['budget']==budget and r['mode']=='joint_no_history']
            exact=[r for r in requests if r['budget']==budget and r['mode']=='exact']
            if len(selected)!=len(exact):raise ValueError('Unmatched budget coverage')
            ratio=sum(float(r['online_ms']) for r in exact)/sum(float(r['online_ms']) for r in selected)
            failures=sum(r['within_budget']=='False' for r in selected)
            budget_rows.append(dict(nodes=meta['nodes'],budget=float(budget),ratio=ratio))
            lines.append(f"| {meta['nodes']:,} | {100*float(budget):.0f}% | {ratio:.2f} | {failures}/{len(selected)} | {100*max(float(r['error']) for r in selected):.2f}% |")
    lines+=['','Budget-specific rows sum matched online request measurements, excluding session',
        'construction and training/builds. They are descriptive subdivisions of the same',
        'six live epochs, not additional independent experiments. Strict budgets may be slower.',
        'Use exact when required precision eliminates worthwhile sampling, and reserve',
        'approximation for workloads that explicitly accept measured precision loss.']
    if a.long:
        meta,rows=summarize(a.long)
        joint=next(r for r in rows if r['mode']=='joint_no_history')
        exact=next(r for r in rows if r['mode']=='exact')
        total=joint['mean_stream_ms']*meta['epochs']+joint['startup_ms']
        plot_evidence(accuracy_rows,budget_rows,meta,joint,exact)
        lines+=['','## Prespecified longer-stream cost check','',
            '![Accuracy, online trade-off and recorded phase costs](figures/v017-evidence.png)','',
            f"{meta['nodes']:,} nodes, {meta['epochs']*meta['requests']:,} request pairs, "
            f"{meta['epochs']} new rank epochs ({meta['seeds'][0]}–{meta['seeds'][-1]}), fixed 20% budget.",
            'Only exact and the unchanged joint policy are compared; no thresholds are retuned.',
            'The 20% budget and 6,000-pair horizon were fixed after the short-stream pilot',
            'and before evaluating these three new ranks; this is a selected-use-case confirmation.',
            f"Exact online + session construction: {exact['mean_stream_ms']*meta['epochs']/1000:.2f} s.",
            f"Joint online + session construction: {joint['mean_stream_ms']*meta['epochs']/1000:.2f} s; "
            f"recorded training/refit/sample builds: {joint['startup_ms']/1000:.2f} s.",
            f"Recorded joint phase sum: {total/1000:.2f} s; baseline/phase-sum ratio "
            f"**{joint['phase_total_speedup']:.2f}×** (online ratio {joint['online_speedup']:.2f}×).",
            f"Budget violations: {joint['failures']}/{joint['components']}; maximum observed "
            f"error: {100*joint['max_error']:.2f}%.",
            'Repeated requests share only three rank realizations. This is a cost-amortization',
            'check on known static predicates, not additional large-scale statistical validation.',
            'Original training was measured previously; the sum of recorded phases is not one',
            'continuous lifecycle wall-clock measurement. Graph import and test-oracle checks',
            'are excluded; the original training workflow includes its internal validation.',
            'All discarded probes, exact fallbacks and session initialization are charged.']
    lines+=['','## Interpretation boundaries','',
        'Report observed failures even after joint calibration. Neither zero observed failures',
        'nor an empirical quantile establishes an unconditional per-request guarantee.',
        'Both graph sizes share the same topology generator and FR/DE predicates; profiles',
        'are fit separately. Unseen topology, changed graph data and parameterized SNB queries',
        'are outside this experiment. More conservative calibration can erase speed benefits.',
        'Six timing blocks support a descriptive host-local comparison, not general significance.',
        'The short streams charge all recorded training and sample builds but do not amortize them.',
        'Graph import, profile reading and test-oracle validation are excluded. The earlier 1.78×',
        'long-stream result remains scoped to v0.15, not automatically transferred to this policy.',
        '', '## Reproduction','', '```powershell']
    for source in a.live:
        meta=json.loads((source/'metadata.json').read_text())
        lines.append(f"python scripts/benchmark_dlss_ablation.py --backend neo4j --source {meta['source']} --epochs 6 --requests 60 --seed-start 23000 --joint-calibration --output results/local/new-joint-{meta['nodes']}")
    for source in a.accuracy:
        meta=json.loads((source/'metadata.json').read_text())
        lines.append(f"python scripts/benchmark_dlss_ablation.py --backend memory --source {meta['source']} --epochs 100 --requests 12 --seed-start 22000 --joint-calibration --output results/local/new-joint-accuracy-{meta['nodes']}")
    if a.long:
        meta=json.loads((a.long/'metadata.json').read_text())
        lines.append(f"python scripts/benchmark_dlss_ablation.py --backend neo4j --source {meta['source']} --epochs 3 --requests 2000 --seed-start 24000 --joint-calibration --modes exact joint_no_history --budgets 0.2 --output results/local/new-joint-long")
    lines.append('python scripts/report_joint_calibration.py --accuracy '+
        ' '.join(x.as_posix() for x in a.accuracy)+' --live '+
        ' '.join(x.as_posix() for x in a.live)+(' --long '+a.long.as_posix() if a.long else ''))
    lines+=['```','']
    Path('docs/v017-joint-calibration.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines))


if __name__=='__main__':main()
