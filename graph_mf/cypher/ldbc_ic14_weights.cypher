// Exact materialized weights; prepare once, maintain through update7 and update8.
MATCH path = allShortestPaths((person1:Person {id:$person1Id})-[:KNOWS*0..]-(person2:Person {id:$person2Id}))
RETURN [n IN nodes(path) | n.id] AS personIdsInPath,
       reduce(weight=0.0, r IN relationships(path) | weight+r.mfWeight) AS pathWeight
ORDER BY pathWeight DESC
