"""Audit unique held-out parameter coverage and matched epoch costs."""
import argparse
import csv
import json
from pathlib import Path
from graph_mf.synthetic import numpy


def summarize(root):
    meta=json.loads((root/'metadata.json').read_text())
    if meta['status']!='completed' or not meta['all_raw_counts_match']:raise ValueError('Validated complete evidence required')
    parameters=meta['test_parameters']
    keys=[(q['country'],q['lower'],q['upper']) for group in parameters for q in group]
    if len(set(keys))!=len(keys):raise ValueError('Repeated held-out parameters')
    source=meta
    if 'source' in meta:source=json.loads((Path(meta['source'])/'metadata.json').read_text())
    fitting={(q['country'],q['lower'],q['upper']) for q in source['train_parameters']}
    if set(keys)&fitting:raise ValueError('Training/test parameter overlap')
    if 'source' in meta:
        pilot={(q['country'],q['lower'],q['upper']) for group in source['test_parameters'] for q in group}
        if set(keys)&pilot:raise ValueError('Pilot/confirmation overlap')
    with (root/'requests.csv').open(newline='') as f:requests=list(csv.DictReader(f))
    with (root/'streams.csv').open(newline='') as f:streams=list(csv.DictReader(f))
    with (root/'builds.csv').open(newline='') as f:builds=list(csv.DictReader(f))
    epochs=len(meta['test_seeds']);modes=sorted({r['mode'] for r in streams})
    keyed={(int(r['epoch']),r['mode']):r for r in streams}
    if len(keyed)!=epochs*len(modes) or len(keyed)!=len(streams):raise ValueError('Incomplete/duplicate streams')
    if len({(r['epoch'],r['mode'],r['request'],r['kind']) for r in requests})!=len(requests):raise ValueError('Duplicate COUNT records')
    if sorted(int(r['epoch']) for r in builds)!=list(range(epochs)):raise ValueError('Incomplete builds')
    np=numpy();resamples=np.random.default_rng(32000).integers(0,epochs,size=(10000,epochs))
    def costs(mode):return np.array([float(keyed[e,mode]['online_ms'])+float(keyed[e,mode].get('init_ms',0)) for e in range(epochs)])
    exact=costs('exact');output=[]
    for mode in modes:
        selected=[r for r in requests if r['mode']==mode]
        if len(selected)!=2*len(keys):raise ValueError('Incomplete COUNT coverage')
        for epoch,queries in enumerate(parameters):
            actual=[r for r in selected if int(r['epoch'])==epoch]
            if len(actual)!=2*len(queries):raise ValueError('Incomplete epoch')
            for row in actual:
                query=queries[int(row['request'])]
                if (row['country'],int(row['lower']),int(row['upper']))!=(query['country'],query['lower'],query['upper']):raise ValueError('Parameter mismatch')
            if sum(r['within_budget']=='False' for r in actual)!=int(keyed[epoch,mode]['failures']):raise ValueError('Error totals disagree')
        measured=costs(mode);boot=exact[resamples].sum(axis=1)/measured[resamples].sum(axis=1)
        startup=0 if mode=='exact' else meta['training_ms']+sum(float(r['build_ms']) for r in builds)
        output.append(dict(mode=mode,unique_parameters=len(keys),components=len(selected),
            online_ratio=float(exact.sum()/measured.sum()),bootstrap_low=float(np.quantile(boot,.025)),
            bootstrap_high=float(np.quantile(boot,.975)),phase_ratio=float(exact.sum()/(measured.sum()+startup)),
            failures=sum(r['within_budget']=='False' for r in selected),
            approximate=sum(float(r['fidelity'])<1 for r in selected),
            max_error=max(float(r['error']) for r in selected),startup_ms=startup))
    (root/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    return meta,output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--confirmation',type=Path,required=True)
    a=p.parse_args()
    population=json.loads((a.source/'uniform'/'metadata.json').read_text())
    lines=['# v0.18 — Topology and held-out parameter validation','',
        f"{population['nodes']:,} nodes and the same {population['edges']:,} directed edge records per graph. Country attributes",
        'are identical; connectivity is uniform, 85% within ID-block communities, or',
        'weighted toward hub IDs. Parallel edges remain separate; self loops are excluded.',
        'The experiment refits for each graph; it is not zero-shot cross-topology transfer.',
        '',
        'Queries count nodes or edges with both endpoints in a country and a half-open',
        'node-ID interval. Training uses eight fixed predicates, four fitting rank seeds',
        'and twenty independent calibration seeds. Each test parameter tuple is unique',
        'and absent from training. Node/edge pairs and methods share parameters intentionally.',
        'Fidelity selection transfers empirical family calibration to unseen intervals;',
        'the finite training predicate set does not guarantee accuracy on all intervals.',
        '',
        'The cost guard uses only fitting-time forecasts: choose the cheapest feasible',
        'tier if its predicted cost is at least 10% below exact, otherwise execute exact.',
        'This rule was fixed after the pilot and before six new confirmation ranks and',
        'new query parameters. Pilot outcomes are not used as per-query oracle answers.',
        '',
        '## Live results','',
        '| Trial | Topology | Policy | Online ratio (paired 95% bootstrap) | Failures | Approximate | Phase ratio with training/builds |',
        '|---|---|---|---:|---:|---:|---:|']
    for trial,source in [('pilot',a.source),('confirmation',a.confirmation)]:
        for topology in ('uniform','community','hub'):
            meta,rows=summarize(source/topology)
            if not meta['performance_measured']:raise ValueError('Live evidence required')
            for row in rows:
                if row['mode']=='exact':continue
                lines.append(f"| {trial} | {topology} | {row['mode']} | {row['online_ratio']:.2f} [{row['bootstrap_low']:.2f}, {row['bootstrap_high']:.2f}] | {row['failures']}/{row['components']} | {row['approximate']}/{row['components']} | {row['phase_ratio']:.2f} |")
    lines+=['','## Measurement boundaries','',
        'Each trial has six paired rank epochs, forty distinct parameter pairs per epoch',
        'and changing 5%/10%/20% error budgets. Bootstrap resamples epochs, not correlated',
        'node/edge answers. These are descriptive host-local intervals on a warm server.',
        'Training includes rank construction and raw-oracle checks; all discarded runtime',
        'probes and exact fallbacks are charged online. Import is measured separately and',
        'excluded from the phase ratio; profile loading/test-oracle checking are excluded.',
        'The pilot did not separately time controller initialization; confirmation does.',
        'Previously measured training is charged once to each non-exact confirmation policy.',
        'These short streams do not establish a startup-inclusive performance improvement.',
        'No observed budget failures would still not establish a production guarantee.',
        'The confirmation guard and baseline chose identical tiers and probe counts;',
        'timing differences therefore do not establish a causal cost-guard benefit.',
        '',
        'The v0.17 1.34× amortization result remains a different known-predicate long-stream',
        'experiment. Do not transfer that number to this parameter family or every topology.',
        'Custom interval COUNTs are not LDBC operations. See the separate',
        '[LDBC adaptive acceptance plan](ldbc-adaptive-acceptance.md) for remaining work.',
        '', '## Reproduction','', '```powershell',
        'python scripts/benchmark_parameter_transfer.py --backend neo4j --nodes 20000 --epochs 6 --queries 40 --output results/local/new-parameter-pilot',
        'python scripts/benchmark_parameter_cost_guard.py --backend neo4j --source results/local/new-parameter-pilot --epochs 6 --queries 40 --output results/local/new-parameter-confirmation',
        f'python scripts/report_parameter_transfer.py --source {a.source.as_posix()} --confirmation {a.confirmation.as_posix()}',
        '```','']
    Path('docs/v018-parameter-transfer.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines))


if __name__=='__main__':main()
