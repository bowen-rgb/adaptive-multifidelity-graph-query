import unittest
from graph_mf.budget_search import search


class BudgetSearchTests(unittest.TestCase):
    def test_all_methods_charge_each_evaluation_and_respect_budget(self):
        domain = [(a/4, b/4) for a in range(1, 5) for b in range(1, 5)]
        for method in ('random', 'nsga2', 'surrogate'):
            calls = []
            def evaluate(candidate):
                calls.append(candidate)
                return sum(candidate), 1-min(candidate)
            result = search(domain, evaluate, 6, .5, method, 7)
            self.assertEqual(len(calls), len(set(calls)))
            self.assertEqual(result['evaluations'], len(calls))
            self.assertLessEqual(len(calls), 6)
            selected = result['selected']
            if selected is not None:
                self.assertIn(selected, calls)
                self.assertLessEqual(result['observations'][selected][1], .5)

    def test_no_feasible_answer_is_not_silently_accepted(self):
        result = search([(0.1, .1), (.2, .2)], lambda c: (1, .9), 2, .1, 'random')
        self.assertIsNone(result['selected'])
