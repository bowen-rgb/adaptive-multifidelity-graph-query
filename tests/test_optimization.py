import csv
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from graph_mf.optimization import (dominates, nondominated_sort, crowding_distance,
    nsga2, candidates_for_reuse, choose_candidate, load_measurements, run_optimization)


class OptimizationTests(unittest.TestCase):
    def test_known_fronts_duplicates_and_three_objectives(self):
        values = [(1, 3, 3), (2, 2, 2), (3, 1, 1), (3, 3, 3), (4, 4, 4), (1, 3, 3)]
        self.assertEqual([set(f) for f in nondominated_sort(values)],
                         [{0, 1, 2, 5}, {3}, {4}])
        self.assertFalse(dominates(values[0], values[5]))
        with self.assertRaises(ValueError):
            nondominated_sort([(1, 2), (3,)])
        with self.assertRaises(ValueError):
            nondominated_sort([(1, math.nan)])

    def test_crowding_normalization_and_constant_axis(self):
        values = [(0, 4, 7), (1, 3, 7), (2, 2, 7), (4, 0, 7)]
        distances = crowding_distance(values, list(range(4)))
        self.assertTrue(math.isinf(distances[0]))
        self.assertTrue(math.isinf(distances[3]))
        self.assertEqual(distances[1], 1)
        self.assertEqual(distances[2], 1.5)
        self.assertEqual(crowding_distance([(1, 1), (1, 1)], [0, 1]), {0: 0, 1: 0})

    def test_nsga2_determinism_and_independent_evaluation_cache(self):
        calls = []
        domain = list(range(20))
        def score(x):
            calls.append(x)
            return (x, 19 - x)
        first = nsga2(domain, score, population_size=12, generations=25, seed=17)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(first['unique_evaluations'], len(calls))
        second = nsga2(domain, lambda x: (x, 19 - x), 12, 25, 17)
        self.assertEqual(first, second)
        self.assertEqual(len(first['trace']), 26)
        self.assertTrue(set(first['front']).issubset(domain))
        self.assertGreater(len(first['front']), 2)

    def test_search_does_not_read_exhaustive_oracle_or_disguise_discovery(self):
        # With no variation, only the sampled categories can be evaluated.
        result = nsga2(list(range(50)), lambda x: (x, 49 - x), 2, 0, 0, 0)
        self.assertEqual(result['unique_evaluations'], 2)
        self.assertEqual(len(result['front']), 2)
        self.assertEqual(result['front'], result['discovered_front'])
        with self.assertRaises(ValueError):
            nsga2([1, 1], lambda x: (x,))

    def test_nsga2_rejects_dominated_solutions_after_elitist_selection(self):
        result = nsga2(list(range(12)), lambda x: (x, x), 12, 20, 7, 0.4)
        self.assertEqual(result['front'], [0])

    def test_reuse_is_fixed_and_budget_selection_is_empirical(self):
        records = [dict(fidelity=0.1, request_ms_mean=2, build_ms_mean=100,
                        node_error_mean=0.01, edge_error_mean=0.04),
                   dict(fidelity=1.0, request_ms_mean=10, build_ms_mean=0,
                        node_error_mean=0, edge_error_mean=0)]
        once = candidates_for_reuse(records, 1)
        reused = candidates_for_reuse(records, 100)
        self.assertEqual(once[0]['modeled_cost_ms'], 102)
        self.assertEqual(reused[0]['modeled_cost_ms'], 3)
        self.assertEqual(choose_candidate(once, 0.02, 0.05)['fidelity'], 1)
        self.assertEqual(choose_candidate(reused, 0.02, 0.05)['fidelity'], 0.1)
        self.assertEqual(choose_candidate(reused, 0, 0)['fidelity'], 1)
        self.assertIsNone(choose_candidate(reused[:1], 0, 0))
        with self.assertRaises(ValueError):
            candidates_for_reuse(records, 0)

    def test_completed_source_required_and_export_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source'
            source.mkdir()
            metadata = source / 'metadata.json'
            metadata.write_text(json.dumps(dict(status='running', all_counts_match_numpy=True)))
            with self.assertRaises(ValueError):
                load_measurements(source)
            metadata.write_text(json.dumps(dict(status='completed', all_counts_match_numpy=True,
                                                 backend='memory', graph_sha256='fixture')))
            with (source / 'summary.csv').open('w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(['fidelity', 'request_ms_mean', 'build_ms_mean',
                                 'node_error_mean', 'edge_error_mean'])
                writer.writerows([[0.1, 2, 100, 0.01, 0.04], [1, 10, 0, 0, 0]])
            output = Path(folder) / 'result'
            result = run_optimization(source, output, [1, 100], runs=2, generations=3)
            self.assertEqual(result['total_runs'], 4)
            self.assertFalse(result['new_neo4j_measurements'])
            self.assertEqual(len(result['source_sha256']['summary.csv']), 64)
            # Git newline conversion must not change recorded text provenance.
            summary = source / 'summary.csv'
            summary.write_bytes(summary.read_bytes().replace(b'\r\n', b'\n'))
            repeat = run_optimization(source, Path(folder) / 'repeat', [1, 100], runs=2, generations=3)
            self.assertEqual(result['source_sha256'], repeat['source_sha256'])
            from graph_mf.__main__ import main
            stream = io.StringIO()
            with redirect_stdout(stream):
                exit_code = main(['select-fidelity', '--source', str(source)])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stream.getvalue())['selected']['fidelity'], 0.1)
            with self.assertRaises(ValueError):
                run_optimization(source, output)


if __name__ == '__main__':
    unittest.main()
