import unittest
from graph_mf.ic5_offline import IC5Offline,load_ic5_csv


class IC5OracleTests(unittest.TestCase):
    def graph(self):
        return IC5Offline([1,2,3,4],[11,12,13],['same']*3,[100,101,102,103],
            [1,2,2,3],[0,1,1,0],[(0,1),(1,2)],[(0,1,1),(1,2,2),(2,1,3),(0,1,1)])

    def test_exact_membership_dates_outsiders_duplicates_and_zero_forums(self):
        graph=self.graph()
        self.assertEqual([(r['forumId'],r['postCount']) for r in graph.query(1,-1)],[(12,2),(11,1),(13,0)])
        self.assertEqual([(r['forumId'],r['postCount']) for r in graph.query(1,1)],[(12,2),(13,0)])
        self.assertEqual(graph.query(1,3),[])
        self.assertEqual(graph.query(-1,-1),[])

    def test_prefix_sampling_matches_independent_enumeration(self):
        import random
        graph=self.graph();prefix=graph.prefixes(42,[.25,.5,.9])
        rng=random.Random(42);ranks=[rng.random() for _ in range(4)]
        for f in (.25,.5,.9):
            expected={11:int(ranks[0]<f)/f,12:(int(ranks[1]<f)+int(ranks[2]<f))/f,13:0}
            self.assertEqual({r['forumId']:r['postCount'] for r in graph.query(1,-1,f,prefix)},expected)

    def test_incomplete_post_ownership_is_rejected(self):
        with self.assertRaises(ValueError):IC5Offline([1],[11],['x'],[100],[-1],[0],[],[])

    def test_csv_entity_glob_excludes_relationship_files(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'dynamic';path.mkdir()
            tables={'person':'id\n1\n2\n','forum':'id|title\n11|x\n','post':'id\n100\n',
                'person_knows_person':'a|b\n1|2\n','forum_hasMember_person':'a|b|date\n11|2|1\n',
                'post_hasCreator_person':'a|b\n100|2\n','forum_containerOf_post':'a|b\n11|100\n'}
            for name,data in tables.items():(path/(name+'_0_0.csv')).write_text(data)
            graph,manifest=load_ic5_csv(Path(root))
            self.assertEqual(graph.query(1,-1),[dict(forumId=11,forumName='x',postCount=1)])
            self.assertEqual(len(manifest),7)
