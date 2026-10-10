"""Frozen-profile IC5 confirmation with pristine upstream baseline and fresh roots."""
import argparse
import hashlib
import json
import logging
import random
from pathlib import Path
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_ic5_sampling import IC5Views,quality,adaptive_request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','pristine-import','validation','reference','output','csv-data'):
        p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh output required')
    source=json.loads((a.source/'metadata.json').read_text())
    pristine=json.loads(a.pristine_import.read_text())
    validated=json.loads((a.validation/'metadata.json').read_text())
    imported=json.loads(Path(source['source_import']).read_text())
    if source['status']!='completed' or pristine['status']!='completed':raise ValueError('Completed experiments required')
    if validated['status']!='completed' or not validated['validation_pass']:raise ValueError('Wait for full reference validation')
    if imported['files']!=pristine['files']:raise ValueError('Initial CSV manifests differ')
    profile_text=(a.source/'profile.json').read_text();profile=json.loads(profile_text)
    original=(a.reference/'cypher/queries/interactive-complex-5.cypher').read_text()
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    start=perf_counter();backend=Neo4jBackend();views=IC5Views(backend,expected_source=(imported['nodes'],imported['relationships']))
    if backend.database!=source['database']:backend.close();raise ValueError('Sample database mismatch')
    def execute(statement,param,database):
        begin=perf_counter()
        rows,_,_=backend.driver.execute_query(statement,parameters_=param,database_=database)
        return [dict(r) for r in rows],1000*(perf_counter()-begin)
    for database in (backend.database,pristine['database']):
        n,_=execute('MATCH (n) WHERE NOT n:MFIC5Sample RETURN count(n) AS n',{},database)
        r,_=execute('MATCH ()-[r]->() WHERE NOT type(r) STARTS WITH "MF_IC5_" RETURN count(r) AS n',{},database)
        if (n[0]['n'],r[0]['n'])!=views.expected_source:backend.close();raise ValueError('Source changed')
    excluded=set(source['excluded_screen_roots'])|{x['personId'] for group in source['parameters'].values() for x in group}
    records=views.execute('MATCH (p:Person) RETURN p.id AS id ORDER BY id')
    roots=[r['id'] for r in records if r['id'] not in excluded];random.Random(44019).shuffle(roots)
    parameters=[dict(personId=r,minDate=-1) for r in roots[:10]]
    meta=dict(status='running',scope='static initial SF0.1 custom IC5; independent roots/seeds; no mixed workload',
        background_workload='none; full reference replay, imports, and offline studies completed before timing',
        parameters=parameters,seeds=list(range(43000,43006)),parameter_seed=44019,
        source=str(a.source),pristine_import=str(a.pristine_import),validation=str(a.validation),
        initialization_ms=1000*(perf_counter()-start),profile_sha256=hashlib.sha256(profile_text.encode()).hexdigest(),
        frozen_profile=True,no_test_oracle_in_selection=True,quality_target=dict(recall=.9,max_count_error=.2))
    a.output.mkdir(parents=True)
    def checkpoint():(a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
    checkpoint();requests=[];answers=[];builds=[];probes=[]
    try:
        # Independent CSV oracle validates exact values and the physical sample ranks.
        # Loading, oracles, warmups and source audits are excluded from online timing.
        from graph_mf.ic5_offline import load_ic5_csv
        graph,csv_manifest=load_ic5_csv(a.csv_data)
        truth=[graph.query(p['personId'],p['minDate']) for p in parameters]
        for param,answer in zip(parameters,truth):
            raw,_=execute(original,param,pristine['database'])
            if raw!=[{k:r[k] for k in ('forumName','postCount')} for r in answer]:raise RuntimeError('CSV/upstream exact mismatch')
            full,_=views.count(param,1.,'unused')
            if full!=answer:raise RuntimeError('CSV/augmented exact mismatch')
        for mode in ('reference_pristine','reference_augmented','exact','fixed_75','fixed_90','adaptive'):
            if mode.startswith('reference'):
                execute(original,parameters[0],pristine['database'] if mode=='reference_pristine' else backend.database)
            else:views.count(parameters[0],1.,'unused')
        checked=0
        for seed in meta['seeds']:
            built=views.build(seed);builds.append(built)
            prefixes=graph.prefixes(seed,(.25,.5,.75,.9))
            # First evaluate every physical tier against the independent CSV engine.
            for param in parameters:
                for f in (.25,.5,.75,.9):
                    actual,_=views.count(param,f,built['generation'])
                    if actual!=graph.query(param['personId'],-1,f,prefixes):raise RuntimeError('CSV/sample mismatch')
                    checked+=1
            modes=['reference_pristine','reference_augmented','exact','fixed_75','fixed_90','adaptive']
            random.Random(seed).shuffle(modes)
            for mode in modes:
                for i,param in enumerate(parameters):
                    if mode.startswith('reference'):
                        raw,elapsed=execute(original,param,pristine['database'] if mode=='reference_pristine' else backend.database)
                        if raw!=[{k:r[k] for k in ('forumName','postCount')} for r in truth[i]]:raise RuntimeError('Reference changed')
                        answer=truth[i];f=1.;trace=[]
                    elif mode=='adaptive':
                        answer,out=adaptive_request(views,param,profile,built['generation'])
                        f=out['fidelity'];elapsed=out['online_ms'];trace=out['trace']
                    else:
                        f={'exact':1.,'fixed_75':.75,'fixed_90':.9}[mode]
                        answer,elapsed=views.count(param,f,built['generation']);trace=[]
                    metric=quality(truth[i],answer)
                    requests.append(dict(seed=seed,parameter=i,mode=mode,fidelity=f,online_ms=elapsed,
                        meets_quality=metric['recall']>=.9 and metric['max_count_error']<=.2,**metric))
                    answers.append(dict(seed=seed,parameter=i,mode=mode,rows=answer))
                    probes.extend(dict(seed=seed,parameter=i,step=j,**r) for j,r in enumerate(trace))
            print('confirmation',seed,'checked',flush=True)
        write_csv(a.output/'requests.csv',requests);write_csv(a.output/'builds.csv',builds);write_csv(a.output/'probes.csv',probes)
        (a.output/'answers.json').write_text(json.dumps(dict(exact=truth,measurements=answers),indent=2)+'\n')
        meta.update(status='completed',csv_exact_match=True,csv_sample_checks=checked,csv_source_manifest=csv_manifest,
            exclusions=['CSV import/oracle checks','warmup','Neo4j graph import','profile file reading'],
            preparation_accounting='charge all four physical views; report initial training separately; no full lifecycle gain claim')
        checkpoint()
    except BaseException:meta['status']='failed_or_interrupted';checkpoint();raise
    finally:backend.close()


if __name__=='__main__':main()
