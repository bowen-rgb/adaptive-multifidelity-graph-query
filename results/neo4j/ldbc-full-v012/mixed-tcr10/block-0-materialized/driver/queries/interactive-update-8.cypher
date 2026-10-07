MATCH (p1:Person {id:$person1Id}), (p2:Person {id:$person2Id})
OPTIONAL MATCH (p1)-[w:MF_REPLY_WEIGHT]-(p2)
CREATE (p1)-[:KNOWS {creationDate:$creationDate, mfWeight:coalesce(w.weight,0.0)}]->(p2)
