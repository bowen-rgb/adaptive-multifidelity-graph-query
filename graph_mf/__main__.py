"""Run from the repository root: python -m graph_mf --backend memory smoke."""
import argparse
import json
import sys
from . import __version__
from .backends import MemoryBackend, Neo4jBackend, QUERIES
from .dataset import load_tiny


def main(argv=None):
    parser = argparse.ArgumentParser(description="Exact and fixed-fidelity graph COUNT experiments")
    parser.add_argument("--backend", choices=("memory", "neo4j"), default="memory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="Idempotently load the tiny dataset")
    commands.add_parser("smoke", help="Check existing data against the tiny fixture; does not seed Neo4j")
    count = commands.add_parser("count")
    count.add_argument("query", choices=QUERIES)
    count.add_argument("--city")
    count.add_argument("--min-age", type=int)
    benchmark = commands.add_parser("benchmark", help="Matched synthetic fixed-fidelity experiment")
    benchmark.add_argument("--nodes", type=int, default=50000)
    benchmark.add_argument("--avg-degree", type=int, default=6)
    benchmark.add_argument("--graph-seed", type=int, default=42)
    benchmark.add_argument("--repeats", type=int, default=20)
    benchmark.add_argument("--warmups", type=int, default=2)
    benchmark.add_argument("--output", default="results/local/benchmark")
    reuse = commands.add_parser("reuse-benchmark", help="Repeated read-only queries over reusable samples")
    reuse.add_argument("--epochs", type=int, default=20)
    reuse.add_argument("--requests", type=int, default=100)
    reuse.add_argument("--warmups", type=int, default=2)
    reuse.add_argument("--output", default="results/local/reuse-benchmark")
    build = commands.add_parser("sample-build", help="Build, attach or explicitly refresh a reusable sample")
    build.add_argument("--refresh", action="store_true")
    build.add_argument("--import-graph", action="store_true", help="Import once; invalidates any existing sample")
    sample_count = commands.add_parser("sample-count", help="Read-only request over a persisted Neo4j sample")
    sample_count.add_argument("--fidelity", type=float, default=0.1)
    sample_count.add_argument("--country", default="FR")
    for command in (reuse, build, sample_count):
        command.add_argument("--nodes", type=int, default=50000)
        command.add_argument("--avg-degree", type=int, default=6)
        command.add_argument("--graph-seed", type=int, default=42)
        command.add_argument("--sample-seed", type=int, default=1000)
    args = parser.parse_args(argv)
    backend = None
    try:
        if args.command == "reuse-benchmark":
            from .reuse_benchmark import run_reuse_benchmark
            result = run_reuse_benchmark(args.backend, args.nodes, args.avg_degree, args.graph_seed,
                args.epochs, args.requests, args.warmups, args.sample_seed, args.output)
            print(json.dumps({"output": result["output"], "summary": result["summary"]}, indent=2))
            return 0
        if args.command in ("sample-build", "sample-count"):
            from .reusable import sample_operation
            result = sample_operation(args.backend, args.command, args.nodes, args.avg_degree,
                args.graph_seed, args.sample_seed, getattr(args, 'fidelity', 0.1),
                getattr(args, 'country', 'FR'), getattr(args, 'refresh', False),
                getattr(args, 'import_graph', False))
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "benchmark":
            from .benchmark import run_benchmark
            result = run_benchmark(args.backend, args.nodes, args.avg_degree, args.graph_seed,
                                   args.repeats, args.warmups, args.output)
            print(json.dumps({"output": result["output"], "summary": result["summary"]}, indent=2))
            return 0
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
