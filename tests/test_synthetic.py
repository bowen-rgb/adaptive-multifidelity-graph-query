import importlib.util
import os
from pathlib import Path
import sys
import unittest

from graph_mf.backends import Neo4jBackend
from graph_mf.benchmark import summarize, relative_error
from graph_mf.synthetic import generate_graph, SyntheticGraph, SyntheticMemory, SyntheticNeo4j

try:
    import numpy as np
except ImportError:
    np = None
try:
    import pandas
except ImportError:
    pandas = None


@unittest.skipIf(np is None, 'Install experiment dependencies')
class SyntheticTests(unittest.TestCase):
    @unittest.skipIf(pandas is None, 'Legacy comparison requires v0.1 pandas dependency')
    def test_generator_matches_preserved_v01(self):
        path = Path(__file__).resolve().parents[1] / 'v0.1/src/multifidelity.py'
        spec = importlib.util.spec_from_file_location('legacy_generator', path)
        legacy = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = legacy
        spec.loader.exec_module(legacy)
        original = legacy.generate_graph(n_nodes=200, avg_degree=6, seed=42)
        current = generate_graph(n_nodes=200, avg_degree=6, seed=42)
        for field in ['countries', 'src', 'dst']:
            np.testing.assert_array_equal(getattr(original, field), getattr(current, field))
        memory = SyntheticMemory(current)
        memory.prepare(1007)
        for f in [0.1, 0.25, 0.5, 0.75, 1]:
            before = legacy.sampled_queries(original, f, seed=1007)
            after = memory.counts(fidelity=f)
            self.assertEqual(before['node_est'], after['node_count'] / f)
            self.assertEqual(before['edge_est'], after['edge_count'] / f**2)

    def test_parallel_edges_and_direction_count_once_per_record(self):
        graph = SyntheticGraph(np.array(['FR', 'FR', 'DE']), np.array([0, 0, 1]), np.array([1, 1, 2]), 0, 2)
        memory = SyntheticMemory(graph)
        self.assertEqual(memory.counts()['node_count'], 2)
        self.assertEqual(memory.counts()['edge_count'], 2)
        memory.sample = np.array([0.1, 0.9, 0.2])
        self.assertEqual(memory.counts(fidelity=0.5)['node_count'], 1)
        self.assertEqual(memory.counts(fidelity=0.5)['edge_count'], 0)
        self.assertEqual(memory.counts(country='Missing')['node_count'], 0)

    def test_input_validation(self):
        for n, degree in [(1, 6), (20, -1)]:
            with self.assertRaises(ValueError):
                generate_graph(n, degree)
        memory = SyntheticMemory(generate_graph(20))
        for f in [0, -0.1, 1.1, float('nan')]:
            with self.assertRaises(ValueError):
                memory.counts(fidelity=f)
        self.assertEqual(relative_error(0, 0), 0)
        self.assertEqual(relative_error(11, 10), 0.1)

    def test_summary_uses_repeated_exact_measurements(self):
        rows = []
        for f in [0.1, 0.25, 0.5, 0.75, 1]:
            for timing in [2, 4]:
                rows.append(dict(fidelity=f, node_error=0, edge_error=0, query_ms=timing,
                                 preparation_ms=10 if f < 1 else 0,
                                 with_preparation_ms=timing + (10 if f < 1 else 0)))
        summary = summarize(rows)
        self.assertEqual(summary[-1]['query_ms_median'], 3)
        self.assertEqual(summary[-1]['query_ms_std'], 1)
        self.assertEqual(summary[0]['with_preparation_ms_median'], 13)


@unittest.skipUnless(os.environ.get('RUN_NEO4J_TESTS') == '1', 'Live Neo4j opt-in required')
class LiveSyntheticTests(unittest.TestCase):
    def test_parallel_edges_idempotent_import_and_sampling(self):
        graph = SyntheticGraph(np.array(['FR', 'FR', 'DE']), np.array([0, 0, 1]), np.array([1, 1, 2]), 0, 2)
        connection = Neo4jBackend()
        try:
            backend = SyntheticNeo4j(graph, connection, batch_size=2)
            backend.seed()
            backend.seed()
            reference = SyntheticMemory(graph)
            for seed in [3, 1000]:
                backend.prepare(seed)
                reference.prepare(seed)
                for f in [0.1, 0.5, 1]:
                    actual, expected = backend.counts(fidelity=f), reference.counts(fidelity=f)
                    for key in ['node_count', 'edge_count']:
                        self.assertEqual(actual[key], expected[key])
        finally:
            connection.close()
