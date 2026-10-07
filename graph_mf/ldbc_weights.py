"""Exact IC14 materialization, maintained by the complete SNB v1 insert workload.

Only dedicated full-LDBC databases are supported. Arbitrary external writes, deletes
and other workload versions are outside the lifecycle and invalidate this view.
"""
from pathlib import Path
from time import perf_counter
import hashlib
import json

BUILD = '''
MATCH (c:Comment)-[:HAS_CREATOR]->(author:Person),
      (c)-[:REPLY_OF]->(message:Message)-[:HAS_CREATOR]->(other:Person)
WHERE author <> other
WITH CASE WHEN author.id < other.id THEN author ELSE other END AS a,
     CASE WHEN author.id < other.id THEN other ELSE author END AS b,
     sum(CASE WHEN message:Post THEN 1.0 ELSE 0.5 END) AS weight
CREATE (a)-[:MF_REPLY_WEIGHT {weight:weight}]->(b)
WITH a,b,weight
MATCH (a)-[r:KNOWS]-(b)
SET r.mfWeight=weight
'''

UPDATE7 = '''WITH c, author, message
CALL {
  WITH author, message
  MATCH (message)-[:HAS_CREATOR]->(other:Person)
  WHERE author <> other
  WITH CASE WHEN author.id < other.id THEN author ELSE other END AS a,
       CASE WHEN author.id < other.id THEN other ELSE author END AS b,
       CASE WHEN message:Post THEN 1.0 ELSE 0.5 END AS delta
  MERGE (a)-[w:MF_REPLY_WEIGHT]->(b)
  ON CREATE SET w.weight=0.0
  SET w.weight=w.weight+delta
  WITH a,b,delta
  OPTIONAL MATCH (a)-[r:KNOWS]-(b)
  FOREACH (rel IN CASE WHEN r IS NULL THEN [] ELSE [r] END |
    SET rel.mfWeight=coalesce(rel.mfWeight,0.0)+delta)
  RETURN count(*) AS updatedWeights
}
WITH c
UNWIND $tagIds AS tagId'''

UPDATE8 = '''MATCH (p1:Person {id:$person1Id}), (p2:Person {id:$person2Id})
OPTIONAL MATCH (p1)-[w:MF_REPLY_WEIGHT]-(p2)
CREATE (p1)-[:KNOWS {creationDate:$creationDate, mfWeight:coalesce(w.weight,0.0)}]->(p2)
'''


def build_weights(connection):
    if connection.database in ('neo4j','system'):
        raise ValueError('Dedicated LDBC database required')
    start=perf_counter()
    def write(tx):
        if tx.run('MATCH (s:MFIC14State) RETURN count(s) AS n').single()['n']:
            raise ValueError('Fresh initial snapshot required; weights already exist')
        tx.run('MATCH ()-[r:KNOWS]->() SET r.mfWeight=0.0').consume()
        tx.run(BUILD).consume()
        tx.run('CREATE (:MFIC14State {ready:true, algorithm:"exact-replies-v1"})').consume()
    with connection.driver.session(database=connection.database) as session:
        session.execute_write(write)
    return dict(build_ms=1000*(perf_counter()-start),algorithm='exact-replies-v1',
                maintenance='update7 comment and update8 friendship in the same operation transaction',
                external_mutations_supported=False)


def patch_weight_queries(query_dir):
    query_dir=Path(query_dir)
    q14=Path(__file__).parent/'cypher/ldbc_ic14_weights.cypher'
    (query_dir/'interactive-complex-14.cypher').write_text(q14.read_text())
    q7=query_dir/'interactive-update-7.cypher'
    text=q7.read_text()
    old='WITH c\nUNWIND $tagIds AS tagId'
    if text.count(old)!=1:
        raise ValueError('Unexpected upstream update7 shape')
    q7.write_text(text.replace(old,UPDATE7))
    (query_dir/'interactive-update-8.cypher').write_text(UPDATE8)


def validate_weights(connection):
    """Global exact recomputation after writers stop, beyond selected IC14 paths."""
    if connection.database in ('neo4j','system'):
        raise ValueError('Dedicated LDBC database required')
    start=perf_counter()
    def execute(q):
        return connection.driver.execute_query(q,database_=connection.database)[0]
    expected=execute('MATCH (c:Comment)-[:HAS_CREATOR]->(author:Person), '
        '(c)-[:REPLY_OF]->(message:Message)-[:HAS_CREATOR]->(other:Person) '
        'WHERE author<>other '
        'WITH CASE WHEN author.id<other.id THEN author.id ELSE other.id END AS a,'
        'CASE WHEN author.id<other.id THEN other.id ELSE author.id END AS b, '
        'sum(CASE WHEN message:Post THEN 1.0 ELSE 0.5 END) AS weight RETURN a,b,weight ORDER BY a,b')
    cached=execute('MATCH (a:Person)-[w:MF_REPLY_WEIGHT]->(b:Person) '
                   'RETURN a.id AS a,b.id AS b,w.weight AS weight ORDER BY a,b')
    x=[(r['a'],r['b'],float(r['weight'])) for r in expected]
    y=[(r['a'],r['b'],float(r['weight'])) for r in cached]
    weights={(a,b):w for a,b,w in x}
    friendships=execute('MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a.id AS a,b.id AS b,r.mfWeight AS weight')
    bad=sum(r['weight'] != weights.get(tuple(sorted((r['a'],r['b']))),0.) for r in friendships)
    result=dict(all_pair_weights_match=x==y,reply_pairs=len(x),cached_pairs=len(y),
                friendships=len(friendships),incorrect_friendship_weights=bad,
                recomputed_sha256=hashlib.sha256(json.dumps(x).encode()).hexdigest(),
                cached_sha256=hashlib.sha256(json.dumps(y).encode()).hexdigest(),
                audit_ms=1000*(perf_counter()-start),boundary='quiescent database; no concurrent writers')
    if x!=y or bad:
        raise RuntimeError('Global reply weight audit failed: '+json.dumps(result))
    return result
