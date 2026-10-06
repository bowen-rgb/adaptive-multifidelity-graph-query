import unittest
from types import SimpleNamespace
from copy import deepcopy
from graph_mf.audit import AuditedSession
from test_deep import model


def profile():
    p = model()
    p.update(algorithm='calibrated-aggregate-scaling-v1', fitting_seeds=list(range(20000, 20020)),
             calibration_seeds=list(range(21000, 21040)))
    return p


class Backend:
    name = 'memory'
    graph = SimpleNamespace(dataset='fixture', fingerprint='fixture')
    sample_generation = 0
    def prepare(self, seed):
        self.sample_generation += 1
    def count_component(self, predicate, fidelity, kind):
        total = 1000 if kind == 'node' else 10000
        return dict(count=round(total*fidelity**(1 if kind == 'node' else 2)), query_ms=.001)


class AuditTests(unittest.TestCase):
    def session(self, **kwargs):
        return AuditedSession(Backend(), profile(), 0, 1000, mode='cached',
                              timing_factor=1e9, **kwargs)

    def test_audit_failure_serves_anchor_and_quarantines_future_queries(self):
        s = self.session()
        for row in s.session.profile['levels'][:-1]:
            row['edge_gain'] *= 1.8
        result = s.request('FR', 'performance')
        self.assertTrue(result['audited'])
        self.assertEqual(result['reason'], 'error_budget')
        self.assertEqual(result['edge_estimate'], 10000)
        self.assertEqual(result['edge_fidelity'], 1.)
        self.assertEqual(len(result['steps']), len(result['candidate']['steps'])+2)
        after = s.request('FR', 'performance')
        self.assertEqual(len(after['steps']), 2)
        self.assertFalse(after['audited'])

    def test_periodic_audit_has_visible_blind_window(self):
        s = self.session(audit_every=5)
        self.assertTrue(s.request('FR', 'performance')['audited'])
        for row in s.session.profile['levels'][:-1]:
            row['edge_gain'] *= 1.8
        for _ in range(3):
            result = s.request('FR', 'performance')
            self.assertFalse(result['audited'])
            self.assertGreater(result['edge_estimate'], 15000)
        self.assertTrue(s.request('FR', 'performance')['quarantined'])

    def test_recovery_requires_disjoint_seeds_and_first_anchor(self):
        s = self.session()
        s.request('FR', 'performance')
        s.state, s.reason = 'quarantined', 'error_budget'
        leaked = profile()
        leaked['fitting_seeds'][0] = 25000
        with self.assertRaises(ValueError):
            s.refresh(leaked, 0, 26000)
        self.assertEqual(s.state, 'quarantined')
        s.refresh(profile(), 0, 26000)
        self.assertEqual(s.state, 'probing')
        self.assertTrue(s.request('FR', 'performance')['audited'])
        self.assertEqual(s.state, 'active')

    def test_timing_drift_needs_consecutive_observations(self):
        p = profile()
        for kind in p['component_timing']['FR'].values():
            for f in kind:
                kind[f] = 1e-9
        s = AuditedSession(Backend(), p, 0, 1000, mode='cached', timing_patience=3)
        self.assertFalse(s.request('FR', 'performance')['quarantined'])
        self.assertFalse(s.request('FR', 'performance')['quarantined'])
        result = s.request('FR', 'performance')
        self.assertEqual(result['reason'], 'timing_drift')
        self.assertEqual(result['edge_fidelity'], 1.)

    def test_external_profile_mutation_cannot_change_active_model(self):
        p = profile()
        s = AuditedSession(Backend(), p, 0, 1000, mode='cached', timing_factor=1e9)
        p['levels'][1]['edge_gain'] = 999
        self.assertEqual(s.session.profile['levels'][1]['edge_gain'], 1.)

    def test_exact_only_refresh_stays_probing(self):
        s = self.session()
        s.refresh(profile(), 0, 26000)
        result = s.request('FR', 'exact')
        self.assertFalse(result['audited'])
        self.assertEqual(s.state, 'probing')
        self.assertFalse(any(e['event'] == 'recovered' for e in s.events))

    def test_invalidated_sample_falls_back_and_marks_incomplete_attempt(self):
        s = self.session()
        s.request('FR', 'performance')
        s.backend.sample_generation += 1
        result = s.request('FR', 'performance')
        self.assertEqual(result['reason'], 'sample_invalidated')
        self.assertEqual(result['edge_estimate'], 10000)
        self.assertTrue(result['failed_attempt'])
        self.assertFalse(result['query_count_complete'])
