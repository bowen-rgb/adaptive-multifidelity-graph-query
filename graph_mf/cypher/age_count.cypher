MATCH (p:Person {dataset: $dataset})
WHERE p.age >= $min_age
RETURN count(p) AS count
