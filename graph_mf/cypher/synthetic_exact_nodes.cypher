MATCH (n:MFNode {dataset: $dataset, country: $country})
RETURN count(n) AS count
