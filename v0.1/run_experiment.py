
from pathlib import Path
import sys
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from multifidelity import (
    generate_graph,
    run_fixed_fidelity_experiment,
    adaptive_fidelity_controller,
    rel_error,
)

g = generate_graph(n_nodes=50000, avg_degree=6, seed=42)
exact, raw, summary = run_fixed_fidelity_experiment(g)

raw.to_csv(ROOT / "results" / "raw_results.csv", index=False)
summary.to_csv(ROOT / "results" / "summary.csv", index=False)

adaptive_rows = []
for target in [0.10, 0.05, 0.02, 0.01]:
    out = adaptive_fidelity_controller(g, target_rel_error=target, seed=123)
    out["target_rel_error"] = target
    out["actual_rel_error"] = rel_error(out["estimated_count"], exact["node_count"])
    adaptive_rows.append(out)

adaptive = pd.DataFrame(adaptive_rows)
adaptive.to_csv(ROOT / "results" / "adaptive_results.csv", index=False)

# Chart 1: fidelity vs error
plt.figure(figsize=(7, 4.5))
plt.plot(summary["fidelity"], 100 * summary["node_error_mean"], marker="o", label="Node COUNT")
plt.plot(summary["fidelity"], 100 * summary["edge_error_mean"], marker="s", label="Edge COUNT")
plt.xlabel("Fidelity")
plt.ylabel("Mean relative error (%)")
plt.title("Accuracy–Fidelity Trade-off")
plt.legend()
plt.tight_layout()
plt.savefig(ROOT / "figures" / "error_vs_fidelity.png", dpi=180)
plt.close()

# Chart 2: fidelity vs latency
plt.figure(figsize=(7, 4.5))
plt.plot(summary["fidelity"], summary["latency_ms_mean"], marker="o")
plt.xlabel("Fidelity")
plt.ylabel("Mean latency (ms)")
plt.title("Latency–Fidelity Trade-off")
plt.tight_layout()
plt.savefig(ROOT / "figures" / "latency_vs_fidelity.png", dpi=180)
plt.close()

print("Exact query:", exact)
print("\nFixed-fidelity summary:")
print(summary.to_string(index=False))
print("\nAdaptive controller:")
print(adaptive.to_string(index=False))
