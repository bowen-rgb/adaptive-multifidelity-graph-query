MATCH (:Person {dataset: $dataset})-[r:FRIEND]->(:Person {dataset: $dataset})
RETURN count(r) AS count
