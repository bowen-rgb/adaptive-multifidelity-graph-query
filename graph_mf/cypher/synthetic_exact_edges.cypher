MATCH (a:MFNode {dataset: $dataset, country: $country})
      -[r:MF_EDGE {dataset: $dataset}]->
      (b:MFNode {dataset: $dataset, country: $country})
RETURN count(r) AS count
