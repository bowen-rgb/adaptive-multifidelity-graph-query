import tempfile
import unittest
from pathlib import Path
from graph_mf.public_graph import load_snap
from graph_mf.synthetic import generate_graph, SyntheticMemory
from graph_mf.split_policy import SplitController, policy_scores, choose
from graph_mf.adaptive import LEVELS
from graph_mf.deep_benchmark import summarize_requests


def model():
    return dict(graph_sha256='fixture', countries=['FR'],
        levels=[dict(fidelity=f, node_gain=1., edge_gain=1.,
                     node_bound=.008*(1-f)/f, edge_bound=.04*(1-f)/f) for f in LEVELS],
        component_timing={'FR': {k: {str(f): f for f in LEVELS} for k in ('node', 'edge')}})


class Cache:
    fingerprint = 'fixture'
    active_state = {'generation': 'one'}
    def count_component(self, predicate, fidelity, kind):
        return dict(count=int(10000*fidelity**(1 if kind == 'node' else 2)), request_ms=1)


class DeepTests(unittest.TestCase):
    def test_public_remaps_canonical_edges_and_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'edges.txt'
            path.write_text('# fixture\n30 10\n20 30\n')
            graph, provenance = load_snap(path)
            self.assertEqual(graph.src.tolist(), [0, 1])
            self.assertEqual(graph.dst.tolist(), [2, 2])
            self.assertEqual(provenance['nodes'], 3)
            self.assertEqual(set(graph.countries), {'degree_0_9'})
            path.write_text('10 30\n30 10\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                load_snap(path)

    def test_component_counts_match_paired_counts(self):
        backend = SyntheticMemory(generate_graph(300))
        backend.prepare(123)
        for f in LEVELS:
            both = backend.counts('FR', f)
            for kind in ('node', 'edge'):
                self.assertEqual(backend.count_component('FR', f, kind)['count'], both[kind+'_count'])

    def test_independent_fidelities_initial_draft_and_tightening(self):
        controller = SplitController(model())
        result = controller.request(Cache(), 'FR', 'performance')
        self.assertEqual(result['steps'][0]['fidelity'], .05)
        self.assertNotEqual(result['node_fidelity'], result['edge_fidelity'])
        self.assertEqual(len(policy_scores(model(), 'FR')), 64)
        tighter = controller.request(Cache(), 'FR', 'quality')
        self.assertGreater(tighter['node_fidelity'], result['node_fidelity'])
        self.assertGreater(tighter['edge_fidelity'], result['edge_fidelity'])

    def test_hysteresis_and_unknown_predicate_exact(self):
        controller, cache = SplitController(model()), Cache()
        high = controller.request(cache, 'FR', 'quality')
        for _ in range(2):
            result = controller.request(cache, 'FR', 'performance')
            self.assertEqual(result['node_fidelity'], high['node_fidelity'])
        self.assertLess(controller.request(cache, 'FR', 'performance')['node_fidelity'], high['node_fidelity'])
        result = controller.request(cache, 'unknown', 'performance')
        self.assertEqual((result['node_fidelity'], result['edge_fidelity']), (1, 1))
        self.assertEqual(len(result['steps']), 2)

    def test_restricted_optimizer_front_falls_back_without_oracle(self):
        scores = policy_scores(model(), 'FR')
        self.assertEqual(choose(scores, (0, 0), [(.05, .05)]), (1., 1.))

    def test_build_cost_only_when_stream_used_sample_including_discarded_draft(self):
        rows = [dict(mode=mode, tier='performance', epoch=e, node_fidelity=1.,
            edge_fidelity=1., count_calls=4 if mode == 'adaptive' else 2,
            request_ms=10., node_error=0., edge_error=0., violation=False)
            for e in range(2) for mode in ('exhaustive', 'adaptive')]
        results = summarize_requests(rows, [dict(epoch=e, build_ms=100.) for e in range(2)], 10)
        all_tiers = {r['mode']: r for r in results if r['tier'] == 'all'}
        self.assertEqual(all_tiers['exhaustive']['with_build_ms_mean'], 10.)
        self.assertEqual(all_tiers['adaptive']['with_build_ms_mean'], 20.)


if __name__ == '__main__':
    unittest.main()
