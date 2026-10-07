MATCH (c:City {id: $cityId})
CREATE (p:Person {
    id: $personId,
    firstName: $personFirstName,
    lastName: $personLastName,
    gender: $gender,
    birthday: $birthday,
    creationDate: $creationDate,
    locationIP: $locationIP,
    browserUsed: $browserUsed,
    speaks: $languages,
    email: $emails
  })-[:IS_LOCATED_IN]->(c)
WITH p
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
