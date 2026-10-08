// Exact IC9 candidate: each author's local top 20 contains every global top-20 row.
MATCH (root:Person {id:$personId})-[:KNOWS*1..2]-(friend:Person)
WHERE friend <> root
WITH DISTINCT friend
CALL {
  WITH friend
  MATCH (friend)<-[:HAS_CREATOR]-(message:Message)
  WHERE message.creationDate < $maxDate
  RETURN message
  ORDER BY message.creationDate DESC, message.id ASC
  LIMIT 20
}
RETURN friend.id AS personId, friend.firstName AS personFirstName,
       friend.lastName AS personLastName, message.id AS commentOrPostId,
       coalesce(message.content,message.imageFile) AS commentOrPostContent,
       message.creationDate AS commentOrPostCreationDate
ORDER BY commentOrPostCreationDate DESC, message.id ASC
LIMIT 20
