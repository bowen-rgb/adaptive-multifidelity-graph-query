import unittest
from graph_mf.sample_correction import fit_profile, fit_joint_profile, answer, DynamicSampler


class CorrectionTests(unittest.TestCase):
    def test_joint_calibration_accounts_for_other_components(self):
        fit,cal=self.fixture()
        for row in cal:
            if row['seed'] in (10,11) and row['kind']=='node' and row['fidelity']==.5:
                row['truth']=200
        marginal=fit_profile(fit,cal,[.5,1.],['FR'],'abc')
        joint=fit_joint_profile(fit,cal,[.5,1.],['FR'],'abc')
        old=next(r for r in marginal['components'] if r['kind']=='edge' and r['fidelity']==.5)
        new=next(r for r in joint['components'] if r['kind']=='edge' and r['fidelity']==.5)
        self.assertGreater(new['raw_count_score'],old['raw_count_score'])
        self.assertEqual(new['gain'],old['gain'])
        self.assertEqual(joint['calibration_mode'],'joint_seed_maximum')
        self.assertTrue(all(r['raw_count_score']==0 for r in joint['components'] if r['fidelity']==1))

    def fixture(self):
        def rows(seeds):
            return [dict(seed=s,country='FR',kind=k,fidelity=f,count=(100 if f==1 else 10),
                         truth=100,query_ms=(2 if f==1 else 1))
                    for s in seeds for k in ('node','edge') for f in (.5,1.)]
        return rows([1,2]),rows(range(10,30))

    def test_correction_uses_fit_only_and_overlap_is_rejected(self):
        fit,cal=self.fixture()
        profile=fit_profile(fit,cal,[.5,1.],['FR'],'abc')
        row=next(r for r in profile['components'] if r['kind']=='node' and r['fidelity']==.5)
        self.assertEqual(row['gain'],5)
        self.assertEqual(row['corrected_bound'],0)
        self.assertAlmostEqual(row['raw_bound'],.8)
        cal[0]['truth']=200
        changed=fit_profile(fit,cal,[.5,1.],['FR'],'abc')
        self.assertEqual(changed['components'][0]['gain'],profile['components'][0]['gain'])
        cal[0]['seed']=1
        with self.assertRaises(ValueError):
            fit_profile(fit,cal,[.5,1.],['FR'],'abc')

    def test_unknown_scope_and_sparse_samples_charge_exact_fallback(self):
        fit,cal=self.fixture(); profile=fit_profile(fit,cal,[.5,1.],['FR'],'abc')
        class Backend:
            class graph:
                fingerprint='abc'
            def __init__(self): self.calls=[]
            def count_component(self,country,f,kind):
                self.calls.append(f)
                return dict(count=100 if f==1 else 10,query_ms=1)
        backend=Backend()
        result=answer(profile,backend,'FR','node',.05)
        self.assertEqual(backend.calls,[.5,1.])
        self.assertEqual(result['query_ms'],2)
        self.assertEqual(result['estimate'],100)
        backend=Backend(); answer(profile,backend,'ES','node',.05)
        self.assertEqual(backend.calls,[1.])

    def test_dynamic_uncertainty_escalates_without_reading_exact_truth(self):
        fit,cal=self.fixture(); profile=fit_profile(fit,cal,[.5,1.],['FR'],'abc')
        for row in profile['components']:
            if row['fidelity']<1:
                row['corrected_count_score']=.1
        class Backend:
            class graph:
                fingerprint='abc'
            def __init__(self,count): self.count=count; self.calls=[]
            def count_component(self,country,f,kind):
                self.calls.append(f)
                return dict(count=self.count if f<1 else 100,query_ms=1)
        confident=Backend(100)
        self.assertEqual(DynamicSampler(profile,confident).request('FR','node',.05)['attempts'],1)
        self.assertEqual(confident.calls,[.5])
        uncertain=Backend(20)
        self.assertEqual(DynamicSampler(profile,uncertain).request('FR','node',.05)['attempts'],2)
        self.assertEqual(uncertain.calls,[.5,1.])
        sparse=Backend(0)
        result=DynamicSampler(profile,sparse).request('FR','node',.05)
        self.assertEqual(sparse.calls,[.5,1.])
        self.assertEqual(result['query_ms'],2)
        self.assertEqual(result['fidelity'],1)
