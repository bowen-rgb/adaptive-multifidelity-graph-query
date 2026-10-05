CREATE CONSTRAINT mf_edge_identity IF NOT EXISTS
FOR ()-[r:MF_EDGE]-() REQUIRE (r.dataset, r.edge_id) IS UNIQUE
