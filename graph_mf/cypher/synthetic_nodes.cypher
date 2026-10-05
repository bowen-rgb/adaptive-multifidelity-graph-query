UNWIND $rows AS row
MERGE (n:MFNode {dataset: $dataset, id: row.id})
SET n.country = row.country, n.sample = 0.0
