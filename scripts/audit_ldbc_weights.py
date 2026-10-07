"""Run the quiescent global IC14 materialization audit on a dedicated database."""
import argparse
import json
from pathlib import Path

from graph_mf.backends import Neo4jBackend
from graph_mf.ldbc_weights import validate_weights


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()

backend = Neo4jBackend()
try:
    result = validate_weights(backend)
finally:
    backend.close()
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, sort_keys=True))
