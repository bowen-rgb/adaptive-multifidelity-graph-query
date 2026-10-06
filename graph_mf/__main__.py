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
    energy_probe = commands.add_parser('energy-probe', help='Detect read-only CPU counters and distinguish GPU-only telemetry')
    energy_probe.add_argument('--output')
    energy = commands.add_parser('energy-benchmark', help='Energy/CPU-time instrumentation of matched COUNT streams')
    energy.add_argument('--source', default='results/neo4j/deep-v06/synthetic-50000')
    energy.add_argument('--epochs', type=int, default=3)
    energy.add_argument('--requests', type=int, default=30)
    energy.add_argument('--interval', type=float, default=.1)
    energy.add_argument('--idle-seconds', type=float, default=1.)
    energy.add_argument('--max-package-watts', type=float, default=500.)
    energy.add_argument('--output', default='results/local/energy-benchmark')
    audit = commands.add_parser('audit-benchmark', help='Periodic exact audit, fault containment and independent recovery')
    audit.add_argument('--source', default='results/neo4j/deep-v06/synthetic-50000')
    audit.add_argument('--epochs', type=int, default=3)
    audit.add_argument('--requests', type=int, default=60)
    audit.add_argument('--audit-every', type=int, default=10)
    audit.add_argument('--recovery-strategy', choices=('full', 'timing_only'), default='full')
    audit.add_argument('--output', default='results/local/audit-benchmark')
    cost = commands.add_parser('cost-benchmark', help='Lazy sample construction and cost-aware stream comparison')
    cost.add_argument('--source', default='results/neo4j/deep-v06/synthetic-50000')
    cost.add_argument('--epochs', type=int, default=3)
    cost.add_argument('--horizons', type=int, nargs='+', default=[75, 500])
    cost.add_argument('--output', default='results/local/cost-benchmark')
    deep = commands.add_parser('deep-benchmark', help='Public topology, scale/memory and same-path policy comparison')
    deep.add_argument('--sizes', type=int, nargs='*', default=[50000, 100000, 200000])
    deep.add_argument('--snap-path')
    deep.add_argument('--server-pid', type=int)
    deep.add_argument('--epochs', type=int, default=5)
    deep.add_argument('--repeats', type=int, default=3)
    deep.add_argument('--timing-epochs', type=int, default=3)
    deep.add_argument('--output', default='results/local/deep-benchmark')
    optimize = commands.add_parser("optimize", help="Offline Pareto/NSGA-II analysis of completed reuse measurements")
    optimize.add_argument("--source", default="results/neo4j/reuse-50k-v031")
    optimize.add_argument("--output", default="results/local/optimization")
    optimize.add_argument("--reuse-requests", type=int, nargs='+', default=[1, 10, 100, 1000])
    optimize.add_argument("--runs", type=int, default=30)
    optimize.add_argument("--population", type=int, default=8)
    optimize.add_argument("--generations", type=int, default=20)
    optimize.add_argument("--mutation-rate", type=float, default=0.2)
    selection = commands.add_parser("select-fidelity", help="Choose cheapest level satisfying recorded mean-error tolerances")
    selection.add_argument("--source", default="results/neo4j/reuse-50k-v031")
    selection.add_argument("--reuse-requests", type=int, default=100)
    selection.add_argument("--node-tolerance", type=float, default=0.02)
    selection.add_argument("--edge-tolerance", type=float, default=0.05)
    adaptive = commands.add_parser("adaptive-benchmark", help="Calibrate and measure held-out adaptive/fixed/exact requests")
    adaptive.add_argument("--nodes", type=int, default=50000)
    adaptive.add_argument("--epochs", type=int, default=15)
    adaptive.add_argument("--repeats-per-tier", type=int, default=4)
    adaptive.add_argument("--timing-epochs", type=int, default=5)
    adaptive.add_argument("--output", default="results/local/adaptive")
    adaptive.add_argument("--cost-policy", choices=("amortized", "cached"), default="amortized")
    adaptive.add_argument("--evaluation-seed", type=int, default=5000)
    adaptive.add_argument("--baseline-fidelities", type=float, nargs='*', default=[0.1, 0.25, 0.5, 0.75])
    adaptive_query = commands.add_parser("adaptive-query", help="Run a tier-controlled query using a saved profile")
    adaptive_query.add_argument("--profile", required=True)
    adaptive_query.add_argument("--tier", choices=("performance", "balanced", "quality", "exact"), default="balanced")
    adaptive_query.add_argument("--country", default="FR")
    adaptive_query.add_argument("--nodes", type=int, default=50000)
    adaptive_query.add_argument("--sample-seed", type=int, default=5014)
    adaptive_query.add_argument("--reuse-requests", type=int, default=100)
    adaptive_query.add_argument("--cost-policy", choices=("amortized", "cached"), default="amortized")
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
        if args.command == 'energy-probe':
            from .energy import probe_energy
            from pathlib import Path
            result, _ = probe_energy()
            payload = json.dumps(result, indent=2)+'\n'
            if args.output:
                path = Path(args.output)
                if path.exists():
                    raise ValueError('New probe output required')
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload, encoding='utf-8')
            print(payload)
            return 0
        if args.command == 'energy-benchmark':
            from .energy_benchmark import run_energy_benchmark
            print(json.dumps(run_energy_benchmark(args.source, args.output, args.backend, args.epochs,
                args.requests, args.interval, args.idle_seconds, args.max_package_watts), indent=2))
            return 0
        if args.command == 'audit-benchmark':
            from .audit_benchmark import run_audit_benchmark
            print(json.dumps(run_audit_benchmark(args.source, args.output, args.backend, args.epochs, args.requests,
                                                args.audit_every, args.recovery_strategy), indent=2))
            return 0
        if args.command == 'cost-benchmark':
            from .cost_benchmark import run_cost_benchmark
            print(json.dumps(run_cost_benchmark(args.source, args.output, args.backend, args.epochs, args.horizons), indent=2))
            return 0
        if args.command == 'deep-benchmark':
            from .deep_benchmark import run_suite
            result = run_suite(args.output, args.backend, args.sizes, args.snap_path,
                               args.server_pid, args.epochs, args.repeats, args.timing_epochs)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "adaptive-benchmark":
            from .adaptive_benchmark import run_adaptive_benchmark
            result = run_adaptive_benchmark(args.backend, args.nodes, args.epochs,
                args.repeats_per_tier, args.timing_epochs, args.output, cost_policy=args.cost_policy,
                evaluation_seed=args.evaluation_seed, baseline_fidelities=args.baseline_fidelities)
            print(json.dumps({"output": result['output'], "summary": result['summary']}, indent=2))
            return 0
        if args.command == "adaptive-query":
            from pathlib import Path
            from .adaptive import AdaptiveController
            from .reusable import ReusableSample
            from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j
            profile = json.loads(Path(args.profile).read_text(encoding='utf-8'))
            graph = generate_graph(args.nodes)
            if args.backend == 'neo4j':
                backend = Neo4jBackend()
                cache = ReusableSample(SyntheticNeo4j(graph, backend))
                if args.tier != 'exact':
                    cache.attach(args.sample_seed)
            else:
                cache = ReusableSample(SyntheticMemory(graph))
                if args.tier != 'exact':
                    cache.build(args.sample_seed)
            result = AdaptiveController(profile, cost_policy=args.cost_policy).request(cache, args.country, args.tier,
                                                         reuse_requests=args.reuse_requests)
            result.update(backend=args.backend, graph_sha256=cache.fingerprint,
                          sample_generation=cache.active_state['generation'] if cache.active_state else None)
            print(json.dumps(result, indent=2))
            return 0
        if args.command in ("optimize", "select-fidelity"):
            if args.backend != "memory":
                raise ValueError('Optimization analyzes recorded files offline; use --backend memory')
            if args.command == "select-fidelity":
                from .optimization import load_measurements, candidates_for_reuse, choose_candidate
                records, _ = load_measurements(args.source)
                selected = choose_candidate(candidates_for_reuse(records, args.reuse_requests),
                                            args.node_tolerance, args.edge_tolerance)
                print(json.dumps(dict(selected=selected, new_neo4j_measurements=False,
                    basis='recorded mean errors and modeled amortized cost; no per-query error guarantee'), indent=2))
                return 0 if selected else 1
            from .optimization import run_optimization
            result = run_optimization(args.source, args.output, args.reuse_requests,
                                      args.runs, args.population, args.generations, args.mutation_rate)
            print(json.dumps(result, indent=2))
            return 0
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
