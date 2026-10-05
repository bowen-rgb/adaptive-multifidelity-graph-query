UNWIND $rows AS row
MATCH (n:MFNode {dataset: $dataset, id: row.id})
SET n.sample = row.sample
