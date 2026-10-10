import unittest
from graph_mf.ldbc_ic3_sampling import quality, select_messages


class IC3SamplingTests(unittest.TestCase):
    def test_ranked_tuple_loss_is_not_hidden_by_good_matched_counts(self):
        exact=[dict(friendId=1,xCount=5,yCount=5,xyCount=10),
               dict(friendId=2,xCount=2,yCount=2,xyCount=4)]
        measured=quality(exact,exact[:1])
        self.assertEqual(measured['recall'],.5)
        self.assertEqual(measured['missing'],1)
        self.assertEqual(measured['max_count_error'],1)

    def test_empty_answers_and_false_people(self):
        self.assertEqual(quality([],[])['recall'],1)
        measured=quality([],[dict(friendId=1,xCount=2,yCount=1,xyCount=3)])
        self.assertEqual(measured['recall'],0)
        self.assertEqual(measured['false_people'],1)

    def test_nested_reproducible_samples_keep_full_tier_exact(self):
        ids=list(range(1000))
        self.assertTrue(set(select_messages(ids,.1,42)) <= set(select_messages(ids,.5,42)))
        self.assertEqual(select_messages(ids,1,42),ids)
        self.assertNotEqual(select_messages(ids,.5,42),select_messages(ids,.5,43))
