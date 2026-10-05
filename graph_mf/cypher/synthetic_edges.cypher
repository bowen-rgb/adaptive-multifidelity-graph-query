UNWIND $rows AS row
MATCH (a:MFNode {dataset: $dataset, id: row.source})
MATCH (b:MFNode {dataset: $dataset, id: row.target})
MERGE (a)-[:MF_EDGE {dataset: $dataset, edge_id: row.edge_id}]->(b)
