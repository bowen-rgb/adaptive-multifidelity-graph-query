"""Experimental nested IC5 post views; never used by the official driver.

IC5 query structure derives from pinned LDBC SNB v1 commit
11db98cc2ba14c33492f6c0c34e68c8be7e22e5f, Apache-2.0; original LICENSE/NOTICE
are in third_party/ldbc. Changes use sample container relations and retain forum
IDs to assess ranking, including zero-count forums. Python helpers are project code.
"""
import math
import random
from uuid import uuid4
from time import perf_counter

LEVELS = {.25:'MF_IC5_25', .5:'MF_IC5_50', .75:'MF_IC5_75', .9:'MF_IC5_90'}
OWNER = 'ic5-v019'


def query(fidelity):
    if fidelity != 1 and fidelity not in LEVELS:
        raise ValueError('Known IC5 fidelity required')
    relation = 'CONTAINER_OF' if fidelity == 1 else LEVELS[fidelity]
    guard = '' if fidelity == 1 else '''MATCH (s:MFIC5Sample {owner:$owner})
WHERE s.status="ready" AND s.generation=$generation WITH s '''
    body = '''MATCH (person:Person {id:$personId})-[:KNOWS*1..2]-(friend)
WHERE person <> friend
WITH DISTINCT friend
MATCH (friend)<-[membership:HAS_MEMBER]-(forum)
WHERE membership.joinDate > $minDate
WITH forum,collect(friend) AS friends
OPTIONAL MATCH (friend)<-[:HAS_CREATOR]-(post)<-[:''' + relation + ''']-(forum)
WHERE friend IN friends
WITH forum,count(post)/$f AS postCount
RETURN forum.id AS forumId,forum.title AS forumName,postCount
ORDER BY postCount DESC,forum.id ASC LIMIT 20'''
    if fidelity == 1:return body
    # Inner global collect preserves legitimate empty results. The outer guard
    # has no aggregate, so absent/stale state returns no record, not an empty answer.
    return guard + 'CALL { CALL { ' + body + ''' } RETURN collect({forumId:forumId,
forumName:forumName,postCount:postCount}) AS rows } RETURN rows'''


def rank_rows(ids, seed):
    rng=random.Random(seed)
    return [dict(id=i,rank=rng.random()) for i in ids]


def quality(exact, approximate):
    truth={r['forumId']:(i,r) for i,r in enumerate(exact)}
    estimated={r['forumId']:(i,r) for i,r in enumerate(approximate)}
    common=truth.keys() & estimated.keys()
    errors=[abs(estimated.get(k,(0,{}))[1].get('postCount',0)-v['postCount'])/max(v['postCount'],1)
            for k,(_,v) in truth.items()]
    return dict(recall=len(common)/len(truth) if truth else float(not estimated),
                max_count_error=max(errors,default=0.),
                mean_count_error=sum(errors)/len(errors) if errors else 0.,
                missing=len(truth.keys()-estimated.keys()),
                false_forums=len(estimated.keys()-truth.keys()),
                mean_rank_displacement=sum(abs(truth[k][0]-estimated[k][0]) for k in common)/len(common) if common else 0.)


class IC5Views:
    def __init__(self, backend, expected_source=None):
        # This run created this database for reference replay and sampling; no other
        # user/previous experiment database can be modified by this adapter.
        if backend.database not in ('ldbcmfic5bench019','ldbcmfic5test019'):
            raise ValueError('Use the newly created v0.19 isolated experiment database')
        self.backend=backend
        self.expected_source=expected_source

    def execute(self,statement,params=None):
        records,_,_=self.backend.driver.execute_query(statement,parameters_=params or {},database_=self.backend.database)
        return [dict(row) for row in records]

    def build(self,seed):
        start=perf_counter()
        if self.backend.database=='ldbcmfic5bench019' and self.expected_source is None:
            raise ValueError('Bind calibration to the initial import totals before building')
        state=self.execute('MATCH (s:MFIC5Sample) RETURN s.owner AS owner')
        if state and state != [dict(owner=OWNER)]:raise ValueError('Unowned sample state')
        if not state and self.execute('MATCH ()-[r:MF_IC5_25|MF_IC5_50|MF_IC5_75|MF_IC5_90]->() RETURN count(r) AS n')[0]['n']:
            raise ValueError('Unowned sample relationships')
        generation=f'rank-{seed}-{uuid4().hex}'
        self.execute('MERGE (s:MFIC5Sample {owner:$owner}) SET s.status="building",s.generation=$generation',dict(owner=OWNER,generation=generation))
        if self.expected_source is not None:
            nodes=self.execute('MATCH (n) WHERE NOT n:MFIC5Sample RETURN count(n) AS n')[0]['n']
            relationships=self.execute('MATCH ()-[r]->() WHERE NOT type(r) STARTS WITH "MF_IC5_" RETURN count(r) AS n')[0]['n']
            if (nodes,relationships)!=self.expected_source:
                raise ValueError('Source changed: restore the calibrated snapshot or refit before recovery')
        self.execute('MATCH ()-[r:MF_IC5_25|MF_IC5_50|MF_IC5_75|MF_IC5_90]->() DELETE r')
        ids=[r['id'] for r in self.execute('MATCH (p:Post) RETURN p.id AS id ORDER BY id')]
        ranked=rank_rows(ids,seed);totals={}
        for f,rel in LEVELS.items():
            selected=[r for r in ranked if r['rank']<f];total=0
            for offset in range(0,len(selected),10000):
                total+=self.execute('UNWIND $rows AS row MATCH (forum)-[:CONTAINER_OF]->(p:Post {id:row.id}) CREATE (forum)-[r:'+rel+']->(p) RETURN count(r) AS n',dict(rows=selected[offset:offset+10000]))[0]['n']
            totals[str(f)]=total
        self.execute('MATCH (s:MFIC5Sample {owner:$owner}) SET s.status="ready"',dict(owner=OWNER))
        return dict(seed=seed,generation=generation,posts=len(ids),relationships=totals,build_ms=1000*(perf_counter()-start))

    def count(self,parameters,fidelity,generation):
        start=perf_counter()
        records=self.execute(query(fidelity),dict(**parameters,f=fidelity,owner=OWNER,generation=generation))
        if fidelity<1:
            if len(records)!=1:raise RuntimeError('Stale IC5 view')
            records=records[0]['rows']
        return records,1000*(perf_counter()-start)


def choose_tier(profile):
    """Select from independent quality calibration and fitting cost, never test truth."""
    feasible=[r for r in profile if r['quality_score']<=1]
    exact=next(r for r in feasible if r['fidelity']==1)
    best=min(feasible,key=lambda r:r['forecast_ms'])
    return best['fidelity'] if best['forecast_ms'] < .9*exact['forecast_ms'] else 1.


def calibrate_quality(rows, seeds, roots):
    """90% empirical seed-max bound across a fixed calibration root set, per tier."""
    output=[]
    for f in (*LEVELS,1.):
        selected=[r for r in rows if r['fidelity']==f]
        maxima=[]
        for seed in seeds:
            block=[r for r in selected if r['seed']==seed]
            if len(block)!=roots:raise ValueError('Complete independent calibration roots required')
            maxima.append(max(max(r['max_count_error']/.2,(1-r['recall'])/.1) for r in block))
        index=min(len(maxima)-1,math.ceil((len(maxima)+1)*.9)-1)
        output.append(dict(fidelity=f,quality_score=sorted(maxima)[index]))
    return output


def adaptive_request(views,parameters,profile,generation):
    start=perf_counter();trace=[]
    first=choose_tier(profile) if parameters['minDate']==-1 else 1.
    allowed={r['fidelity'] for r in profile if r['quality_score']<=1}
    for f in (*LEVELS,1.):
        if f<first or f not in allowed:continue
        probe_start=perf_counter()
        try:
            answer,_=views.count(parameters,f,generation)
        except RuntimeError:
            trace.append(dict(fidelity=f,accepted=False,reason='stale',query_ms=1000*(perf_counter()-probe_start)))
            answer,_=views.count(parameters,1.,generation)
            trace.append(dict(fidelity=1.,accepted=True,reason='stale_exact_fallback',query_ms=1000*(perf_counter()-probe_start)-trace[-1]['query_ms']))
            return answer,dict(fidelity=1.,online_ms=1000*(perf_counter()-start),trace=trace)
        # This is a conservative sparsity screen, not a top-k confidence theorem.
        enough=f==1 or bool(answer) and min(r['postCount']*f for r in answer)>=8
        trace.append(dict(fidelity=f,accepted=enough,reason='accepted' if enough else 'sparse',query_ms=1000*(perf_counter()-probe_start)))
        if enough:return answer,dict(fidelity=f,online_ms=1000*(perf_counter()-start),trace=trace)
    raise ValueError('Exact terminal tier required')
