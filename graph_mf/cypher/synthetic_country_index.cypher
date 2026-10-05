CREATE RANGE INDEX mf_country IF NOT EXISTS
FOR (n:MFNode) ON (n.dataset, n.country)
