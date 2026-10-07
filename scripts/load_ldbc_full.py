"""Create no databases and delete no data. Load only a caller-selected empty database."""
import argparse
from graph_mf.backends import Neo4jBackend
from graph_mf.ldbc_full import load_full

p = argparse.ArgumentParser()
p.add_argument('--dataset-path', required=True)
p.add_argument('--reference', required=True)
p.add_argument('--output', required=True)
p.add_argument('--batch-size', type=int, default=2000)
args = p.parse_args()
connection = Neo4jBackend()
try:
    load_full(connection, args.dataset_path, args.reference, args.output,args.batch_size)
finally:
    connection.close()
