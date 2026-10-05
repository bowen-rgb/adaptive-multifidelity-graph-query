CREATE CONSTRAINT mf_node_identity IF NOT EXISTS
FOR (n:MFNode) REQUIRE (n.dataset, n.id) IS UNIQUE
