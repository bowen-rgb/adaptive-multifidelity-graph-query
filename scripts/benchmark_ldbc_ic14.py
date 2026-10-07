"""Paired exact IC14 timing and full-result equivalence on fixed official parameters."""
import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import random
from statistics import mean
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_full import reference_headers

p = argparse.ArgumentParser()
p.add_argument('--reference', required=True)
p.add_argument('--parameters', required=True)
p.add_argument('--output', required=True)
p.add_argument('--pairs', type=int, default=24)
p.add_argument('--blocks', type=int, default=5)
p.add_argument('--materialized', action='store_true')
a = p.parse_args()
logging.getLogger('neo4j').setLevel(logging.ERROR)
if a.pairs < 2 or a.blocks < 2:
    raise ValueError('Multiple parameters and blocks required')
reference_headers(a.reference)
original = (Path(a.reference)/'cypher/queries/interactive-complex-14.cypher').read_text()
optimized = (Path(__file__).resolve().parents[1]/'graph_mf/cypher/ldbc_ic14_bound.cypher').read_text()
if a.materialized:
    optimized=(Path(__file__).resolve().parents[1]/'graph_mf/cypher/ldbc_ic14_weights.cypher').read_text()
parameter_file = Path(a.parameters)/'interactive_14_param.txt'
with parameter_file.open() as f:
    params = list(csv.DictReader(f,delimiter='|'))
random.Random(12012).shuffle(params)
params = [{k:int(v) for k,v in row.items()} for row in params[:a.pairs]]
output = Path(a.output)
if output.exists():
    raise ValueError('New output directory required')
output.mkdir(parents=True)
b = Neo4jBackend()
if b.database in ('neo4j','system'):
    b.close()
    raise ValueError('Dedicated LDBC database required')
meta = dict(status='running', database=b.database, scope='exact IC14 paired query experiment, not mixed SNB throughput',
    parameters=params,blocks=a.blocks,parameter_seed=12012,order_seed=14014,warm_cache=True,
    query_sha256={k:hashlib.sha256(v.encode()).hexdigest() for k,v in [('reference',original),('bound',optimized)]},
    parameter_sha256=hashlib.sha256(parameter_file.read_bytes()).hexdigest(),
    construction_ms=0,calibration_ms=0,approximation=False,includes_client_and_transaction=True)
def checkpoint():
    (output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')
def canonical(records):
    # IC14 specifies descending weight, with no ordering requirement within weight ties.
    values = [(tuple(r['personIdsInPath']),float(r['pathWeight'])) for r in records]
    if any(values[i][1] < values[i+1][1] for i in range(len(values)-1)):
        raise RuntimeError('IC14 weight ordering violated')
    return sorted(values)
def execute(query,params,profile=False):
    start = perf_counter()
    records,summary,_ = b.driver.execute_query(('PROFILE ' if profile else '')+query,
        parameters_=params,database_=b.database,routing_='r')
    elapsed = 1000*(perf_counter()-start)
    return canonical(records),elapsed,summary
rows=[]
try:
    if a.materialized:
        from graph_mf.ldbc_weights import build_weights
        preparation=build_weights(b)
        meta['construction_ms']=preparation['build_ms']
        meta['preparation']=preparation
    checkpoint()
    # Compile/warm both query shapes and verify answers outside timed repetitions.
    for param in params:
        x,_,_ = execute(original,param)
        y,_,_ = execute(optimized,param)
        if x != y:
            raise RuntimeError('Exact IC14 path/weight mismatch')
    rng=random.Random(14014)
    for block in range(a.blocks):
        indices=list(range(len(params))); rng.shuffle(indices)
        for index in indices:
            variants=[('reference',original),('bound',optimized)]; rng.shuffle(variants)
            answers={}
            for name,query in variants:
                values,elapsed,_=execute(query,params[index])
                answers[name]=values
                rows.append(dict(block=block,parameter=index,variant=name,query_ms=elapsed,rows=len(values)))
            if answers['reference'] != answers['bound']:
                raise RuntimeError('Exact IC14 timed result mismatch')
        write_csv(output/'requests.csv',rows)
        print('IC14 block',block+1,'verified',flush=True)
    blocks=[]
    for block in range(a.blocks):
        values={name:mean(r['query_ms'] for r in rows if r['block']==block and r['variant']==name)
                for name in ('reference','bound')}
        blocks.append(dict(block=block,**values,speedup=values['reference']/values['bound']))
    write_csv(output/'blocks.csv',blocks)
    # Timing blocks share a graph and parameter set. The CI is conditional on this workload.
    ratios=[]; rng=random.Random(16016)
    for _ in range(10000):
        selected=[rng.choice(blocks) for _ in blocks]
        ratios.append(mean(x['reference'] for x in selected)/mean(x['bound'] for x in selected))
    ratios.sort()
    profiles=[]
    def hits(node):
        return node.get('dbHits',0)+sum(hits(c) for c in node.get('children',[]))
    for i in range(min(3,len(params))):
        for name,q in [('reference',original),('bound',optimized)]:
            _,_,summary=execute(q,params[i],profile=True)
            profiles.append(dict(parameter=i,variant=name,db_hits=hits(summary.profile)))
    write_csv(output/'profiles.csv',profiles)
    base=mean(x['reference'] for x in blocks); candidate=mean(x['bound'] for x in blocks)
    meta.update(status='completed',all_path_weights_match=True,timed_queries=len(rows),
        reference_mean_ms=base,bound_mean_ms=candidate,speedup=base/candidate,
        candidate='exact_materialized_weights' if a.materialized else 'bound_endpoints',
        materialization_break_even_requests=meta['construction_ms']/(base-candidate) if base>candidate else None,
        conditional_block_bootstrap_95=[ratios[249],ratios[9749]],
        interpretation='single graph, fixed parameter set, warm cache, no concurrent writes; not a general or mixed-workload speedup')
    checkpoint()
    print(json.dumps({k:v for k,v in meta.items() if k not in ('parameters','query_sha256')},indent=2))
except BaseException:
    meta['status']='failed_or_interrupted'; checkpoint(); raise
finally:
    b.close()
