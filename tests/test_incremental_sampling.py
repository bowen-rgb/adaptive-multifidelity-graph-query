import unittest
from graph_mf.synthetic import generate_graph,SyntheticMemory
from graph_mf.reusable import ReusableSample
from graph_mf.incremental_sampling import IncrementalCounter,HistorySampler


class IncrementalTests(unittest.TestCase):
    def test_deltas_match_direct_counts_and_reject_overwritten_rank(self):
        graph=generate_graph(300,avg_degree=20)
        backend=SyntheticMemory(graph); sample=ReusableSample(backend); sample.build(42)
        for kind in ('node','edge'):
            for country in ('FR','DE'):
                counter=IncrementalCounter(sample,country,kind)
                for f in (.05,.1,.25,.5,.75,1.):
                    measured=counter.probe(f)
                    self.assertEqual(measured['count'],backend.count_component(country,f,kind)['count'])
                with self.assertRaises(ValueError): counter.probe(.5)
        counter=IncrementalCounter(sample,'FR','edge'); backend.prepare(44)
        with self.assertRaises(RuntimeError): counter.probe(.1)
        sample.build(45,refresh=True)
        counter=IncrementalCounter(sample,'FR','edge'); counter.probe(.1)
        sample.build(46,refresh=True)
        with self.assertRaises(RuntimeError): counter.probe(.25)

    def test_history_delays_lower_probe_and_zero_error_budget_is_immediate(self):
        graph=generate_graph(300,avg_degree=20)
        backend=SyntheticMemory(graph); sample=ReusableSample(backend); sample.build(42)
        target=backend.count_component('FR',1,'node')['count']
        profile=dict(graph_sha256=graph.fingerprint,countries=['FR'],components=[
            dict(kind='node',fidelity=f,gain=1.,forecast_ms=f,raw_bound=bound,
                 raw_count_score=bound,reference_sample_count=target*f)
            for f,bound in [(.1,.2),(.5,.01),(1.,0.)]])
        controller=HistorySampler(profile,sample,min_count=0)
        for _ in range(3):
            self.assertEqual(controller.request('FR','node',.05)['attempts'],1)
        result=controller.request('FR','node',.05)
        self.assertEqual([r['fidelity'] for r in result['trace']],[.1,.5])
        exact=controller.request('FR','node',0)
        self.assertEqual(exact['fidelity'],1)
        self.assertEqual(exact['estimate'],target)
        self.assertEqual(exact['attempts'],1)
        unknown=controller.request('ES','node',.2)
        self.assertEqual(unknown['fidelity'],1)
