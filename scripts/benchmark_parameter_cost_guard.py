"""Fresh held-out parameters; cost decisions use previously recorded fitting timings."""
import argparse
import json
import logging
import random
from pathlib import Path
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.parameter_sampling import topology_graph,RangeQuery,RangeCounter,ParameterSampler
from graph_mf.reusable import ReusableSample
from graph_mf.synthetic import SyntheticMemory,SyntheticNeo4j


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--backend',choices=['memory','neo4j'],default='memory')
    p.add_argument('--epochs',type=int,default=6)
    p.add_argument('--queries',type=int,default=40)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();logging.getLogger('neo4j').setLevel(logging.ERROR)
    if a.output.exists() or a.epochs<3 or a.queries<6:raise ValueError('Fresh output and repeated epochs required')
    a.output.mkdir(parents=True)
    connection=Neo4jBackend() if a.backend=='neo4j' else None
    try:
        for topology in ('uniform','community','hub'):
            source=a.source/topology;old=json.loads((source/'metadata.json').read_text())
            if old['status']!='completed' or not old['all_raw_counts_match']:raise ValueError('Validated source required')
            profile=json.loads((source/'profile.json').read_text());graph=topology_graph(topology,old['nodes'])
            reference=SyntheticMemory(graph)
            backend=SyntheticNeo4j(graph,connection) if connection else SyntheticMemory(graph)
            if connection:backend.validate_import()
            sample=ReusableSample(backend);oracle_sample=ReusableSample(reference)
            root=a.output/topology;root.mkdir();results=[];streams=[];builds=[];probes=[]
            meta=dict(status='running',backend=a.backend,performance_measured=bool(connection),topology=topology,
                nodes=old['nodes'],edges=old['edges'],graph_sha256=graph.fingerprint,training_ms=old['training_ms'],
                source=source.as_posix(),test_seeds=list(range(30000,30000+a.epochs)),queries_per_epoch=a.queries,
                cost_margin=.9,scope='fresh range parameters; graph-specific source profile; no additional training')
            def checkpoint(): (root/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
            checkpoint()
            try:
                seen={(q['country'],q['lower'],q['upper']) for q in old['train_parameters']}
                seen.update((q['country'],q['lower'],q['upper']) for group in old['test_parameters'] for q in group)
                rng=random.Random(31000);parameters=[]
                for epoch,seed in enumerate(meta['test_seeds']):
                    queries=[]
                    while len(queries)<a.queries:
                        width=rng.randint(int(old['nodes']*.15),int(old['nodes']*.75));lower=rng.randint(0,old['nodes']-width)
                        q=RangeQuery(rng.choice(['FR','DE']),lower,lower+width);key=(q.country,q.lower,q.upper)
                        if key in seen:continue
                        seen.add(key);queries.append(q)
                    parameters.append([q.__dict__ for q in queries])
                    built=sample.build(seed,refresh=True);oracle_sample.build(seed,refresh=True)
                    builds.append(dict(epoch=epoch,build_ms=built['build_ms']))
                    order=['exact','adaptive','cost_guard'];random.Random(seed).shuffle(order)
                    for mode in order:
                        started=perf_counter();counter=RangeCounter(backend,sample)
                        controller=ParameterSampler(profile,counter,cost_guard=mode=='cost_guard') if mode!='exact' else None
                        init_ms=1000*(perf_counter()-started);oracle=RangeCounter(reference,oracle_sample);active=[]
                        for request,q in enumerate(queries):
                            budget=(.05,.1,.2)[request%3]
                            for kind in ('node','edge'):
                                start=perf_counter()
                                if mode=='exact':
                                    raw=counter.count(q,1,kind)
                                    result=dict(estimate=raw['count'],raw_count=raw['count'],fidelity=1.,attempts=1,bound=0.,trace=[],fallback=False,parameter_transfer=False)
                                else:result=controller.request(q,kind,budget)
                                elapsed=1000*(perf_counter()-start)
                                for step,probe in enumerate(result.pop('trace')):
                                    if probe['count']!=oracle.count(q,probe['fidelity'],kind)['count']:raise RuntimeError('Probe mismatch')
                                    probes.append(dict(epoch=epoch,mode=mode,request=request,kind=kind,step=step,**probe))
                                if result['raw_count']!=oracle.count(q,result['fidelity'],kind)['count']:raise RuntimeError('Raw mismatch')
                                truth=oracle.count(q,1,kind)['count'];error=abs(result['estimate']-truth)/max(truth,1)
                                row=dict(epoch=epoch,mode=mode,request=request,kind=kind,country=q.country,lower=q.lower,
                                    upper=q.upper,budget=budget,online_ms=elapsed,truth=truth,error=error,within_budget=error<=budget,**result)
                                active.append(row);results.append(row)
                        streams.append(dict(epoch=epoch,mode=mode,init_ms=init_ms,online_ms=sum(r['online_ms'] for r in active),
                            components=len(active),failures=sum(not r['within_budget'] for r in active)))
                        print(topology,seed,mode,'verified',flush=True)
                meta['test_parameters']=parameters
                write_csv(root/'requests.csv',results);write_csv(root/'streams.csv',streams)
                write_csv(root/'builds.csv',builds);write_csv(root/'probes.csv',probes)
                meta['status']='completed';meta['all_raw_counts_match']=True;checkpoint()
            except BaseException:
                meta['status']='failed_or_interrupted';checkpoint();raise
    finally:
        if connection:connection.close()


if __name__=='__main__':main()
