"""Fit/calibrate/test on disjoint sampling epochs, retaining all costs and failures."""
import argparse
import json
import random
from pathlib import Path
from statistics import mean
from time import perf_counter
from graph_mf.adaptive import LEVELS
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.sample_correction import fit_profile, answer, DynamicSampler
from graph_mf.synthetic import generate_graph,SyntheticMemory,SyntheticNeo4j


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['memory','neo4j'],default='memory')
    p.add_argument('--nodes',type=int,default=50000)
    p.add_argument('--runs',type=int,default=10)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.runs<2:
        raise ValueError('Fresh output and multiple test epochs required')
    graph=generate_graph(a.nodes)
    connection=Neo4jBackend() if a.backend=='neo4j' else None
    backend=SyntheticNeo4j(graph,connection) if connection else SyntheticMemory(graph)
    reference=SyntheticMemory(graph)
    a.output.mkdir(parents=True)
    training=[]; results=[]; setup=[]; probes=[]
    meta=dict(status='running',backend=a.backend,nodes=a.nodes,graph_sha256=graph.fingerprint,
              fitting_seeds=list(range(16000,16004)),calibration_seeds=list(range(17000,17020)),
              test_seeds=list(range(18000,18000+a.runs)),fit_countries=['FR','DE'],
              unseen_countries=['ES','IT','NL'],error_budget=.05,fixed_fidelity=.25,
              bounds='empirical per level/component; no selected/joint coverage guarantee',
              production_unknown_scope='exact fallback',performance_measured=a.backend=='neo4j')
    def checkpoint():
        (a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    checkpoint()
    try:
        if connection: backend.validate_import()
        start=perf_counter()
        truth={c:backend.counts(c) for c in meta['fit_countries']}
        for country in truth:
            expected=reference.counts(country)
            for kind in ('node','edge'):
                if truth[country][kind+'_count']!=expected[kind+'_count']:
                    raise RuntimeError('Exact reference mismatch')
        for split in ('fitting','calibration'):
            for seed in meta[split+'_seeds']:
                backend.prepare(seed); reference.prepare(seed)
                for c in meta['fit_countries']:
                    for k in ('node','edge'):
                        for f in LEVELS:
                            observed=backend.count_component(c,f,k)
                            if observed['count']!=reference.count_component(c,f,k)['count']:
                                raise RuntimeError('Raw sampled COUNT mismatch')
                            training.append(dict(split=split,seed=seed,country=c,kind=k,fidelity=f,
                                                 truth=truth[c][k+'_count'],**observed))
                write_csv(a.output/'training.csv',training)
                print(split,seed,'verified',flush=True)
        profile=fit_profile([r for r in training if r['split']=='fitting'],
                            [r for r in training if r['split']=='calibration'],
                            LEVELS,meta['fit_countries'],graph.fingerprint)
        meta['training_ms']=1000*(perf_counter()-start)
        (a.output/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
        modes=['exact','fixed_raw','fixed_corrected','gated_raw','gated_corrected','dynamic_raw','dynamic_corrected']
        samplers={mode:DynamicSampler(profile,backend,corrected=mode.endswith('corrected'))
                  for mode in modes if mode.startswith('dynamic')}
        for seed in meta['test_seeds']:
            start=perf_counter(); backend.prepare(seed); reference.prepare(seed)
            setup.append(dict(seed=seed,sample_preparation_ms=1000*(perf_counter()-start)))
            order=list(modes); random.Random(seed).shuffle(order)
            for mode in order:
                for c in ('FR','DE','ES','IT','NL'):
                    for k in ('node','edge'):
                        probe_trace=[]
                        start=perf_counter()
                        if mode=='exact':
                            measured=backend.count_component(c,1,k)
                            result=dict(estimate=measured['count'],fidelity=1,bound=0,query_ms=measured['query_ms'],
                                        attempts=1,fallback=False,raw_count=measured['count'])
                        elif mode.startswith('dynamic'):
                            result=samplers[mode].request(c,k,.05)
                            probe_trace=result.pop('trace')
                        else:
                            result=answer(profile,backend,c,k,.05,corrected=mode.endswith('corrected'),gated=mode.startswith('gated'))
                        online_ms=1000*(perf_counter()-start)
                        for step,probe in enumerate(probe_trace):
                            if probe['raw_count']!=reference.count_component(c,probe['fidelity'],k)['count']:
                                raise RuntimeError('Dynamic probe raw COUNT mismatch')
                            probes.append(dict(seed=seed,mode=mode,country=c,kind=k,step=step,**probe))
                        f=result['fidelity']; target=reference.count_component(c,1,k)['count']
                        if result['raw_count']!=reference.count_component(c,f,k)['count']:
                            raise RuntimeError('Held-out raw COUNT mismatch')
                        error=abs(result['estimate']-target)/max(target,1)
                        results.append(dict(seed=seed,mode=mode,country=c,kind=k,scope='known' if c in truth else 'unseen',
                                            online_ms=online_ms,relative_error=error,within_budget=error<=.05,**result))
            write_csv(a.output/'requests.csv',results); write_csv(a.output/'setup.csv',setup)
            write_csv(a.output/'probes.csv',probes)
            print('test',seed,'verified',flush=True)
        meta['all_raw_counts_match']=True
        meta['summary']={mode:dict(requests=sum(r['mode']==mode for r in results),
            failures=sum(r['mode']==mode and not r['within_budget'] for r in results),
            mean_error=mean(r['relative_error'] for r in results if r['mode']==mode),
            total_online_ms=sum(r['online_ms'] for r in results if r['mode']==mode),
            approximate_requests=sum(r['mode']==mode and r['fidelity']<1 for r in results)) for mode in modes}
        meta['status']='completed'; checkpoint(); print(json.dumps(meta['summary'],indent=2))
    except BaseException:
        meta['status']='failed_or_interrupted'; checkpoint(); raise
    finally:
        if connection: connection.close()


if __name__=='__main__': main()
