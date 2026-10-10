"""Read-only SF0.1 IC3 fixed-tier feasibility pilot; not full adaptive SNB."""
import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import random
from time import perf_counter

from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_full import reference_headers
from graph_mf.ldbc_ic3_sampling import POPULATION, CANDIDATES, select_messages, quality


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--parameters', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=8)
    parser.add_argument('--blocks', type=int, default=3)
    parser.add_argument('--stress-wide-window', action='store_true',
                        help='Custom full-date/top-country stress parameters, not official substitutions')
    args = parser.parse_args()
    if args.output.exists() or args.pairs < 2 or args.blocks < 2:
        raise ValueError('Fresh output and multiple parameters/blocks required')
    reference_headers(args.reference)
    original = (args.reference/'cypher/queries/interactive-complex-3.cypher').read_text()
    source = args.parameters/'interactive_3_param.txt'
    with source.open() as handle:
        parameters = list(csv.DictReader(handle, delimiter='|'))
    random.Random(33000).shuffle(parameters)
    parameters = [dict(personId=int(p['personId']), startDate=int(p['startDate']),
                       endDate=int(p['startDate'])+int(p['durationDays'])*86400000,
                       countryXName=p['countryXName'], countryYName=p['countryYName'])
                  for p in parameters[:args.pairs]]
    if len({json.dumps(p, sort_keys=True) for p in parameters}) != args.pairs:
        raise ValueError('Distinct IC3 parameters required')
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    backend = Neo4jBackend()
    if backend.database in ('neo4j', 'system'):
        backend.close()
        raise ValueError('Dedicated full-LDBC database required')
    args.output.mkdir(parents=True)
    meta = dict(status='running', database=backend.database, parameters=parameters,
                blocks=args.blocks, rank_seeds=list(range(34000,34000+args.blocks)),
                parameter_seed=33000, read_only=True, approximation=True,
                parameter_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                query_sha256={name:hashlib.sha256(query.encode()).hexdigest()
                              for name,query in [('reference',original),('population',POPULATION),('candidate',CANDIDATES)]},
                scope='fixed-tier IC3 pilot; repeated parameters; no fitting, calibration or adaptive policy; no mixed workload',
                quality_target=dict(recall=.9, max_count_error=.2),
                measurement='online includes fresh population lookup, ID transfer, Python selection and query; test oracle excluded')
    def checkpoint():
        (args.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    def execute(query, params):
        records,_,_ = backend.driver.execute_query(query,parameters_=params,
                                                   database_=backend.database,routing_='r')
        return [dict(row) for row in records]
    rows=[]; answers=[]
    try:
        checkpoint()
        # Record counts before/after: external writers must remain quiescent.
        before=execute('MATCH (n) RETURN count(n) AS nodes',{})[0]
        before.update(execute('MATCH ()-[r]->() RETURN count(r) AS relationships',{})[0])
        meta['population_before']=before
        preparation_start=perf_counter()
        if args.stress_wide_window:
            countries=execute('MATCH (m:Message)-[:IS_LOCATED_IN]->(c:Country) RETURN c.name AS name,count(m) AS n ORDER BY n DESC,name LIMIT 2',{})
            dates=execute('MATCH (m:Message) RETURN min(m.creationDate) AS lower,max(m.creationDate) AS upper',{})[0]
            for param in parameters:
                param.update(countryXName=countries[0]['name'],countryYName=countries[1]['name'],
                             startDate=dates['lower'],endDate=dates['upper']+1)
            meta['stress_definition']='same preselected roots; globally most frequent two message countries and full date range; not chosen by root answer'
        meta['parameter_preparation_ms']=1000*(perf_counter()-preparation_start)
        checkpoint()
        print('IC3 parameters prepared; checking exact tuples',flush=True)
        truth=[execute(original,param) for param in parameters]
        # Compile both query shapes before timed blocks; preserve warmup cost.
        warmup_start=perf_counter()
        warm_ids=[row['id'] for row in execute(POPULATION,parameters[0])]
        execute(CANDIDATES,dict(**parameters[0],messageIds=warm_ids,f=1.))
        meta['warmup_ms']=1000*(perf_counter()-warmup_start)
        checkpoint()
        print('IC3 candidate warmed; timing fixed tiers',flush=True)
        order_rng=random.Random(35000)
        for block,seed in enumerate(meta['rank_seeds']):
            indices=list(range(len(parameters)));order_rng.shuffle(indices)
            for index in indices:
                param=parameters[index]
                modes=[('reference',1.),('population_exact',1.),('fixed_10',.1),('fixed_25',.25),('fixed_50',.5),('fixed_75',.75)]
                order_rng.shuffle(modes)
                for mode,f in modes:
                    start=perf_counter();lookup_ms=selection_ms=0.;population_size=sample_size=0
                    if mode=='reference':
                        result=execute(original,param)
                    else:
                        ids=[row['id'] for row in execute(POPULATION,param)]
                        lookup_ms=1000*(perf_counter()-start);selection_start=perf_counter()
                        selected=select_messages(ids,f,seed)
                        selection_ms=1000*(perf_counter()-selection_start)
                        population_size=len(ids);sample_size=len(selected)
                        result=execute(CANDIDATES,dict(**param,messageIds=selected,f=f))
                        if f==1:
                            for row in result:
                                for key in ('xCount','yCount','xyCount'):
                                    if row[key]!=int(row[key]):
                                        raise RuntimeError('Nonintegral exact IC3 count')
                                    row[key]=int(row[key])
                    elapsed=1000*(perf_counter()-start)
                    if f==1 and result!=truth[index]:
                        raise RuntimeError('Exact ordered IC3 tuple mismatch or concurrent mutation')
                    metrics=quality(truth[index],result)
                    rows.append(dict(block=block,parameter=index,mode=mode,fidelity=f,
                                     online_ms=elapsed,population_ms=lookup_ms,selection_ms=selection_ms,
                                     population_size=population_size,sample_size=sample_size,
                                     meets_quality=metrics['recall']>=.9 and metrics['max_count_error']<=.2,**metrics))
                    answers.append(dict(block=block,parameter=index,mode=mode,rows=result))
            print('IC3 block',block+1,'exact tuples checked',flush=True)
        after=execute('MATCH (n) RETURN count(n) AS nodes',{})[0]
        after.update(execute('MATCH ()-[r]->() RETURN count(r) AS relationships',{})[0])
        if after!=before:raise RuntimeError('Population changed; invalid quiescent pilot')
        meta.update(status='completed',population_after=after,exact_tuples_match=True,
                    mutation_limit='equal counts cannot detect every external property mutation; run without writers')
        write_csv(args.output/'requests.csv',rows)
        (args.output/'answers.json').write_text(json.dumps(dict(exact=truth,measurements=answers),indent=2)+'\n')
        checkpoint()
    except BaseException:
        meta['status']='failed_or_interrupted';checkpoint();raise
    finally:
        backend.close()


if __name__=='__main__':
    main()
