import json
import os
from pathlib import Path
import tempfile
import unittest
from graph_mf.snb import SNBGraph, SNBMemory, SNBNeo4j, epoch_ms, load_snb, sample_ranks
from graph_mf.backends import Neo4jBackend


def fixture():
    people = {p:dict(id=p,firstName=str(p),lastName='Fixture') for p in range(1,6)}
    return SNBGraph(people,[(1,2,100),(1,3,100),(2,3,80),(2,4,70),(3,4,60)],{})


class SNBTests(unittest.TestCase):
    def test_is3_ordered_fields_and_tie_breaking(self):
        rows = SNBMemory(fixture()).query('is3',1)['value']
        self.assertEqual([r['personId'] for r in rows],[2,3])
        self.assertEqual(rows[0],dict(personId=2,firstName='2',lastName='Fixture',friendshipCreationDate=100))

    def test_fixed_root_neighbor_inclusion_scales_by_f_only(self):
        backend = SNBMemory(fixture())
        backend.ranks = {1:.99,2:.05,3:.9,4:.9,5:.9}
        row = backend.query('friends_count',1,.1)
        self.assertEqual(row['value'],1)
        self.assertEqual(row['estimate'],10.)
        self.assertEqual(row['fidelity'],.1)

    def test_multi_path_duplicates_and_root_excluded_with_exact_fallback(self):
        row = SNBMemory(fixture()).query('reach_2_count',1,.1)
        self.assertEqual(row['value'],3) # Two paths to 4, plus a triangle; each person once.
        self.assertEqual(row['fidelity'],1.)
        self.assertIsNotNone(row['fallback_reason'])

    def test_isolated_unknown_and_list_approximation(self):
        backend = SNBMemory(fixture())
        self.assertEqual(backend.query('is3',5)['value'],[])
        self.assertEqual(backend.query('reach_2_count',5)['value'],0)
        with self.assertRaises(ValueError):
            backend.query('is3',1,.5)
        with self.assertRaises(ValueError):
            backend.query('friends_count',6)

    def test_seed_reproducibility_and_epoch_milliseconds(self):
        self.assertEqual(sample_ranks(fixture(),42),sample_ranks(fixture(),42))
        self.assertEqual(epoch_ms('1278777892244'),1278777892244)
        self.assertEqual(epoch_ms('1970-01-01T01:00:00.123+01:00'),123)
        with self.assertRaises(ValueError):
            epoch_ms('1970-01-01T00:00:00')

    def test_duplicate_headers_parsed_positionally_and_strict_input_checks(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path/'person_0_0.csv').write_text('id|firstName|lastName\n1|A|X\n2|B|Y\n')
            edge = path/'person_knows_person_0_0.csv'
            edge.write_text('Person.id|Person.id|creationDate\n1|2|100\n')
            graph = load_snb(path,verify_pinned=False)
            self.assertEqual(graph.edges,[(1,2,100)])
            self.assertFalse(graph.provenance['official_micro_fixture'])
            with self.assertRaises(ValueError):
                load_snb(path)
            edge.write_text('Person.id|Person.id|creationDate\n1|2|100\n2|1|100\n')
            with self.assertRaises(ValueError):
                load_snb(path,verify_pinned=False)


@unittest.skipUnless(os.environ.get('RUN_NEO4J_TESTS') == '1', 'Live Neo4j opt-in required')
class LiveSNBTests(unittest.TestCase):
    def test_order_counts_and_sequential_sample_invalidation(self):
        first, second = Neo4jBackend(), Neo4jBackend()
        try:
            graph = fixture()
            a, b = SNBNeo4j(graph,first), SNBNeo4j(graph,second)
            reference = SNBMemory(graph)
            a.seed()
            a.seed()
            for p in graph.persons:
                self.assertEqual(a.query('is3',p)['value'],reference.query('is3',p)['value'])
                self.assertEqual(a.query('reach_2_count',p,.1)['value'],reference.query('reach_2_count',p)['value'])
            a.prepare(42)
            reference.prepare(42)
            self.assertEqual(a.query('friends_count',1,.5)['value'],reference.query('friends_count',1,.5)['value'])
            b.prepare(43)
            with self.assertRaises(RuntimeError):
                a.query('friends_count',1,.5)
            self.assertEqual(a.query('friends_count',1)['value'],2)
            a.prepare(42)
            b.seed()
            with self.assertRaises(RuntimeError):
                a.query('friends_count',1,.5)
        finally:
            first.close()
            second.close()
