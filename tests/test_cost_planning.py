import unittest
import os
from graph_mf.split_policy import SplitController, CostAwareSession, policy_scores, choose
from graph_mf.optimization import nsga2
from graph_mf.synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j
from graph_mf.backends import Neo4jBackend
from unittest.mock import patch
from test_deep import Cache, model


class CostPlanningTests(unittest.TestCase):
    def test_short_stream_skips_draft_and_long_stream_uses_independent_sample(self):
        p = model()
        short = SplitController(p, cost_policy='amortized', build_ms=100, reuse_requests=10)
        result = short.request(Cache(), 'FR', 'performance')
        self.assertEqual((result['node_fidelity'], result['edge_fidelity']), (1., 1.))
        self.assertEqual(len(result['steps']), 2)
        long = SplitController(p, cost_policy='amortized', build_ms=100, reuse_requests=1000)
        result = long.request(Cache(), 'FR', 'performance')
        self.assertLess(result['node_fidelity'], 1)
        self.assertLess(result['edge_fidelity'], 1)

    def test_single_shared_build_not_two_component_builds(self):
        cached = policy_scores(model(), 'FR')
        amortized = policy_scores(model(), 'FR', 100, 10)
        self.assertEqual(amortized[(.5, .5)][0]-cached[(.5, .5)][0], 10)
        self.assertEqual(amortized[(1., .5)][0]-cached[(1., .5)][0], 10)
        self.assertEqual(amortized[(1., 1.)][0], cached[(1., 1.)][0])
        self.assertEqual(choose(amortized, (.05, .15)), (1., 1.))

    def test_dedup_preserves_population_without_injecting_unseen_candidates(self):
        domain = list(range(64))
        result = nsga2(domain, lambda x: (x, 63-x), 32, 8, 7, 0,
                       eliminate_duplicates=True)
        # With mutation off, categorical inheritance cannot discover outside init.
        self.assertEqual(result['unique_evaluations'], 32)
        initial = set(result['trace'][0]['population'])
        for row in result['trace']:
            self.assertEqual(len(row['population']), len(set(row['population'])))
            self.assertEqual(set(row['population']), initial)
        with self.assertRaises(ValueError):
            nsga2([1, 2], lambda x: (x,), 3, eliminate_duplicates=True)

    def test_unique_search_retains_large_tradeoff_front(self):
        result = nsga2(list(range(50)), lambda x: (x, 49-x), 48, 40, 0, .35,
                       eliminate_duplicates=True)
        self.assertEqual(len(result['front']), 48)
        self.assertEqual(len(set(result['trace'][-1]['population'])), 48)
        self.assertEqual(result, nsga2(list(range(50)), lambda x: (x, 49-x),
                                     48, 40, 0, .35, eliminate_duplicates=True))

    def test_session_skips_materialization_and_builds_only_once_for_long_stream(self):
        backend = SyntheticMemory(generate_graph(5000))
        p = model()
        p['graph_sha256'] = backend.graph.fingerprint
        short = CostAwareSession(backend, p, 100, 10)
        with patch.object(backend, 'prepare', side_effect=AssertionError('Unnecessary materialization')):
            for _ in range(2):
                result = short.request('FR', 'performance')
                self.assertEqual(result['build_ms'], 0)
                self.assertEqual(result['node_fidelity'], 1.)
        long = CostAwareSession(backend, p, 100, 1000)
        with patch.object(backend, 'prepare', wraps=backend.prepare) as prepare:
            long.request('FR', 'performance')
            long.request('FR', 'performance')
            self.assertEqual(prepare.call_count, 1)

    def test_incompatible_session_uses_exact_without_constructing_sample(self):
        backend = SyntheticMemory(generate_graph(200))
        session = CostAwareSession(backend, model(), 100, 1000)
        with patch.object(backend, 'prepare', side_effect=AssertionError('Profile mismatch')):
            result = session.request('FR', 'performance')
            self.assertFalse(session.built)
            self.assertEqual(result['node_fidelity'], 1.)

    def test_explicit_exact_tier_skips_build_even_in_cached_mode(self):
        backend = SyntheticMemory(generate_graph(200))
        p = model()
        p['graph_sha256'] = backend.graph.fingerprint
        session = CostAwareSession(backend, p, 100, 1000, mode='cached')
        with patch.object(backend, 'prepare', side_effect=AssertionError('Exact needs no sample')):
            result = session.request('FR', 'exact')
            self.assertFalse(session.built)
            self.assertEqual(result['node_fidelity'], 1.)


@unittest.skipUnless(os.environ.get('RUN_NEO4J_TESTS') == '1', 'Live Neo4j opt-in required')
class LiveCostSessionTests(unittest.TestCase):
    def test_lazy_build_and_reuse_match_raw_reference(self):
        graph = generate_graph(2000, seed=9693)
        p = model()
        p['graph_sha256'] = graph.fingerprint
        connection = Neo4jBackend()
        try:
            backend = SyntheticNeo4j(graph, connection)
            backend.seed()
            short = CostAwareSession(backend, p, 100, 10)
            with patch.object(backend, 'prepare', side_effect=AssertionError('Unnecessary sample write')):
                self.assertEqual(short.request('FR', 'performance')['build_ms'], 0)
            long = CostAwareSession(backend, p, 100, 1000, sample_seed=12300)
            reference = SyntheticMemory(graph)
            reference.prepare(12300)
            with patch.object(backend, 'prepare', wraps=backend.prepare) as prepare:
                for _ in range(2):
                    result = long.request('FR', 'performance')
                    for step in result['steps']:
                        self.assertEqual(step['count'], reference.count_component('FR', step['fidelity'], step['kind'])['count'])
                self.assertEqual(prepare.call_count, 1)
        finally:
            connection.close()
