import os
import unittest
from unittest.mock import patch
from graph_mf.backends import Neo4jBackend
from graph_mf.reusable import ReusableSample
from graph_mf.reuse_benchmark import summarize_reuse
from graph_mf.synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j

try:
    import numpy as np
except ImportError:
    np = None


@unittest.skipIf(np is None, 'Install experiment dependencies')
class ReusableTests(unittest.TestCase):
    def test_repeated_requests_and_attach_do_not_prepare_again(self):
        backend = SyntheticMemory(generate_graph(100))
        cache = ReusableSample(backend)
        first = cache.build(1000)
        ranks = backend.sample.copy()
        with patch.object(backend, 'prepare', side_effect=AssertionError('Unexpected rebuild')):
            self.assertTrue(cache.build(1000)['reused'])
            for _ in range(5):
                result = cache.counts(fidelity=0.5)
                self.assertGreaterEqual(result['request_ms'], result['query_ms'])
        np.testing.assert_array_equal(ranks, backend.sample)
        self.assertFalse(first['reused'])

    def test_failed_build_is_rejected_and_can_be_rebuilt(self):
        backend = SyntheticMemory(generate_graph(100))
        cache = ReusableSample(backend)
        with patch.object(backend, 'prepare', side_effect=RuntimeError('Interrupted write')):
            with self.assertRaises(RuntimeError):
                cache.build(1000)
        self.assertEqual(cache.read_state()['status'], 'failed')
        with self.assertRaises(RuntimeError):
            cache.attach(1000)
        cache.build(1000)
        self.assertEqual(cache.read_state()['status'], 'ready')
        self.assertGreater(cache.counts()['node_count'], 0)

    def test_direct_overwrite_and_explicit_refresh(self):
        backend = SyntheticMemory(generate_graph(100))
        cache = ReusableSample(backend)
        first = cache.build(1000)
        backend.prepare(1001)
        with self.assertRaises(RuntimeError):
            cache.counts(fidelity=0.5)
        second = cache.build(1000)
        self.assertFalse(second['reused'])
        self.assertNotEqual(first['generation'], second['generation'])
        third = cache.build(1000, refresh=True)
        self.assertNotEqual(second['generation'], third['generation'])

    def test_amortization_and_independent_error_accounting(self):
        rows = []
        for f in [0.1, 0.25, 0.5, 0.75, 1]:
            for epoch in range(2):
                for request in range(2):
                    rows.append(dict(fidelity=f, epoch=epoch, request_index=request,
                        request_ms=5 if f == 1 else 2, state_check_ms=0.5,
                        node_error=0.1*epoch, edge_error=0.2*epoch))
        summary = summarize_reuse(rows, [{'build_ms': 12}, {'build_ms': 12}], 2)
        self.assertEqual(summary[0]['amortized_ms_per_request'], 8)
        self.assertEqual(summary[0]['modeled_break_even_requests'], 4)
        self.assertEqual(summary[0]['independent_sample_epochs'], 2)
        self.assertEqual(summary[0]['timed_requests'], 4)
        self.assertEqual(summary[0]['node_error_mean'], 0.05)
        self.assertEqual(summary[-1]['amortized_ms_per_request'], 5)


@unittest.skipUnless(os.environ.get('RUN_NEO4J_TESTS') == '1', 'Live Neo4j opt-in required')
class LiveReusableTests(unittest.TestCase):
    def test_persisted_sample_attaches_in_new_connection_without_rank_writes(self):
        graph = generate_graph(30, avg_degree=6, seed=9691)
        connection = Neo4jBackend()
        second_connection = None
        try:
            backend = SyntheticNeo4j(graph, connection, batch_size=10)
            backend.seed()
            first = ReusableSample(backend)
            built = first.build(123)
            second_connection = Neo4jBackend()
            second_backend = SyntheticNeo4j(graph, second_connection)
            second = ReusableSample(second_backend)
            self.assertEqual(second.attach(123)['generation'], built['generation'])
            reference = SyntheticMemory(graph)
            reference.prepare(123)
            expected = reference.counts(fidelity=0.5)
            with patch.object(second_backend, 'prepare', side_effect=AssertionError('Unexpected rank writes')):
                self.assertTrue(second.build(123)['reused'])
                for _ in range(3):
                    actual = second.counts(fidelity=0.5)
                    for key in ['node_count', 'edge_count']:
                        self.assertEqual(actual[key], expected[key])
                    for kind in ('node', 'edge'):
                        self.assertEqual(second.count_component('FR', .5, kind)['count'], expected[kind+'_count'])
            first.build(124, refresh=True)
            with self.assertRaises(RuntimeError):
                second.counts(fidelity=0.5)
            with self.assertRaises(RuntimeError):
                second.count_component('FR', .5, 'edge')
        finally:
            if second_connection:
                second_connection.close()
            connection.close()

    def test_partial_write_failure_and_reimport_invalidate_ready_state(self):
        graph = generate_graph(30, seed=9692)
        connection = Neo4jBackend()
        try:
            backend = SyntheticNeo4j(graph, connection, batch_size=10)
            backend.seed()
            cache = ReusableSample(backend)
            cache.build(123)
            original = backend.write_batches
            def fail_after_partial_write(query, rows):
                original(query, rows[:2])
                raise RuntimeError('Simulated interruption after first rank batch')
            with patch.object(backend, 'write_batches', side_effect=fail_after_partial_write):
                with self.assertRaises(RuntimeError):
                    cache.build(124, refresh=True)
            self.assertEqual(cache.read_state()['status'], 'failed')
            with self.assertRaises(RuntimeError):
                cache.attach(124)
            cache.build(124, refresh=True)
            self.assertEqual(cache.read_state()['status'], 'ready')
            backend.seed()
            with self.assertRaises(RuntimeError):
                cache.counts(fidelity=0.5)
        finally:
            connection.close()
