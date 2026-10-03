UNWIND $people AS person
MERGE (p:Person {dataset: $dataset, id: person.id})
SET p.name = person.name, p.age = person.age, p.city = person.city
