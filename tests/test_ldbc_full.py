import unittest
import os
from pathlib import Path
from graph_mf.ldbc_full import parse_node, RELATIONS, NODES, filesystem_path, batches


class FullLoaderTests(unittest.TestCase):
    def test_csv_read_from_long_nested_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            folders=[]; current=Path(root)
            try:
                for i in range(7):
                    current=filesystem_path(current/('long-snb-directory-'+str(i)+'x'*30))
                    current.mkdir();folders.append(current)
                file=current/'table.csv'
                file.write_text('id|value\n1|a\n2|b\n',encoding='utf-8')
                self.assertGreater(len(str(file)),260)
                self.assertEqual(list(batches(file,1)),[[['1','a']],[['2','b']]])
                file.unlink()
            finally:
                for folder in reversed(folders):folder.rmdir()

    def test_reference_import_property_types_and_empty_cells(self):
        header = 'id:ID(Post)|content:STRING|imageFile:STRING|creationDate:LONG|length:INT'.split('|')
        props, labels = parse_node(header, ['1099511997932', '', 'img.png', '1347529090363','6'], 'post')
        self.assertEqual(props,dict(id=1099511997932,imageFile='img.png',creationDate=1347529090363,length=6))
        self.assertEqual(labels,['Post','Message'])

    def test_subtype_labels_arrays_and_duplicate_endpoint_layout(self):
        props,labels=parse_node('id:ID(Place)|name:STRING|url:STRING|:LABEL'.split('|'),
                                ['1','Paris','url','city'],'place')
        self.assertEqual(labels,['Place','City'])
        self.assertEqual(props['id'],1)
        props,_=parse_node(['speaks:STRING[]','email:STRING[]'],['fr;en',''],'person')
        self.assertEqual(props,dict(speaks=['fr','en'],email=[]))
        self.assertEqual(RELATIONS['workAt'],'WORK_AT')
        self.assertEqual(len(NODES),8)
        with self.assertRaises(ValueError):
            parse_node(['id:ID(Person)'],['1','extra'],'person')
        with self.assertRaises(ValueError):
            parse_node([':LABEL'],['unexpected) CREATE (n)'],'place')


@unittest.skipUnless(os.environ.get('RUN_LDBC_LIVE_TESTS')=='1','Dedicated LDBC live tests opt-in')
class ExactIC14Tests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('LDBC_REFERENCE'),'Reference checkout required for update regression')
    def test_new_person_empty_groups_do_not_skip_later_relationships(self):
        from graph_mf.backends import Neo4jBackend
        from graph_mf.ldbc_reference import patch_reference_queries
        import tempfile,shutil,itertools
        b=Neo4jBackend()
        self.assertIn('weighttest',b.database)
        def run(q,**params):
            return b.driver.execute_query(q,parameters_=params,database_=b.database)[0]
        marker='graph-mf-u1-regression'
        try:
            run('CREATE (:City {id:-804,test:$marker}),(:Tag {id:-801,test:$marker}),'
                '(:Organisation:University {id:-802,test:$marker}),(:Organisation:Company {id:-803,test:$marker})',marker=marker)
            with tempfile.TemporaryDirectory() as folder:
                for name in ('interactive-complex-1.cypher','interactive-short-7.cypher','interactive-update-1.cypher'):
                    shutil.copyfile(Path(os.environ['LDBC_REFERENCE'])/'cypher/queries'/name,Path(folder)/name)
                patch_reference_queries(folder)
                query=(Path(folder)/'interactive-update-1.cypher').read_text(encoding='utf-8')
                for i,(tag,study,work) in enumerate(itertools.product((False,True),repeat=3)):
                    identity=-7000-i
                    params=dict(cityId=-804,personId=identity,personFirstName='Test',personLastName='Groups',
                        gender='female',birthday=0,creationDate=0,locationIP='local',browserUsed='test',
                        languages=['en'],emails=[],tagIds=[-801] if tag else [],
                        studyAt=[[-802,2019]] if study else [],workAt=[[-803,2020]] if work else [])
                    run(query,**params)
                    rows=run('MATCH (p:Person {id:$id})-[r]->() RETURN type(r) AS kind,count(r) AS n',id=identity)
                    expected={'IS_LOCATED_IN':1}
                    expected.update({k:1 for k,enabled in [('HAS_INTEREST',tag),('STUDY_AT',study),('WORK_AT',work)] if enabled})
                    self.assertEqual({r['kind']:r['n'] for r in rows},expected)
                    self.assertEqual(run('MATCH (p:Person {id:$id}) RETURN p.speaks AS speaks',id=identity)[0]['speaks'],['en'])
        finally:
            run('MATCH (n) WHERE n.test=$marker OR n.id<=-7000 AND n.id>=-7007 DETACH DELETE n',marker=marker)
            b.close()

    def test_reply_weights_multiple_shortest_paths_self_and_disconnected(self):
        from graph_mf.backends import Neo4jBackend
        b=Neo4jBackend()
        self.assertNotIn(b.database,('neo4j','system'))
        def run(q, **params):
            return b.driver.execute_query(q,parameters_=params,database_=b.database)[0]
        marker='graph-mf-ic14-regression'
        q=(Path(__file__).resolve().parents[1]/'graph_mf/cypher/ldbc_ic14_bound.cypher').read_text()
        try:
            run('UNWIND range(-105,-101) AS id CREATE (:Person {id:id, test:$marker})',marker=marker)
            run('UNWIND [[-101,-102],[-101,-103],[-102,-104],[-103,-104]] AS edge '
                'MATCH (a:Person {id:edge[0]}),(b:Person {id:edge[1]}) CREATE (a)-[:KNOWS]->(b)')
            run('MATCH (a:Person {id:-101}),(b:Person {id:-102}),(c:Person {id:-103}) '
                'CREATE (p:Post:Message {id:-201,test:$marker})-[:HAS_CREATOR]->(b),'
                '(s:Post:Message {id:-202,test:$marker})-[:HAS_CREATOR]->(a),'
                '(x:Comment:Message {id:-301,test:$marker})-[:HAS_CREATOR]->(a),'
                '(x)-[:REPLY_OF]->(p),'
                '(y:Comment:Message {id:-302,test:$marker})-[:HAS_CREATOR]->(b),'
                '(y)-[:REPLY_OF]->(s),'
                '(z:Comment:Message {id:-303,test:$marker})-[:HAS_CREATOR]->(c),'
                '(z)-[:REPLY_OF]->(x)',marker=marker)
            rows=run(q,person1Id=-101,person2Id=-104)
            self.assertEqual([(r['personIdsInPath'],r['pathWeight']) for r in rows],
                             [([-101,-102,-104],2.),([-101,-103,-104],.5)])
            self.assertEqual(run(q,person1Id=-101,person2Id=-101)[0]['pathWeight'],0)
            self.assertEqual(run(q,person1Id=-101,person2Id=-105),[])
        finally:
            run('MATCH (n {test:$marker}) DETACH DELETE n',marker=marker)
            b.close()

    @unittest.skipUnless(os.environ.get('LDBC_REFERENCE'),'Reference checkout required for update regression')
    def test_materialized_weights_maintained_with_empty_tags_and_new_friendship(self):
        from graph_mf.backends import Neo4jBackend
        from graph_mf.ldbc_weights import build_weights,patch_weight_queries,validate_weights
        import tempfile,shutil
        b=Neo4jBackend()
        self.assertIn('weighttest',b.database)
        def run(q,**params):
            return b.driver.execute_query(q,parameters_=params,database_=b.database)[0]
        self.assertEqual(run('MATCH (n) RETURN count(n) AS n')[0]['n'],0)
        marker='graph-mf-weight-regression'
        try:
            run('CREATE (a:Person {id:-101,test:$marker}),(b:Person {id:-102,test:$marker}),'
                '(country:Country {id:-1,test:$marker}),'
                '(p:Post:Message {id:-201,test:$marker})-[:HAS_CREATOR]->(b),'
                '(c:Comment:Message {id:-301,test:$marker})-[:HAS_CREATOR]->(a),'
                '(c)-[:REPLY_OF]->(p)',marker=marker)
            build_weights(b)
            with tempfile.TemporaryDirectory() as folder:
                source=Path(os.environ['LDBC_REFERENCE'])/'cypher/queries/interactive-update-7.cypher'
                shutil.copyfile(source,Path(folder)/source.name)
                patch_weight_queries(folder)
                u8=(Path(folder)/'interactive-update-8.cypher').read_text()
                u7=(Path(folder)/'interactive-update-7.cypher').read_text()
                run(u8,person1Id=-101,person2Id=-102,creationDate=1)
                q=(Path(folder)/'interactive-complex-14.cypher').read_text()
                self.assertEqual(run(q,person1Id=-101,person2Id=-102)[0]['pathWeight'],1.)
                run(u7,authorPersonId=-101,countryId=-1,replyToPostId=-201,replyToCommentId=-1,
                    commentId=-302,creationDate=2,locationIP='local',browserUsed='test',content='reply',length=5,tagIds=[])
                self.assertEqual(run(q,person1Id=-101,person2Id=-102)[0]['pathWeight'],2.)
                run(u7,authorPersonId=-102,countryId=-1,replyToPostId=-1,replyToCommentId=-302,
                    commentId=-303,creationDate=3,locationIP='local',browserUsed='test',content='reply',length=5,tagIds=[])
                self.assertEqual(run(q,person1Id=-101,person2Id=-102)[0]['pathWeight'],2.5)
                self.assertTrue(validate_weights(b)['all_pair_weights_match'])
                run('MATCH ()-[r:KNOWS]->() SET r.mfWeight=123.0')
                with self.assertRaises(RuntimeError):
                    validate_weights(b)
                with self.assertRaises(ValueError):
                    build_weights(b)
        finally:
            run('MATCH (n) WHERE n.test=$marker OR n:MFIC14State OR n.id IN [-302,-303] DETACH DELETE n',marker=marker)
            b.close()
