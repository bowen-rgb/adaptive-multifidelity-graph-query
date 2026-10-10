import unittest
from graph_mf.parameter_sampling import topology_graph,RangeQuery,RangeCounter,ParameterSampler
from graph_mf.synthetic import SyntheticMemory
from graph_mf.reusable import ReusableSample


class ParameterSamplingTests(unittest.TestCase):
    def test_topologies_preserve_population_edges_and_change_concentration(self):
        graphs=[topology_graph(t,2000) for t in ('uniform','community','hub')]
        for graph in graphs[1:]:
            self.assertEqual(len(graph.src),len(graphs[0].src))
            self.assertTrue((graph.countries==graphs[0].countries).all())
            self.assertFalse((graph.src==graph.dst).any())
        self.assertEqual(len({g.fingerprint for g in graphs}),3)

    def test_range_counts_use_both_endpoints_and_reject_old_generation(self):
        graph=topology_graph('community',2000);backend=SyntheticMemory(graph)
        sample=ReusableSample(backend);sample.build(5)
        counter=RangeCounter(backend,sample);q=RangeQuery('FR',100,1500)
        selected=[i for i in range(100,1500) if graph.countries[i]=='FR' and backend.sample[i]<.5]
        chosen=set(selected)
        expected=sum(int(a) in chosen and int(b) in chosen for a,b in zip(graph.src,graph.dst))
        self.assertEqual(counter.count(q,.5,'node')['count'],len(selected))
        self.assertEqual(counter.count(q,.5,'edge')['count'],expected)
        sample.build(6,refresh=True)
        with self.assertRaises(RuntimeError):counter.count(q,.5,'edge')
        self.assertGreaterEqual(counter.count(q,1,'edge')['count'],expected)

    def test_unknown_country_and_small_range_are_exact(self):
        graph=topology_graph('uniform',2000);backend=SyntheticMemory(graph)
        sample=ReusableSample(backend);sample.build(5)
        counter=RangeCounter(backend,sample)
        profile=dict(graph_sha256=graph.fingerprint,components=[dict(kind=k,fidelity=f,
            raw_bound=0.,raw_count_score=0.,reference_sample_count=100) for k in ('node','edge') for f in (.1,1)])
        sampler=ParameterSampler(profile,counter)
        for q in (RangeQuery('ES',0,2000),RangeQuery('FR',0,10)):
            result=sampler.request(q,'node',.2)
            self.assertEqual(result['fidelity'],1)
            self.assertEqual(result['estimate'],counter.count(q,1,'node')['count'])
        profile['graph_sha256']='changed'
        with self.assertRaises(ValueError):ParameterSampler(profile,counter)

    def test_cost_guard_avoids_predicted_unprofitable_probe(self):
        graph=topology_graph('uniform',2000);backend=SyntheticMemory(graph)
        sample=ReusableSample(backend);sample.build(5)
        profile=dict(graph_sha256=graph.fingerprint,components=[dict(kind='node',fidelity=f,
            raw_bound=0.,raw_count_score=0.,reference_sample_count=100,
            forecast_ms=2 if f<1 else 1) for f in (.5,1.)])
        sampler=ParameterSampler(profile,RangeCounter(backend,sample),cost_guard=True)
        result=sampler.request(RangeQuery('FR',0,2000),'node',.2)
        self.assertEqual(result['fidelity'],1)
        self.assertEqual(result['attempts'],1)
