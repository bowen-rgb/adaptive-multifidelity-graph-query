MATCH (n:MFNode {dataset: $dataset, country: $country})
WHERE n.sample < $fidelity
RETURN count(n) AS count
