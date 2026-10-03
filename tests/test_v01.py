"""Regression checks on the original code; archived results are never overwritten."""
import importlib.util
from pathlib import Path
import unittest
import sys

try:
    import numpy as np
    import pandas
except ImportError:
    np = None


@unittest.skipIf(np is None, "Install v0.1/requirements.txt to check legacy experiments")
class LegacyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "v0.1/src/multifidelity.py"
        spec = importlib.util.spec_from_file_location("legacy_multifidelity", path)
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        spec.loader.exec_module(cls.module)

    def test_exact_and_full_fidelity_on_known_graph(self):
        m = self.module
        graph = m.GraphData(np.array(["FR", "FR", "DE"]), np.array([0, 1, 0]), np.array([1, 2, 2]))
        exact = m.exact_queries(graph)
        self.assertEqual((exact["node_count"], exact["edge_count"]), (2, 1))
        sampled = m.sampled_queries(graph, 1.0)
        self.assertEqual((sampled["node_est"], sampled["edge_est"]), (2.0, 1.0))
        selected = m.adaptive_fidelity_controller(graph, levels=(1.0,))
        self.assertEqual(selected["chosen_fidelity"], 1.0)
        self.assertEqual(selected["estimated_count"], 2.0)

    def test_deterministic_sampling_and_experiment(self):
        m = self.module
        graph = m.generate_graph(n_nodes=200, seed=42)
        a, b = [m.sampled_queries(graph, 0.5, seed=7) for _ in range(2)]
        self.assertEqual(a["node_est"], b["node_est"])
        self.assertEqual(a["edge_est"], b["edge_est"])
        exact, raw, summary = m.run_fixed_fidelity_experiment(graph, repeats=2)
        self.assertEqual(len(raw), 10)
        self.assertEqual(len(summary), 5)
        self.assertTrue((raw.loc[raw.fidelity == 1, ["node_error", "edge_error"]] == 0).all().all())
