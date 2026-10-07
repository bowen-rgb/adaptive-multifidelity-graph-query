MATCH
  (author:Person {id: $authorPersonId}),
  (country:Country {id: $countryId}),
  (message:Message {id: $replyToPostId + $replyToCommentId + 1}) // $replyToCommentId is -1 if the message is a reply to a post and vica versa (see spec)
CREATE (author)<-[:HAS_CREATOR]-(c:Comment:Message {
    id: $commentId,
    creationDate: $creationDate,
    locationIP: $locationIP,
    browserUsed: $browserUsed,
    content: $content,
    length: $length
  })-[:REPLY_OF]->(message),
  (c)-[:IS_LOCATED_IN]->(country)
WITH c, author, message
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
UNWIND $tagIds AS tagId
  MATCH (t:Tag {id: tagId})
  CREATE (c)-[:HAS_TAG]->(t)