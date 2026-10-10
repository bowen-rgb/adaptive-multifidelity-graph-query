"""Read-only aggregate density screen; exact semantic checks, not sampling gains."""
import argparse
import csv
import hashlib
import json
import logging
from pathlib import Path
import random
from statistics import median
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import write_csv
from graph_mf.ldbc_full import reference_headers


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--parameters',type=Path,required=True)
    p.add_argument('--pairs',type=int,default=15)
    p.add_argument('--families',nargs='+',type=int,choices=[5,6,12],default=[5,6,12])
    p.add_argument('--all-memberships',action='store_true',help='Custom IC5 minDate=-1 stress, not official substitutions')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.pairs<6:raise ValueError('Fresh output and >=6 distinct pairs required')
    reference_headers(a.reference)
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    b=Neo4jBackend()
    if b.database in ('neo4j','system'):b.close();raise ValueError('Dedicated SNB database required')
    a.output.mkdir(parents=True)
    meta=dict(status='running',database=b.database,read_only=True,parameter_seed=36019,
              scope='exact IC5/IC6/IC12 density screening; one snapshot; not full mixed or adaptive performance',families={})
    def checkpoint():(a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    def execute(q,param):
        start=perf_counter();records,_,_=b.driver.execute_query(q,parameters_=param,database_=b.database,routing_='r')
        return [dict(r) for r in records],1000*(perf_counter()-start)
    rows=[];answers=[]
    try:
        checkpoint()
        for family,count_key,limit in [(5,'postCount',20),(6,'postCount',10),(12,'replyCount',20)]:
            if family not in a.families:continue
            source=a.parameters/f'interactive_{family}_param.txt'
            with source.open() as handle:params=list(csv.DictReader(handle,delimiter='|'))
            params=list({json.dumps(row,sort_keys=True):row for row in params}.values())
            random.Random(36019+family).shuffle(params)
            params=[{k:int(v) if k in ('personId','minDate') else v for k,v in x.items()} for x in params[:a.pairs]]
            if family==5 and a.all_memberships:
                for param in params:param['minDate']=-1
                meta['stress']='IC5 full membership window, same preselected roots; custom parameters'
            if len({json.dumps(x,sort_keys=True) for x in params})!=a.pairs:raise ValueError('Distinct screen parameters required')
            q=(a.reference/f'cypher/queries/interactive-complex-{family}.cypher').read_text()
            suffix=f'LIMIT {limit}'
            if not q.rstrip().endswith(suffix):raise ValueError('Unexpected pinned query limit')
            full=q.rstrip()[:-len(suffix)]
            meta['families'][str(family)]=dict(parameters=params,parameter_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),query_sha256=hashlib.sha256(q.encode()).hexdigest())
            for index,param in enumerate(params):
                exact,elapsed=execute(q,param);all_rows,_=execute(full,param)
                if exact!=all_rows[:limit]:raise RuntimeError('Full aggregate prefix mismatch')
                counts=[r[count_key] for r in all_rows];top=[r[count_key] for r in exact]
                positives=[v for v in counts if v>0]
                rows.append(dict(family=family,parameter=index,online_ms=elapsed,returned=len(exact),groups=len(counts),
                    positive_groups=len(positives),zeros=counts.count(0),ones=counts.count(1),
                    median_positive=median(positives) if positives else 0,max_count=max(counts,default=0),
                    top_median=median(top) if top else 0,top_min=min(top,default=0),top_max=max(top,default=0)))
                answers.append(dict(family=family,parameter=index,exact=exact,counts=counts))
            print('IC',family,'density and exact prefixes verified',flush=True)
        write_csv(a.output/'requests.csv',rows)
        (a.output/'answers.json').write_text(json.dumps(answers,indent=2)+'\n',encoding='utf-8')
        meta.update(status='completed',all_exact_prefixes_match=True);checkpoint()
    except BaseException:meta['status']='failed_or_interrupted';checkpoint();raise
    finally:b.close()


if __name__=='__main__':main()
