"""Paired ablations under changing error budgets, with whole-epoch statistics."""
import argparse
import json
import logging
import random
from pathlib import Path
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.incremental_sampling import HistorySampler
from graph_mf.reusable import ReusableSample
from graph_mf.synthetic import generate_graph,SyntheticMemory,SyntheticNeo4j


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['memory','neo4j'],default='memory')
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=6)
    p.add_argument('--requests',type=int,default=60)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); logging.getLogger('neo4j').setLevel(logging.ERROR)
    source=json.loads((a.source/'metadata.json').read_text());profile=json.loads((a.source/'profile.json').read_text())
    if source['status']!='completed' or a.output.exists() or a.epochs<3 or a.requests<12:
        raise ValueError('Completed source, fresh output and sufficient repeated streams required')
    graph=generate_graph(source['nodes']); reference=SyntheticMemory(graph)
    connection=Neo4jBackend() if a.backend=='neo4j' else None
    backend=SyntheticNeo4j(graph,connection) if connection else SyntheticMemory(graph)
    sample=ReusableSample(backend);a.output.mkdir(parents=True)
    variants={'full':{},'no_history':dict(use_history=False),
              'no_incremental':dict(use_incremental=False),
              'cold_incremental':dict(start_policy='cold',use_history=False)}
    rows=[];streams=[];probes=[];builds=[]
    meta=dict(status='running',backend=a.backend,nodes=source['nodes'],graph_sha256=graph.fingerprint,
        source=a.source.as_posix(),epochs=a.epochs,requests=a.requests,modes=['exact',*variants],
        seeds=list(range(21000,21000+a.epochs)),budgets=[.2,.05,.1,.2,.05,.2],
        scope='static graph, changing budgets; seed epoch independent, no result cache',
        training_ms=source['training_ms'],performance_measured=a.backend=='neo4j')
    def checkpoint(): (a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    checkpoint()
    try:
        if connection: backend.validate_import()
        for epoch,seed in enumerate(meta['seeds']):
            reference.prepare(seed); built=sample.build(seed,refresh=True)
            builds.append(dict(epoch=epoch,build_ms=built['build_ms']))
            order=list(meta['modes']);random.Random(seed).shuffle(order)
            rng=random.Random(seed+1000)
            work=[(rng.choice(profile['countries']),meta['budgets'][min(5,i*6//a.requests)]) for i in range(a.requests)]
            for mode in order:
                start=perf_counter()
                controller=HistorySampler(profile,sample,**variants[mode]) if mode!='exact' else None
                init_ms=1000*(perf_counter()-start)
                active=[]
                for request,(country,budget) in enumerate(work):
                    for kind in ('node','edge'):
                        start=perf_counter()
                        if mode=='exact':
                            raw=backend.count_component(country,1,kind)
                            result=dict(estimate=raw['count'],raw_count=raw['count'],fidelity=1,attempts=1,
                                        query_ms=raw['query_ms'],trace=[],bound=0.,fallback=False)
                        else: result=controller.request(country,kind,budget)
                        elapsed=1000*(perf_counter()-start)
                        truth=reference.count_component(country,1,kind)['count']
                        for step,probe in enumerate(result.pop('trace')):
                            if probe['raw_count']!=reference.count_component(country,probe['fidelity'],kind)['count']:
                                raise RuntimeError('Ablation probe COUNT mismatch')
                            probes.append(dict(epoch=epoch,mode=mode,request=request,country=country,kind=kind,
                                               budget=budget,step=step,**probe))
                        if result['raw_count']!=reference.count_component(country,result['fidelity'],kind)['count']:
                            raise RuntimeError('Ablation final COUNT mismatch')
                        error=abs(result['estimate']-truth)/max(truth,1)
                        row=dict(epoch=epoch,mode=mode,request=request,country=country,kind=kind,budget=budget,
                                 online_ms=elapsed,error=error,within_budget=error<=budget,**result)
                        active.append(row);rows.append(row)
                streams.append(dict(epoch=epoch,mode=mode,init_ms=init_ms,components=len(active),
                    online_ms=sum(r['online_ms'] for r in active),
                    failures=sum(not r['within_budget'] for r in active),calls=sum(r['attempts'] for r in active)))
                write_csv(a.output/'requests.csv',rows);write_csv(a.output/'streams.csv',streams)
                write_csv(a.output/'builds.csv',builds)
                if probes:write_csv(a.output/'probes.csv',probes)
                print(epoch,mode,'verified',flush=True)
        meta['status']='completed';meta['all_raw_counts_match']=True;checkpoint()
    except BaseException:
        meta['status']='failed_or_interrupted';checkpoint();raise
    finally:
        if connection:connection.close()


if __name__=='__main__':main()
