UNWIND $friends AS friend
MATCH (a:Person {dataset: $dataset, id: friend.source})
MATCH (b:Person {dataset: $dataset, id: friend.target})
MERGE (a)-[:FRIEND]->(b)
