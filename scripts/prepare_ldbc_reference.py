"""Reproducible database routing patch; retains upstream query semantics."""
import argparse
from pathlib import Path
from graph_mf.ldbc_full import reference_headers

p = argparse.ArgumentParser()
p.add_argument('--reference', required=True)
args = p.parse_args()
root = Path(args.reference)
reference_headers(root)
java = root/'cypher/src/main/java/org/ldbcouncil/snb/impls/workloads/cypher/CypherDbConnectionState.java'
s = java.read_text()
old = 'return driver.session( config );'
new = ('return driver.session( SessionConfig.builder().withDatabase( database )'
       '.withDefaultAccessMode( config.defaultAccessMode() ).build() );')
if old in s:
    s = s.replace('protected final Driver driver;', 'protected final Driver driver;\n    protected final String database;')
    s = s.replace('super(properties, store);', 'super(properties, store);\n        database = properties.getOrDefault("neo4j.database", "neo4j");')
    java.write_text(s.replace(old, new))
elif new not in s:
    raise ValueError('Unexpected reference source')
s = java.read_text().replace('properties.getOrDefault("database", "neo4j")',
                            'properties.getOrDefault("neo4j.database", "neo4j")')
java.write_text(s)
print('Database routing patch ready; build with Maven -Pcypher')
