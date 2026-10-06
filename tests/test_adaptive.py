from types import SimpleNamespace
import unittest
from graph_mf.adaptive import AdaptiveController, LEVELS, calibrate
from graph_mf.synthetic import generate_graph


def profile():
    levels = [dict(fidelity=f, node_gain=1.0, edge_gain=1.0,
                   node_bound=0.008*(1-f)/f, edge_bound=0.02*(1-f)/f) for f in LEVELS]
    return dict(algorithm='calibrated-aggregate-scaling-v1', graph_sha256='fixture',
                countries=['FR'], levels=levels)


class FakeCache:
    fingerprint = 'fixture'
    active_state = dict(generation='first')
    def __init__(self, sparse=False):
        self.calls = []
        self.sparse = sparse
    def counts(self, country, fidelity):
        self.calls.append(fidelity)
        if self.sparse and fidelity < 1:
            return dict(node_count=0, edge_count=0, request_ms=1)
        return dict(node_count=int(1000*fidelity), edge_count=int(10000*fidelity**2), request_ms=1)


class AdaptiveTests(unittest.TestCase):
    def test_initial_draft_is_charged_and_tightening_is_immediate(self):
        cache = FakeCache()
        controller = AdaptiveController(profile())
        first = controller.request(cache, tier='performance')
        self.assertEqual(first['steps'][0]['fidelity'], 0.05)
        self.assertGreater(first['queries'], 1)
        self.assertLessEqual(first['node_bound'], 0.05)
        tight = controller.request(cache, tier='quality')
        self.assertGreater(tight['fidelity'], first['fidelity'])
        self.assertLessEqual(tight['edge_bound'], 0.02)

    def test_relaxing_budget_requires_three_consecutive_requests(self):
        controller, cache = AdaptiveController(profile()), FakeCache()
        quality = controller.request(cache, tier='quality')['fidelity']
        self.assertEqual(controller.request(cache, tier='performance')['fidelity'], quality)
        self.assertEqual(controller.request(cache, tier='performance')['fidelity'], quality)
        self.assertLess(controller.request(cache, tier='performance')['fidelity'], quality)

    def test_sparse_samples_and_unknown_scope_fall_back_to_exact(self):
        cache = FakeCache(sparse=True)
        result = AdaptiveController(profile()).request(cache, tier='performance')
        self.assertEqual(result['fidelity'], 1)
        self.assertEqual(result['node_estimate'], 1000)
        for country, fingerprint in [('XX', 'fixture'), ('FR', 'different')]:
            cache = FakeCache()
            cache.fingerprint = fingerprint
            result = AdaptiveController(profile()).request(cache, country=country)
            self.assertEqual(cache.calls, [1])
            self.assertFalse(result['compatible_profile'])

    def test_exact_bypasses_draft_and_generation_change_resets_history(self):
        controller, cache = AdaptiveController(profile()), FakeCache()
        self.assertEqual(controller.request(cache, tier='exact')['queries'], 1)
        self.assertEqual(cache.calls, [1])
        cache.active_state = dict(generation='second')
        result = controller.request(cache, tier='performance')
        self.assertEqual(result['steps'][0]['fidelity'], 0.05)

    def test_correction_and_interval_do_not_read_ground_truth(self):
        model, cache = profile(), FakeCache()
        for row in model['levels'][:-1]:
            row['node_gain'] = 1.03
        result = AdaptiveController(model).request(cache, tier='performance')
        self.assertAlmostEqual(result['node_estimate'], 1.03*result['raw_node_estimate'])
        low, high = result['node_interval']
        self.assertLessEqual(low, result['node_estimate'])
        self.assertGreaterEqual(high, result['node_estimate'])
        with self.assertRaises(ValueError):
            AdaptiveController(model).request(cache, budgets=(-1, 0))

    def test_disjoint_fit_calibration_and_epoch_level_maximum(self):
        model = calibrate(generate_graph(500), fit_epochs=2, calibration_epochs=20)
        self.assertFalse(set(model['fitting_seeds']) & set(model['calibration_seeds']))
        self.assertEqual(len(model['calibration_scores']), 20)
        self.assertEqual(model['joint_quantile'], max(model['calibration_scores']))
        self.assertEqual(model['levels'][-1]['edge_bound'], 0)
        self.assertNotIn('truth', model)

    def test_cached_and_amortized_planning_have_explicit_different_costs(self):
        model = profile()
        model['build_ms_mean'] = 10000
        model['timing'] = {'FR': {str(f): {'request_ms_mean': 50 if f == 1 else 10}
                                  for f in LEVELS}}
        amortized = AdaptiveController(model).request(FakeCache(), tier='performance')
        cached = AdaptiveController(model, cost_policy='cached').request(FakeCache(), tier='performance')
        self.assertEqual(amortized['fidelity'], 1)
        self.assertLess(cached['fidelity'], 1)


if __name__ == '__main__':
    unittest.main()
