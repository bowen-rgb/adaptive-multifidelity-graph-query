"""Matched speed/error tiers for progressive and history/incremental samplers."""
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
from graph_mf.sample_correction import DynamicSampler
from graph_mf.synthetic import generate_graph,SyntheticMemory,SyntheticNeo4j


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['memory','neo4j'],default='memory')
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--requests',type=int,default=60)
    p.add_argument('--epochs',type=int,default=3)
    p.add_argument('--seed-start',type=int,default=19000)
    p.add_argument('--tiers',nargs='+',choices=['quality','balanced','performance'],default=['quality','balanced','performance'])
    p.add_argument('--modes',nargs='+',choices=['exact','progressive','history_incremental'],default=['exact','progressive','history_incremental'])
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    source=json.loads((a.source/'metadata.json').read_text())
    profile=json.loads((a.source/'profile.json').read_text())
    if (source['status']!='completed' or not source.get('all_raw_counts_match') or a.output.exists()
            or a.epochs<2 or a.requests<4 or len(set(a.modes))!=len(a.modes)
            or len(set(a.tiers))!=len(a.tiers) or a.seed_start<0):
        raise ValueError('Validated source, new output and repeated streams required')
    graph=generate_graph(source['nodes']); reference=SyntheticMemory(graph)
    connection=Neo4jBackend() if a.backend=='neo4j' else None
    backend=SyntheticNeo4j(graph,connection) if connection else SyntheticMemory(graph)
    sample=ReusableSample(backend); a.output.mkdir(parents=True)
    rows=[]; streams=[]; preparations=[]; probes=[]
    meta=dict(status='running',backend=a.backend,source=a.source.as_posix(),epochs=a.epochs,
              requests=a.requests,tiers={k:v for k,v in {'quality':.05,'balanced':.1,'performance':.2}.items() if k in a.tiers},
              modes=a.modes,seed_start=a.seed_start,
              graph_sha256=graph.fingerprint,training_ms=source['training_ms'],
              scope='static known predicates, no result cache; seed epoch is independent unit',
              performance_measured=a.backend=='neo4j')
    def checkpoint(): (a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    checkpoint()
    try:
        if connection: backend.validate_import()
        for epoch in range(a.epochs):
            seed=a.seed_start+epoch; reference.prepare(seed)
            built=sample.build(seed,refresh=True)
            preparations.append(dict(epoch=epoch,seed=seed,build_ms=built['build_ms']))
            for tier,budget in meta['tiers'].items():
                countries=[random.Random(19000+i).choice(profile['countries']) for i in range(a.requests)]
                modes=list(a.modes); random.Random(seed+int(budget*100)).shuffle(modes)
                for mode in modes:
                    session=HistorySampler(profile,sample) if mode=='history_incremental' else DynamicSampler(profile,backend,corrected=False)
                    start=perf_counter(); failures=0; query_count=0
                    for request,country in enumerate(countries):
                        for kind in ('node','edge'):
                            qstart=perf_counter()
                            if mode=='exact':
                                measured=backend.count_component(country,1,kind)
                                result=dict(estimate=measured['count'],fidelity=1,raw_count=measured['count'],
                                            attempts=1,query_ms=measured['query_ms'],trace=[],bound=0.,fallback=False)
                            else: result=session.request(country,kind,budget)
                            online_ms=1000*(perf_counter()-qstart)
                            target=reference.count_component(country,1,kind)['count']
                            if result['raw_count']!=reference.count_component(country,result['fidelity'],kind)['count']:
                                raise RuntimeError('Final raw COUNT mismatch')
                            for step,probe in enumerate(result.pop('trace')):
                                if probe['raw_count']!=reference.count_component(country,probe['fidelity'],kind)['count']:
                                    raise RuntimeError('Incremental/progressive probe mismatch')
                                probes.append(dict(epoch=epoch,tier=tier,mode=mode,request=request,country=country,kind=kind,step=step,**probe))
                            error=abs(result['estimate']-target)/max(target,1); failures+=error>budget
                            query_count+=result['attempts']
                            rows.append(dict(epoch=epoch,tier=tier,budget=budget,mode=mode,request=request,
                                country=country,kind=kind,online_ms=online_ms,error=error,within_budget=error<=budget,**result))
                        if (request+1)%250==0:
                            print(epoch,tier,mode,request+1,'requests',flush=True)
                    active=[r for r in rows if r['epoch']==epoch and r['tier']==tier and r['mode']==mode]
                    streams.append(dict(epoch=epoch,tier=tier,mode=mode,components=len(active),failures=failures,
                        calls=query_count,online_ms=sum(r['online_ms'] for r in active),
                        harness_wall_ms=1000*(perf_counter()-start)))
                    write_csv(a.output/'requests.csv',rows); write_csv(a.output/'streams.csv',streams)
                    write_csv(a.output/'preparation.csv',preparations)
                    if probes: write_csv(a.output/'probes.csv',probes)
                    print(epoch,tier,mode,'verified',flush=True)
        meta['all_raw_counts_match']=True; meta['status']='completed'; checkpoint()
    except BaseException:
        meta['status']='failed_or_interrupted'; checkpoint(); raise
    finally:
        if connection: connection.close()


if __name__=='__main__': main()
