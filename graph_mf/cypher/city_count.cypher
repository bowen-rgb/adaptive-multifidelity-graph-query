MATCH (p:Person {dataset: $dataset})
WHERE p.city = $city
RETURN count(p) AS count
