MATCH (p:Person {dataset: $dataset})
RETURN count(p) AS count
