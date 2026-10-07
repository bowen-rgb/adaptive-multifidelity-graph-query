// Exact IC14: bind each shortest-path edge's endpoints before counting replies.
// Equivalent weights: comment->post 1.0; comment->comment 0.5, both directions.
MATCH path = allShortestPaths((person1:Person {id:$person1Id})-[:KNOWS*0..]-(person2:Person {id:$person2Id}))
CALL {
  WITH path
  UNWIND relationships(path) AS r
  WITH startNode(r) AS a, endNode(r) AS b
  RETURN sum(
    size([(a)<-[:HAS_CREATOR]-(:Comment)-[:REPLY_OF]->(:Post)-[:HAS_CREATOR]->(b) | 1]) +
    size([(b)<-[:HAS_CREATOR]-(:Comment)-[:REPLY_OF]->(:Post)-[:HAS_CREATOR]->(a) | 1]) +
    0.5 * size([(a)<-[:HAS_CREATOR]-(:Comment)-[:REPLY_OF]->(:Comment)-[:HAS_CREATOR]->(b) | 1]) +
    0.5 * size([(b)<-[:HAS_CREATOR]-(:Comment)-[:REPLY_OF]->(:Comment)-[:HAS_CREATOR]->(a) | 1])
  ) AS pathWeight
}
RETURN [n IN nodes(path) | n.id] AS personIdsInPath, pathWeight
ORDER BY pathWeight DESC
