import unittest
from graph_mf.ldbc_ic5_sampling import rank_rows, quality, choose_tier, calibrate_quality, IC5Views, adaptive_request


class IC5SamplingTests(unittest.TestCase):
    def test_invalid_sample_falls_back_exact_and_unknown_window_is_exact(self):
        class Views:
            def __init__(self):self.calls=[]
            def count(self,param,f,generation):
                self.calls.append(f)
                if f<1:raise RuntimeError('stale')
                return [],1
        profile=[dict(fidelity=.9,quality_score=0,forecast_ms=1),dict(fidelity=1.,quality_score=0,forecast_ms=100)]
        views=Views();answer,result=adaptive_request(views,dict(minDate=-1),profile,'old')
        self.assertEqual(answer,[]);self.assertEqual(views.calls,[.9,1.])
        self.assertEqual(result['trace'][0]['reason'],'stale')
        views=Views();adaptive_request(views,dict(minDate=0),profile,'old')
        self.assertEqual(views.calls,[1.])

    def test_duplicate_titles_do_not_hide_a_missing_forum(self):
        exact=[dict(forumId=1,forumName='same',postCount=20),dict(forumId=2,forumName='same',postCount=10)]
        metric=quality(exact,exact[:1])
        self.assertEqual(metric['recall'],.5)
        self.assertEqual(metric['max_count_error'],1.)

    def test_zero_groups_and_rank_loss_are_preserved(self):
        exact=[dict(forumId=1,postCount=0),dict(forumId=2,postCount=0)]
        metric=quality(exact,[exact[1],exact[0]])
        self.assertEqual(metric['recall'],1)
        self.assertEqual(metric['mean_rank_displacement'],1)
        self.assertEqual(metric['max_count_error'],0)

    def test_nested_ranks_and_reproducibility(self):
        first=rank_rows(list(range(1000)),42)
        self.assertEqual(first,rank_rows(list(range(1000)),42))
        self.assertNotEqual(first,rank_rows(list(range(1000)),43))
        self.assertTrue({r['id'] for r in first if r['rank']<.25} <= {r['id'] for r in first if r['rank']<.9})

    def test_bad_quality_or_unprofitable_tiers_use_exact(self):
        rows=[dict(fidelity=.5,quality_score=2,forecast_ms=1),dict(fidelity=1.,quality_score=0,forecast_ms=10)]
        self.assertEqual(choose_tier(rows),1)
        rows[0]['quality_score']=.5
        self.assertEqual(choose_tier(rows),.5)
        rows[0]['forecast_ms']=11
        self.assertEqual(choose_tier(rows),1)

    def test_calibration_cannot_hide_one_bad_root(self):
        rows=[dict(seed=seed,fidelity=f,recall=1.,max_count_error=.3 if f<1 and root==1 else 0)
              for seed in range(20) for f in (.25,.5,.75,.9,1.) for root in range(2)]
        profile=calibrate_quality(rows,list(range(20)),2)
        self.assertTrue(all(r['quality_score']>1 for r in profile if r['fidelity']<1))
        with self.assertRaises(ValueError):calibrate_quality(rows[:-1],list(range(20)),2)

    def test_views_refuse_unrelated_database(self):
        class Backend:database='neo4j'
        with self.assertRaises(ValueError):IC5Views(Backend())
