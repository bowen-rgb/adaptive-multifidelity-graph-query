"""Live correctness-only IC5 fixture; refuses nonempty/non-test databases."""
import json
import logging
from pathlib import Path
from graph_mf.backends import Neo4jBackend
from graph_mf.ldbc_ic5_sampling import IC5Views, LEVELS, OWNER, rank_rows


def main():
    logging.getLogger('neo4j').setLevel(logging.ERROR)
    b=Neo4jBackend()
    if b.database!='ldbcmfic5test019':b.close();raise ValueError('Dedicated empty test database required')
    v=IC5Views(b)
    output=Path('results/neo4j/ic5-view-smoke-v019.json')
    if output.exists():b.close();raise ValueError('Fresh output required')
    try:
        if v.execute('MATCH (n) RETURN count(n) AS n')[0]['n']:raise ValueError('Empty test database required')
        v.execute('CREATE CONSTRAINT IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE')
        v.execute('UNWIND [1,2,3,4] AS id CREATE (:Person {id:id})')
        v.execute('MATCH (a:Person {id:1}),(b:Person {id:2}),(c:Person {id:3}) CREATE (a)-[:KNOWS]->(b),(b)-[:KNOWS]->(c)')
        v.execute('UNWIND [11,12,13] AS id CREATE (:Forum {id:id,title:"same"})')
        v.execute('UNWIND [[11,2],[12,3],[13,2]] AS x MATCH (f:Forum {id:x[0]}),(p:Person {id:x[1]}) CREATE (f)-[:HAS_MEMBER {joinDate:1}]->(p)')
        posts=[dict(id=i,forum=11 if i<110 else 12,creator=2 if i<110 else 3) for i in range(100,130)]
        posts+=[dict(id=200,forum=11,creator=4)]
        v.execute('UNWIND $rows AS r MATCH (f:Forum {id:r.forum}),(p:Person {id:r.creator}) CREATE (f)-[:CONTAINER_OF]->(:Post {id:r.id})-[:HAS_CREATOR]->(p)',dict(rows=posts))
        first=v.build(42);param=dict(personId=1,minDate=-1)
        exact,_=v.count(param,1.,first['generation'])
        if [(r['forumId'],r['postCount']) for r in exact]!=[(12,20),(11,10),(13,0)]:raise RuntimeError('Exact fixture mismatch')
        ranks={r['id']:r['rank'] for r in rank_rows(sorted(p['id'] for p in posts),42)}
        for f in LEVELS:
            expected={forum:sum(p['forum']==forum and p['creator'] in (2,3) and ranks[p['id']]<f for p in posts)/f for forum in (11,12,13)}
            rows,_=v.count(param,f,first['generation'])
            if {r['forumId']:r['postCount'] for r in rows}!=expected:raise RuntimeError('Independent sampled raw-count mismatch')
        empty,_=v.count(dict(personId=-1,minDate=-1),.9,first['generation'])
        if empty!=[]:raise RuntimeError('Legitimate empty answer lost')
        second=v.build(42)
        if second['generation']==first['generation']:raise RuntimeError('Repeated seed aliases generation')
        rejected=False
        try:v.count(param,.9,first['generation'])
        except RuntimeError:rejected=True
        if not rejected:raise RuntimeError('Old generation accepted')
        v.execute('MATCH (s:MFIC5Sample {owner:$owner}) SET s.status="invalid"',dict(owner=OWNER))
        invalid=False
        try:v.count(param,.9,second['generation'])
        except RuntimeError:invalid=True
        if not invalid:raise RuntimeError('Invalid state accepted')
        report=dict(status='passed',exact_and_all_sample_raw_counts_match=True,duplicate_titles_preserved=True,
                    zero_forums_preserved=True,legitimate_empty_preserved=True,repeated_seed_old_generation_rejected=True,
                    invalid_state_rejected=True,performance_measured=False)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    finally:b.close()


if __name__=='__main__':main()
