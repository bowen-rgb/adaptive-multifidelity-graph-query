"""Independent IC5 calibration and fresh-root test on experimental physical views."""
import argparse
import hashlib
import json
import logging
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_ic5_sampling import IC5Views,LEVELS,OWNER,quality,calibrate_quality,adaptive_request
from graph_mf.ldbc_full import reference_headers


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--screen',type=Path,required=True)
    p.add_argument('--source-import',type=Path,required=True)
    p.add_argument('--background-workload',default='none',help='Record concurrent host work; do not claim isolated timing')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh output required')
    reference_headers(a.reference)
    validated=json.loads(a.source_import.read_text())
    if validated['status']!='completed':raise ValueError('Complete initial import required')
    initialization_start=perf_counter()
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    backend=Neo4jBackend();views=IC5Views(backend)
    if validated['database']!=backend.database:backend.close();raise ValueError('Validated snapshot/database required')
    actual_nodes=views.execute('MATCH (n) WHERE NOT n:MFIC5Sample RETURN count(n) AS n')[0]['n']
    actual_relationships=views.execute('MATCH ()-[r]->() WHERE NOT type(r) STARTS WITH "MF_IC5_" RETURN count(r) AS n')[0]['n']
    if (actual_nodes,actual_relationships)!=(validated['nodes'],validated['relationships']):
        backend.close();raise ValueError('Fresh initial snapshot totals mismatch')
    views.expected_source=(actual_nodes,actual_relationships)
    original=(a.reference/'cypher/queries/interactive-complex-5.cypher').read_text()
    screen=json.loads((a.screen/'metadata.json').read_text())
    excluded={p['personId'] for family in screen['families'].values() for p in family['parameters']}
    roots=[r['id'] for r in views.execute('MATCH (p:Person) RETURN p.id AS id ORDER BY id') if r['id'] not in excluded]
    random.Random(37019).shuffle(roots)
    work={split:[dict(personId=root,minDate=-1) for root in selected]
          for split,selected in [('fitting',roots[:5]),('calibration',roots[5:10]),('test',roots[10:20])]}
    seeds=dict(fitting=list(range(37000,37004)),calibration=list(range(38000,38020)),test=list(range(39000,39006)))
    a.output.mkdir(parents=True)
    meta=dict(status='running',database=backend.database,source_import=str(a.source_import),background_workload=a.background_workload,
        initialization_ms=1000*(perf_counter()-initialization_start),
        parameter_seed=37019,parameters=work,seeds=seeds,excluded_screen_roots=sorted(excluded),
        quality_target=dict(recall=.9,max_count_error=.2),minimum_sample_count=8,
        scope='custom IC5 minDate=-1; fresh root holdout; static initial SF0.1; not official substitutions or mixed SNB',
        original_sha256=hashlib.sha256(original.encode()).hexdigest(),no_test_oracle_in_selection=True)
    def checkpoint():(a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    def reference(param):
        start=perf_counter();answer=views.execute(original,param)
        return answer,1000*(perf_counter()-start)
    def exact(param):
        answer,_=views.count(param,1.,'unused');raw,_=reference(param)
        if raw!=[{k:r[k] for k in ('forumName','postCount')} for r in answer]:
            raise RuntimeError('Augmented exact IC5 ordered values mismatch')
        return answer
    training=[];builds=[];requests=[];answers=[];probes=[]
    try:
        preparation_start=perf_counter()
        checkpoint();truth={split:[exact(p) for p in params] for split,params in work.items() if split!='test'}
        for split in ('fitting','calibration'):
            for seed in seeds[split]:
                built=views.build(seed);builds.append(dict(split=split,**built))
                for index,param in enumerate(work[split]):
                    for f in (*LEVELS,1.):
                        answer,elapsed=views.count(param,f,built['generation'])
                        metric=quality(truth[split][index],answer)
                        training.append(dict(split=split,seed=seed,parameter=index,fidelity=f,query_ms=elapsed,**metric))
                print(split,seed,'measured',flush=True)
        profile=calibrate_quality([r for r in training if r['split']=='calibration'],seeds['calibration'],5)
        for row in profile:
            row['forecast_ms']=mean(r['query_ms'] for r in training if r['split']=='fitting' and r['fidelity']==row['fidelity'])
        meta['training_ms']=1000*(perf_counter()-preparation_start)
        (a.output/'profile.json').write_text(json.dumps(profile,indent=2)+'\n')
        checkpoint();test_truth=[exact(p) for p in work['test']]
        for seed in seeds['test']:
            built=views.build(seed);builds.append(dict(split='test',**built))
            order=['reference','exact','fixed_75','fixed_90','adaptive'];random.Random(seed).shuffle(order)
            for mode in order:
                for index,param in enumerate(work['test']):
                    if mode=='reference':
                        raw,elapsed=reference(param)
                        if raw!=[{k:r[k] for k in ('forumName','postCount')} for r in test_truth[index]]:raise RuntimeError('Reference changed')
                        answer=test_truth[index];f=1.;trace=[]
                    elif mode=='adaptive':
                        answer,out=adaptive_request(views,param,profile,built['generation'])
                        elapsed=out['online_ms'];f=out['fidelity'];trace=out['trace']
                    else:
                        f={'exact':1.,'fixed_75':.75,'fixed_90':.9}[mode]
                        answer,elapsed=views.count(param,f,built['generation']);trace=[]
                    if f==1 and answer!=test_truth[index]:raise RuntimeError('Full-tier changed')
                    metric=quality(test_truth[index],answer)
                    requests.append(dict(seed=seed,parameter=index,mode=mode,fidelity=f,online_ms=elapsed,
                        meets_quality=metric['recall']>=.9 and metric['max_count_error']<=.2,**metric))
                    answers.append(dict(seed=seed,parameter=index,mode=mode,rows=answer))
                    probes.extend(dict(seed=seed,parameter=index,step=i,**r) for i,r in enumerate(trace))
            print('test',seed,'verified',flush=True)
        # Controlled insertion + atomic invalidation: tests known writer integration,
        # not detection of arbitrary external updates or official-driver Update6.
        fixture=-190000000000001;root=work['fitting'][0];generation=built['generation']
        if views.execute('MATCH (p:Post {id:$id}) RETURN p.id AS id',dict(id=fixture)):raise ValueError('Fixture ID occupied')
        start=perf_counter()
        mutation=views.execute('''MATCH (p:Person {id:$personId})-[:KNOWS*1..2]-(friend)
WHERE p <> friend WITH DISTINCT friend
MATCH (friend)<-[membership:HAS_MEMBER]-(forum)
WHERE membership.joinDate > $minDate
WITH forum,friend LIMIT 1
MATCH (s:MFIC5Sample {owner:$owner})
CREATE (post:Post:Message:MFIC5Fixture {id:$id,owner:$owner})
CREATE (forum)-[:CONTAINER_OF]->(post)-[:HAS_CREATOR]->(friend)
SET s.status="invalid"
RETURN post.id AS id''',dict(**root,id=fixture,owner=OWNER))
        if len(mutation)!=1:raise RuntimeError('Mutation fixture could not be created')
        mutation_ms=1000*(perf_counter()-start)
        rejected=False
        try:views.count(root,.9,generation)
        except RuntimeError:rejected=True
        if not rejected:raise RuntimeError('Invalid sample was accepted')
        forced=[dict(fidelity=.9,quality_score=0,forecast_ms=1),dict(fidelity=1.,quality_score=0,forecast_ms=999)]
        result,fallback=adaptive_request(views,root,forced,generation)
        if result!=exact(root) or fallback['fidelity']!=1:raise RuntimeError('Update fallback mismatch')
        changed_recovery_refused=False
        try:views.build(40018)
        except ValueError:changed_recovery_refused=True
        if not changed_recovery_refused:raise RuntimeError('Changed graph reused old calibration')
        views.execute('MATCH (p:MFIC5Fixture {id:$id,owner:$owner}) DETACH DELETE p',dict(id=fixture,owner=OWNER))
        rebuilt=views.build(40019)
        old_rejected=False
        try:views.count(root,.9,generation)
        except RuntimeError:old_rejected=True
        empty,_=views.count(dict(personId=fixture,minDate=-1),.9,rebuilt['generation'])
        if not old_rejected or empty!=[]:raise RuntimeError('Generation/empty guard failure')
        meta['invalidation_test']=dict(insert_ms=mutation_ms,stale_rejected=rejected,exact_fallback_ms=fallback['online_ms'],
            recovery_ms=rebuilt['build_ms'],old_generation_rejected=old_rejected,legitimate_empty_preserved=True,
            forced_fault_profile=True,
            changed_graph_recovery_refused=changed_recovery_refused,
            scope='controlled Post fixture + explicit atomic invalidation; no concurrent or arbitrary external-write guarantee')
        write_csv(a.output/'training.csv',training);write_csv(a.output/'requests.csv',requests)
        write_csv(a.output/'builds.csv',builds);write_csv(a.output/'probes.csv',probes)
        (a.output/'answers.json').write_text(json.dumps(dict(test_exact=test_truth,measurements=answers),indent=2)+'\n')
        meta.update(status='completed',all_exact_values_match=True);checkpoint()
    except BaseException:meta['status']='failed_or_interrupted';checkpoint();raise
    finally:backend.close()


if __name__=='__main__':main()
