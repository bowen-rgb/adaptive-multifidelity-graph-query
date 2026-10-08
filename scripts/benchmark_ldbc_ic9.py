"""Bounded, paired IC9 optimization experiment; retains negative results."""
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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True)
    p.add_argument('--parameters',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--pairs',type=int,default=20)
    p.add_argument('--blocks',type=int,default=5)
    a=p.parse_args()
    if a.pairs<2 or a.blocks<2 or a.output.exists():
        raise ValueError('Multiple pairs/blocks and a fresh output directory required')
    reference_headers(a.reference)
    original=(Path(a.reference)/'cypher/queries/interactive-complex-9.cypher').read_text()
    candidate=(Path(__file__).resolve().parents[1]/'graph_mf/cypher/ldbc_ic9_local_topk.cypher').read_text()
    source=Path(a.parameters)/'interactive_9_param.txt'
    with source.open() as f:
        parameters=list(csv.DictReader(f,delimiter='|'))
    random.Random(13013).shuffle(parameters)
    parameters=[{k:int(v) for k,v in x.items()} for x in parameters[:a.pairs]]
    a.output.mkdir(parents=True)
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    backend=Neo4jBackend()
    if backend.database in ('neo4j','system'):
        backend.close()
        raise ValueError('Dedicated full-LDBC database required')
    meta=dict(status='running',database=backend.database,parameters=parameters,blocks=a.blocks,
              parameter_seed=13013,order_seed=13014,approximation=False,
              parameter_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
              query_sha256={k:hashlib.sha256(q.encode()).hexdigest() for k,q in [('reference',original),('candidate',candidate)]},
              interpretation='fixed parameters, single graph, warm cache; query-only, not full SNB throughput')
    def checkpoint():
        (a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    def execute(query,param):
        start=perf_counter()
        records,_,_=backend.driver.execute_query(query,parameters_=param,database_=backend.database,routing_='r')
        elapsed=1000*(perf_counter()-start)
        return [dict(r) for r in records],elapsed
    rows=[]
    try:
        checkpoint()
        for param in parameters:
            if execute(original,param)[0]!=execute(candidate,param)[0]:
                raise RuntimeError('IC9 warmup ordered full-row mismatch')
        rng=random.Random(13014)
        for block in range(a.blocks):
            indices=list(range(len(parameters))); rng.shuffle(indices)
            for index in indices:
                variants=[('reference',original),('candidate',candidate)]; rng.shuffle(variants)
                answers={}
                for name,query in variants:
                    values,elapsed=execute(query,parameters[index]); answers[name]=values
                    rows.append(dict(block=block,parameter=index,variant=name,query_ms=elapsed,rows=len(values)))
                if answers['reference']!=answers['candidate']:
                    raise RuntimeError('IC9 timed ordered full-row mismatch')
            write_csv(a.output/'requests.csv',rows)
            print('IC9 block',block+1,'verified',flush=True)
        blocks=[dict(block=i,**{name:mean(r['query_ms'] for r in rows if r['block']==i and r['variant']==name)
                    for name in ('reference','candidate')}) for i in range(a.blocks)]
        write_csv(a.output/'blocks.csv',blocks)
        base=mean(x['reference'] for x in blocks); changed=mean(x['candidate'] for x in blocks)
        meta.update(status='completed',all_ordered_rows_match=True,timed_queries=len(rows),
                    reference_mean_ms=base,candidate_mean_ms=changed,speedup=base/changed,
                    adopted=False,reason=('candidate slower than reference; retained as a negative result' if changed>=base
                                          else 'positive local result requires broader validation before driver integration'))
        checkpoint(); print(json.dumps({k:v for k,v in meta.items() if k not in ('parameters','query_sha256')},indent=2))
    except BaseException:
        meta['status']='failed_or_interrupted'; checkpoint(); raise
    finally:
        backend.close()


if __name__=='__main__':
    main()
