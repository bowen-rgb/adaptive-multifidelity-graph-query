
from dataclasses import dataclass
from time import perf_counter
import numpy as np
import pandas as pd

@dataclass
class GraphData:
    countries: np.ndarray
    src: np.ndarray
    dst: np.ndarray

def generate_graph(n_nodes=50000, avg_degree=6, seed=42):
    """
    Lightweight synthetic graph generator.
    Nodes have a 'country' property. Edges are undirected pairs.
    The prototype is intentionally pure Python/NumPy so it can run without Neo4j.
    """
    rng = np.random.default_rng(seed)
    countries = rng.choice(
        np.array(["FR", "DE", "ES", "IT", "NL"]),
        size=n_nodes,
        p=[0.30, 0.20, 0.18, 0.17, 0.15],
    )
    n_edges = n_nodes * avg_degree // 2
    src = rng.integers(0, n_nodes, size=n_edges, endpoint=False)
    dst = rng.integers(0, n_nodes, size=n_edges, endpoint=False)
    mask = src != dst
    return GraphData(countries=countries, src=src[mask], dst=dst[mask])

def exact_queries(g: GraphData, country="FR"):
    t0 = perf_counter()
    node_mask = g.countries == country
    node_count = int(node_mask.sum())
    edge_mask = node_mask[g.src] & node_mask[g.dst]
    edge_count = int(edge_mask.sum())
    elapsed = perf_counter() - t0
    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "latency_s": elapsed,
    }

def sampled_queries(g: GraphData, fidelity: float, country="FR", seed=0):
    """
    Uniform node sampling.
    Q1: count country nodes -> Horvitz-Thompson style scaling by 1/f.
    Q2: count edges whose two endpoints are sampled country nodes -> scale by 1/f^2.
    """
    rng = np.random.default_rng(seed)
    n = len(g.countries)
    t0 = perf_counter()

    sample_mask = rng.random(n) < fidelity
    target = (g.countries == country) & sample_mask

    sample_node_count = int(target.sum())
    node_est = sample_node_count / fidelity

    sampled_edge_mask = target[g.src] & target[g.dst]
    sample_edge_count = int(sampled_edge_mask.sum())
    edge_est = sample_edge_count / (fidelity ** 2)

    elapsed = perf_counter() - t0
    return {
        "node_est": float(node_est),
        "edge_est": float(edge_est),
        "sample_nodes": int(sample_mask.sum()),
        "latency_s": elapsed,
    }

def rel_error(est, truth):
    if truth == 0:
        return 0.0 if est == 0 else np.inf
    return abs(est - truth) / truth

def run_fixed_fidelity_experiment(
    g: GraphData,
    fidelities=(0.10, 0.25, 0.50, 0.75, 1.00),
    repeats=20,
    country="FR",
):
    exact = exact_queries(g, country)
    rows = []
    for f in fidelities:
        for r in range(repeats):
            if f == 1.0:
                row = {
                    "fidelity": f,
                    "repeat": r,
                    "node_error": 0.0,
                    "edge_error": 0.0,
                    "latency_s": exact["latency_s"],
                    "sample_nodes": len(g.countries),
                }
            else:
                out = sampled_queries(g, f, country, seed=1000 + r)
                row = {
                    "fidelity": f,
                    "repeat": r,
                    "node_error": rel_error(out["node_est"], exact["node_count"]),
                    "edge_error": rel_error(out["edge_est"], exact["edge_count"]),
                    "latency_s": out["latency_s"],
                    "sample_nodes": out["sample_nodes"],
                }
            rows.append(row)
    raw = pd.DataFrame(rows)
    summary = raw.groupby("fidelity", as_index=False).agg(
        node_error_mean=("node_error", "mean"),
        edge_error_mean=("edge_error", "mean"),
        latency_ms_mean=("latency_s", lambda s: 1000 * s.mean()),
        latency_ms_std=("latency_s", lambda s: 1000 * s.std(ddof=0)),
        sample_nodes_mean=("sample_nodes", "mean"),
    )
    return exact, raw, summary

def adaptive_fidelity_controller(
    g: GraphData,
    target_rel_error=0.05,
    levels=(0.10, 0.25, 0.50, 0.75, 1.00),
    country="FR",
    seed=123,
):
    """
    Proof-of-concept controller:
    progressively increases fidelity and uses a normal-approximation confidence
    bound for the sampled node-count query. This is a heuristic baseline, not a
    claimed novel algorithm.
    """
    rng = np.random.default_rng(seed)
    n = len(g.countries)
    permutation = rng.permutation(n)
    z = 1.96

    for f in levels:
        if f == 1.0:
            exact = exact_queries(g, country)
            return {
                "chosen_fidelity": 1.0,
                "estimated_count": float(exact["node_count"]),
                "estimated_rel_uncertainty": 0.0,
                "sample_size": n,
            }

        m = max(2, int(round(f * n)))
        ids = permutation[:m]
        hits = int((g.countries[ids] == country).sum())
        p_hat = hits / m
        count_est = n * p_hat

        # Finite-population corrected standard error for a sampled proportion.
        fpc = np.sqrt((n - m) / (n - 1))
        se_p = np.sqrt(max(p_hat * (1 - p_hat), 1e-12) / m) * fpc
        half_width_count = z * n * se_p
        rel_uncertainty = half_width_count / max(count_est, 1.0)

        if rel_uncertainty <= target_rel_error:
            return {
                "chosen_fidelity": float(f),
                "estimated_count": float(count_est),
                "estimated_rel_uncertainty": float(rel_uncertainty),
                "sample_size": int(m),
            }

    raise RuntimeError("No fidelity level selected.")
