"""Run from the repository root: python -m graph_mf --backend memory smoke."""
import argparse
import json
import sys
from . import __version__
from .backends import MemoryBackend, Neo4jBackend, QUERIES
from .dataset import load_tiny


def main(argv=None):
    parser = argparse.ArgumentParser(description="Graph exact COUNT learning milestone")
    parser.add_argument("--backend", choices=("memory", "neo4j"), default="memory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="Idempotently load the tiny dataset")
    commands.add_parser("smoke", help="Check existing data against the tiny fixture; does not seed Neo4j")
    count = commands.add_parser("count")
    count.add_argument("query", choices=QUERIES)
    count.add_argument("--city")
    count.add_argument("--min-age", type=int)
    args = parser.parse_args(argv)
    backend = None
    try:
        backend = MemoryBackend() if args.backend == "memory" else Neo4jBackend()
        result = {"version": __version__, "backend": backend.name, "dataset": load_tiny()["dataset"], "neo4j_measured": False}
        # This flag indicates query execution, never benchmark or performance evidence.
        result["neo4j_query_executed"] = backend.name == "neo4j" and args.command != "seed"
        if args.command == "seed":
            backend.seed()
            result["seeded"] = True
        elif args.command == "count":
            params = {}
            if args.city is not None:
                params["city"] = args.city
            if args.min_age is not None:
                params["min_age"] = args.min_age
            result.update(query=args.query, parameters=params, count=backend.count(args.query, **params))
        else:
            observed = {
                "node_count": backend.count("node_count"),
                "edge_count": backend.count("edge_count"),
                "city_count_Paris": backend.count("city_count", city="Paris"),
                "age_count_24": backend.count("age_count", min_age=24),
            }
            expected = {"node_count": 3, "edge_count": 2, "city_count_Paris": 1, "age_count_24": 2}
            result.update(observed=observed, expected=expected, passed=observed == expected)
            if observed != expected:
                print(json.dumps(result, indent=2))
                return 1
        print(json.dumps(result, indent=2))
        return 0
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
