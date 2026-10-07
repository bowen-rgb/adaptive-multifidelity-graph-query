"""Explicit, documented semantic repairs to the pinned Neo4j reference queries."""
from pathlib import Path

PERSON_GROUPS='''WITH p
CALL {
  WITH p
  UNWIND $tagIds AS tagId
  MATCH (t:Tag {id:tagId})
  CREATE (p)-[:HAS_INTEREST]->(t)
  RETURN count(*) AS tagCount
}
CALL {
  WITH p
  UNWIND $studyAt AS s
  MATCH (u:Organisation {id:s[0]})
  CREATE (p)-[:STUDY_AT {classYear:s[1]}]->(u)
  RETURN count(*) AS studyCount
}
CALL {
  WITH p
  UNWIND $workAt AS w
  MATCH (company:Organisation {id:w[0]})
  CREATE (p)-[:WORK_AT {workFrom:w[1]}]->(company)
  RETURN count(*) AS workCount
}
RETURN p.id AS personId
'''


def patch_reference_queries(query_dir):
    root=Path(query_dir)
    q1=root/'interactive-complex-1.cypher'
    s=q1.read_text(encoding='utf-8').replace('CASE uni.name\n        WHEN null THEN null','CASE WHEN uni IS NULL THEN null')
    q1.write_text(s.replace('CASE company.name\n        WHEN null THEN null','CASE WHEN company IS NULL THEN null'),encoding='utf-8')
    sq7=root/'interactive-short-7.cypher'
    sq7.write_text(sq7.read_text(encoding='utf-8').replace('CASE r\n            WHEN null THEN false',
                                                      'CASE WHEN r IS NULL THEN false'),encoding='utf-8')
    u1=root/'interactive-update-1.cypher'
    s=u1.read_text(encoding='utf-8').replace('languages: $languages','speaks: $languages')
    if 'WITH p, count(*) AS dummy1' not in s:
        raise ValueError('Unexpected reference update1 shape')
    s=s.split('WITH p, count(*) AS dummy1',1)[0]+PERSON_GROUPS
    u1.write_text(s,encoding='utf-8')
