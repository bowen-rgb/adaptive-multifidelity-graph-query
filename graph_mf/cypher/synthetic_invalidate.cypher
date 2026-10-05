MATCH (s:MFMaterialization {dataset: $dataset})
SET s.status = 'invalidated'
