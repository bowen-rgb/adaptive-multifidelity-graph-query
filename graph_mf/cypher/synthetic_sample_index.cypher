CREATE RANGE INDEX mf_sample IF NOT EXISTS
FOR (n:MFNode) ON (n.dataset, n.country, n.sample)
