"""Matched-topology experiments with distinct held-out range-query parameters."""
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
from graph_mf.sample_correction import fit_joint_profile
from graph_mf.synthetic import SyntheticMemory,SyntheticNeo4j


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--backend',choices=['memory','neo4j'],default='memory')
    p.add_argument('--nodes',type=int,default=20000)
    p.add_argument('--topologies',nargs='+',default=['uniform','community','hub'])
    p.add_argument('--epochs',type=int,default=6)
    p.add_argument('--queries',type=int,default=40)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();logging.getLogger('neo4j').setLevel(logging.ERROR)
    if a.output.exists() or a.epochs<3 or a.queries<6 or a.nodes<200:raise ValueError('Fresh output and sufficient workload required')
    a.output.mkdir(parents=True)
    connection=Neo4jBackend() if a.backend=='neo4j' else None
    try:
        for topology in a.topologies:
            graph=topology_graph(topology,a.nodes);reference=SyntheticMemory(graph)
            backend=SyntheticNeo4j(graph,connection) if connection else SyntheticMemory(graph)
            sample=ReusableSample(backend);oracle_sample=ReusableSample(reference)
            root=a.output/topology;root.mkdir()
            meta=dict(status='running',backend=a.backend,performance_measured=bool(connection),topology=topology,
                nodes=a.nodes,edges=len(graph.src),graph_sha256=graph.fingerprint,
                fitting_seeds=list(range(26000,26004)),calibration_seeds=list(range(27000,27020)),
                test_seeds=list(range(28000,28000+a.epochs)),queries_per_epoch=a.queries,
                scope='custom country + node-ID range COUNTs; refit per topology, held-out parameters; not SNB')
            def checkpoint(): (root/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
            checkpoint();training=[];results=[];streams=[];builds=[];probes=[]
            try:
                imported=perf_counter()
                if connection:backend.seed()
                meta['import_ms']=1000*(perf_counter()-imported)
                templates=[RangeQuery(c,int(a.nodes*l),int(a.nodes*u)) for c in ('FR','DE') for l,u in ((0,.2),(.2,.4),(.4,.7),(0,.75))]
                excluded={(q.country,q.lower,q.upper) for q in templates}
                rng=random.Random(29000);work=[];seen=set(excluded)
                for epoch in range(a.epochs):
                    queries=[]
                    while len(queries)<a.queries:
                        width=rng.randint(int(a.nodes*.15),int(a.nodes*.75));lower=rng.randint(0,a.nodes-width)
                        q=RangeQuery(rng.choice(['FR','DE']),lower,lower+width)
                        if (q.country,q.lower,q.upper) in seen:continue
                        seen.add((q.country,q.lower,q.upper));queries.append(q)
                    work.append(queries)
                meta['train_parameters']=[q.__dict__ for q in templates]
                meta['test_parameters']=[[q.__dict__ for q in queries] for queries in work]
                start=perf_counter()
                for split in ('fitting','calibration'):
                    for seed in meta[split+'_seeds']:
                        sample.build(seed,refresh=True);oracle_sample.build(seed,refresh=True)
                        counter=RangeCounter(backend,sample);oracle=RangeCounter(reference,oracle_sample)
                        for index,q in enumerate(templates):
                            for kind in ('node','edge'):
                                truth=oracle.count(q,1,kind)['count']
                                for f in (.1,.25,.5,.75,1.):
                                    observed=counter.count(q,f,kind)
                                    if observed['count']!=oracle.count(q,f,kind)['count']:raise RuntimeError('Training raw mismatch')
                                    training.append(dict(split=split,seed=seed,country=f'q{index}',kind=kind,
                                        fidelity=f,truth=truth,**observed))
                        print(topology,split,seed,'verified',flush=True)
                profile=fit_joint_profile([r for r in training if r['split']=='fitting'],
                    [r for r in training if r['split']=='calibration'],(.1,.25,.5,.75,1.),
                    [f'q{i}' for i in range(len(templates))],graph.fingerprint)
                meta['training_ms']=1000*(perf_counter()-start)
                (root/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
                write_csv(root/'training.csv',training)
                for epoch,seed in enumerate(meta['test_seeds']):
                    built=sample.build(seed,refresh=True);oracle_sample.build(seed,refresh=True)
                    builds.append(dict(epoch=epoch,build_ms=built['build_ms']))
                    counter=RangeCounter(backend,sample);oracle=RangeCounter(reference,oracle_sample)
                    controller=ParameterSampler(profile,counter)
                    modes=['exact','adaptive'];random.Random(seed).shuffle(modes)
                    for mode in modes:
                        active=[]
                        for request,q in enumerate(work[epoch]):
                            budget=(.05,.1,.2)[request%3]
                            for kind in ('node','edge'):
                                start=perf_counter()
                                if mode=='exact':
                                    raw=counter.count(q,1,kind)
                                    result=dict(estimate=raw['count'],raw_count=raw['count'],fidelity=1.,attempts=1,bound=0.,trace=[],fallback=False,parameter_transfer=False)
                                else:result=controller.request(q,kind,budget)
                                elapsed=1000*(perf_counter()-start)
                                for step,probe in enumerate(result.pop('trace')):
                                    if probe['count']!=oracle.count(q,probe['fidelity'],kind)['count']:raise RuntimeError('Probe raw mismatch')
                                    probes.append(dict(epoch=epoch,request=request,kind=kind,step=step,**probe))
                                if result['raw_count']!=oracle.count(q,result['fidelity'],kind)['count']:raise RuntimeError('Held-out raw mismatch')
                                truth=oracle.count(q,1,kind)['count'];error=abs(result['estimate']-truth)/max(truth,1)
                                record=dict(epoch=epoch,mode=mode,request=request,kind=kind,country=q.country,
                                    lower=q.lower,upper=q.upper,budget=budget,online_ms=elapsed,truth=truth,
                                    error=error,within_budget=error<=budget,**result)
                                results.append(record);active.append(record)
                        streams.append(dict(epoch=epoch,mode=mode,online_ms=sum(r['online_ms'] for r in active),
                            components=len(active),failures=sum(not r['within_budget'] for r in active)))
                        print(topology,'test',seed,mode,'verified',flush=True)
                write_csv(root/'requests.csv',results);write_csv(root/'streams.csv',streams)
                write_csv(root/'builds.csv',builds);write_csv(root/'probes.csv',probes)
                meta['status']='completed';meta['all_raw_counts_match']=True;checkpoint()
            except BaseException:
                meta['status']='failed_or_interrupted';checkpoint();raise
    finally:
        if connection:connection.close()


if __name__=='__main__':main()
