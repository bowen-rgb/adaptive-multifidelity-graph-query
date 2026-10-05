// Imported MF_EDGE records connect MFNode endpoints in this fingerprinted dataset.
// Keep only the start node labeled to favor traversal over pairwise index seeks.
MATCH (a:MFNode {dataset: $dataset, country: $country})
WHERE a.sample < $fidelity
WITH a
MATCH (a)-[r:MF_EDGE {dataset: $dataset}]->(b)
WHERE b.dataset = $dataset AND b.country = $country AND b.sample < $fidelity
RETURN count(r) AS count
