"""Offline independent accuracy stress; database-trained profiles, no speed claims."""
import argparse
import json
from pathlib import Path
import random
from graph_mf.benchmark import write_csv
from graph_mf.parameter_sampling import topology_graph,RangeCounter,RangeQuery,ParameterSampler
from graph_mf.reusable import ReusableSample
from graph_mf.synthetic import SyntheticMemory


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--confirmation',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=100)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or not 3<=a.epochs<=1000:raise ValueError('Fresh output; 3..1000 independent epochs')
    a.output.mkdir(parents=True)
    for topology in ('uniform','community','hub'):
        old=json.loads((a.source/topology/'metadata.json').read_text())
        confirmation=json.loads((a.confirmation/topology/'metadata.json').read_text())
        profile=json.loads((a.source/topology/'profile.json').read_text())
        graph=topology_graph(topology,old['nodes']);backend=SyntheticMemory(graph);sample=ReusableSample(backend)
        if graph.fingerprint!=profile['graph_sha256']:raise ValueError('Graph mismatch')
        seen={(q['country'],q['lower'],q['upper']) for q in old['train_parameters']}
        for metadata in (old,confirmation):
            seen.update((q['country'],q['lower'],q['upper']) for group in metadata['test_parameters'] for q in group)
        rng=random.Random(42000);rows=[];root=a.output/topology;root.mkdir()
        meta=dict(status='running',topology=topology,graph_sha256=graph.fingerprint,
            performance_measured=False,source_profile=str(a.source/topology/'profile.json'),
            rank_seeds=list(range(41000,41000+a.epochs)),parameter_seed=42000,
            scope='offline quality only; per-topology old profile; unique held-out intervals; sparse/unknown exact guard')
        path=root/'metadata.json';path.write_text(json.dumps(meta,indent=2)+'\n')
        try:
            for epoch,seed in enumerate(meta['rank_seeds']):
                sample.build(seed,refresh=True);counter=RangeCounter(backend,sample)
                sampler=ParameterSampler(profile,counter,cost_guard=True)
                for request in range(30):
                    style='standard' if request<20 else 'sparse' if request<25 else 'unknown'
                    while True:
                        width=rng.randint(int(old['nodes']*(.01 if style=='sparse' else .15)),int(old['nodes']*(.10 if style=='sparse' else .75)))
                        lower=rng.randint(0,old['nodes']-width)
                        q=RangeQuery(rng.choice(['IT','ES','NL'] if style=='unknown' else ['FR','DE']),lower,lower+width)
                        key=(q.country,q.lower,q.upper)
                        if key not in seen:break
                    seen.add(key);budget=(.05,.1,.2)[request%3]
                    for kind in ('node','edge'):
                        result=sampler.request(q,kind,budget)
                        truth=counter.count(q,1.,kind)['count']
                        error=abs(result['estimate']-truth)/max(truth,1)
                        if style!='standard' and result['fidelity']!=1:raise RuntimeError('Unsupported query sampled')
                        rows.append(dict(epoch=epoch,seed=seed,request=request,style=style,kind=kind,**q.__dict__,
                            budget=budget,truth=truth,estimate=result['estimate'],fidelity=result['fidelity'],
                            error=error,within_budget=error<=budget,attempts=result['attempts']))
            write_csv(root/'requests.csv',rows)
            summary=[]
            for style in ('standard','sparse','unknown'):
                selected=[r for r in rows if r['style']==style]
                failed={r['seed'] for r in selected if not r['within_budget']}
                summary.append(dict(style=style,answers=len(selected),failures=sum(not r['within_budget'] for r in selected),
                    failed_epochs=len(failed),approximate=sum(r['fidelity']<1 for r in selected),
                    max_error=max(r['error'] for r in selected)))
            (root/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
            meta.update(status='completed',all_parameters_unique_and_disjoint=True);path.write_text(json.dumps(meta,indent=2)+'\n')
            print(topology,summary,flush=True)
        except BaseException:meta['status']='failed_or_interrupted';path.write_text(json.dumps(meta,indent=2)+'\n');raise


if __name__=='__main__':main()
