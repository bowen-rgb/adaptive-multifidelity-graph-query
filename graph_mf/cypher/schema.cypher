CREATE CONSTRAINT graph_mf_person_identity IF NOT EXISTS
FOR (p:Person) REQUIRE (p.dataset, p.id) IS UNIQUE
