"""Pinned SNB v1 micro-fixture projection; IS3 exact, derived counts explicitly custom."""
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
from time import perf_counter
from uuid import uuid4

COMMIT = '11db98cc2ba14c33492f6c0c34e68c8be7e22e5f'
UPSTREAM = 'https://github.com/ldbc/ldbc_snb_interactive_v1_impls'
FILES = {'person_0_0.csv': '131ce3c4fd1e0ccab3e204403f4cfdaca21e5351bc60b34d1673bbc2a6bfeb30',
         'person_knows_person_0_0.csv': '703e6bed5869d90d1f8c49f0cc161640ec25e426840676a82ebed25bb13a58bf'}


def epoch_ms(text):
    if text.isdecimal():
        value = int(text)
        if value >= 2**63:
            raise ValueError('Epoch milliseconds exceed signed 64-bit range')
        return value
    value = datetime.fromisoformat(text)
    if value.tzinfo is None or value.microsecond % 1000:
        raise ValueError('Explicit time zone and millisecond precision required')
    delta = value.astimezone(timezone.utc)-datetime(1970,1,1,tzinfo=timezone.utc)
    return (delta.days*86400+delta.seconds)*1000+delta.microseconds//1000


@dataclass
class SNBGraph:
    persons: dict
    edges: list
    provenance: dict

    @property
    def fingerprint(self):
        payload = dict(persons=[self.persons[k] for k in sorted(self.persons)], edges=sorted(self.edges))
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @property
    def dataset(self):
        return 'graph-mf-snb-v1-'+self.fingerprint[:16]


def load_snb(folder, verify_pinned=True):
    folder = Path(folder)
    hashes = {f: hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in FILES}
    if verify_pinned and hashes != FILES:
        raise ValueError('Pinned SNB micro-fixture hashes mismatch')
    people = {}
    with (folder/'person_0_0.csv').open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle, delimiter='|'):
            identity = int(row['id'])
            if not 0 <= identity < 2**63 or identity in people:
                raise ValueError('Duplicate or invalid person ID')
            people[identity] = dict(id=identity, firstName=row['firstName'], lastName=row['lastName'])
    edges, seen = [], set()
    with (folder/'person_knows_person_0_0.csv').open(encoding='utf-8', newline='') as handle:
        reader = csv.reader(handle, delimiter='|')
        if next(reader) != ['Person.id', 'Person.id', 'creationDate']:
            raise ValueError('Expected duplicate endpoint headers in official KNOWS layout')
        for row in reader:
            if len(row) != 3:
                raise ValueError('Invalid KNOWS row')
            a, b = sorted((int(row[0]), int(row[1])))
            if a == b or a not in people or b not in people or (a,b) in seen:
                raise ValueError('Unknown endpoint, self-loop or duplicate undirected friendship')
            seen.add((a,b))
            edges.append((a,b,epoch_ms(row[2])))
    if not people:
        raise ValueError('Empty person table')
    return SNBGraph(people, sorted(edges), dict(source=UPSTREAM, commit=COMMIT if verify_pinned else None,
        file_sha256=hashes, official_micro_fixture=verify_pinned,
        projection='Person id/firstName/lastName and undirected KNOWS creationDate only',
        benchmark_scope='IS3 read semantics plus custom counts; not full SNB, SF1, driver protocol or audited benchmark',
        date_semantics='official LongDateFormatter integer UTC milliseconds preserved; ISO test inputs require explicit zone', raw_data_redistributed=False))


def sample_ranks(graph, seed):
    if type(seed) is not int or seed < 0:
        raise ValueError('Nonnegative integer sample seed required')
    rng = random.Random(seed)
    return {p:rng.random() for p in sorted(graph.persons)}


class SNBMemory:
    name = 'memory'

    def __init__(self, graph):
        self.graph, self.ranks = graph, None
        self.adj = {p: {} for p in graph.persons}
        for a,b,date in graph.edges:
            self.adj[a][b] = date
            self.adj[b][a] = date

    def prepare(self, seed):
        self.ranks = sample_ranks(self.graph, seed)

    def query(self, kind, person_id, fidelity=1.):
        validate_query(self.graph, kind, person_id, fidelity)
        start = perf_counter()
        if kind == 'is3':
            values = [dict(personId=p, firstName=self.graph.persons[p]['firstName'],
                lastName=self.graph.persons[p]['lastName'], friendshipCreationDate=date)
                for p,date in self.adj[person_id].items()]
            values.sort(key=lambda r: (-r['friendshipCreationDate'], r['personId']))
        elif kind == 'friends_count':
            if fidelity < 1 and self.ranks is None:
                raise RuntimeError('Prepare a sample first')
            values = sum(fidelity == 1 or self.ranks[p] < fidelity for p in self.adj[person_id])
        else:
            reached = set(self.adj[person_id])
            for friend in self.adj[person_id]:
                reached.update(self.adj[friend])
            reached.discard(person_id)
            values = len(reached)
        return result(kind, values, fidelity, 1000*(perf_counter()-start))


def validate_query(graph, kind, person_id, fidelity):
    if kind not in ('is3', 'friends_count', 'reach_2_count') or person_id not in graph.persons:
        raise ValueError('Known query and person ID required')
    if not 0 < fidelity <= 1:
        raise ValueError('Fidelity must be in (0,1]')
    if kind == 'is3' and fidelity != 1:
        raise ValueError('IS3 ordered tuples require exact execution')


def result(kind, values, requested_fidelity, query_ms):
    effective = requested_fidelity if kind == 'friends_count' else 1.
    return dict(kind=kind, value=values, requested_fidelity=requested_fidelity, fidelity=effective,
        estimate=values/effective if kind == 'friends_count' else values,
        fallback_reason='distinct multi-hop inclusion probability not validated' if kind == 'reach_2_count' and requested_fidelity < 1 else None,
        query_ms=query_ms, estimator='anchored-neighbor-count/ f; no calibrated error guarantee' if kind == 'friends_count' else 'exact')


class SNBNeo4j:
    name = 'neo4j'

    def __init__(self, graph, connection):
        self.graph, self.connection, self.ranks = graph, connection, None
        self.dataset, self.fingerprint = graph.dataset, graph.fingerprint
        self.generation = None

    def execute(self, query, **params):
        records, _, _ = self.connection.driver.execute_query(query,
            parameters_={'dataset':self.dataset, **params}, database_=self.connection.database)
        return [dict(r) for r in records]

    def seed(self):
        self.execute('CREATE CONSTRAINT mf_snb_person_identity IF NOT EXISTS FOR (p:MFSNBPerson) REQUIRE (p.dataset,p.id) IS UNIQUE')
        self.execute('CREATE CONSTRAINT mf_snb_sample_identity IF NOT EXISTS FOR (s:MFSNBSample) REQUIRE s.dataset IS UNIQUE')
        people = list(self.graph.persons.values())
        edges = [dict(a=a,b=b,date=d) for a,b,d in self.graph.edges]
        def write(tx):
            tx.run('MERGE (s:MFSNBSample {dataset:$dataset}) SET s.ready=false',dataset=self.dataset).consume()
            tx.run('UNWIND $people AS row MERGE (p:MFSNBPerson {dataset:$dataset,id:row.id}) '
                'SET p.firstName=row.firstName,p.lastName=row.lastName REMOVE p.sampleRank',
                dataset=self.dataset,people=people).consume()
            tx.run('UNWIND $edges AS row MATCH (a:MFSNBPerson {dataset:$dataset,id:row.a}), '
                '(b:MFSNBPerson {dataset:$dataset,id:row.b}) MERGE (a)-[r:MFKNOWS]->(b) SET r.creationDate=row.date',
                dataset=self.dataset,edges=edges).consume()
        with self.connection.driver.session(database=self.connection.database) as session:
            session.execute_write(write)
        self.ranks = None
        self.generation = None
        self.validate()

    def validate(self):
        people = self.execute('MATCH (p:MFSNBPerson {dataset:$dataset}) RETURN p.id AS id,p.firstName AS firstName,p.lastName AS lastName ORDER BY id')
        edges = self.execute('MATCH (a:MFSNBPerson {dataset:$dataset})-[r:MFKNOWS]->(b:MFSNBPerson {dataset:$dataset}) RETURN a.id AS a,b.id AS b,r.creationDate AS date ORDER BY a,b')
        if people != [self.graph.persons[k] for k in sorted(self.graph.persons)] or [(e['a'],e['b'],e['date']) for e in edges] != self.graph.edges:
            raise RuntimeError('SNB projected import does not match source snapshot')

    def prepare(self, seed):
        self.ranks = None
        self.generation = None
        ranks = sample_ranks(self.graph, seed)
        generation = uuid4().hex
        rows = [dict(id=p,rank=r) for p,r in ranks.items()]
        def write(tx):
            tx.run('UNWIND $rows AS row MATCH (p:MFSNBPerson {dataset:$dataset,id:row.id}) SET p.sampleRank=row.rank',
                   dataset=self.dataset,rows=rows).consume()
            tx.run('MERGE (s:MFSNBSample {dataset:$dataset}) SET s.ready=true,s.generation=$generation,s.graph_sha256=$fingerprint',
                dataset=self.dataset,generation=generation,fingerprint=self.fingerprint).consume()
        with self.connection.driver.session(database=self.connection.database) as session:
            session.execute_write(write)
        self.ranks = ranks
        self.generation = generation

    def query(self, kind, person_id, fidelity=1.):
        validate_query(self.graph, kind, person_id, fidelity)
        if kind == 'friends_count' and fidelity < 1 and self.ranks is None:
            raise RuntimeError('Prepare a sample first')
        start = perf_counter()
        if kind == 'friends_count' and fidelity < 1:
            state = self.execute('MATCH (s:MFSNBSample {dataset:$dataset}) RETURN s.ready AS ready,s.generation AS generation,s.graph_sha256 AS graph_sha256')
            if not state or state[0] != dict(ready=True,generation=self.generation,graph_sha256=self.fingerprint):
                raise RuntimeError('SNB sample invalidated or replaced; rebuild before approximation')
        base = 'MATCH (root:MFSNBPerson {dataset:$dataset,id:$person_id})'
        if kind == 'is3':
            values = self.execute(base+'-[r:MFKNOWS]-(friend:MFSNBPerson {dataset:$dataset}) '
                'RETURN friend.id AS personId,friend.firstName AS firstName,friend.lastName AS lastName,'
                'r.creationDate AS friendshipCreationDate ORDER BY friendshipCreationDate DESC,personId ASC', person_id=person_id)
        elif kind == 'friends_count':
            values = self.execute(base+'-[:MFKNOWS]-(friend:MFSNBPerson {dataset:$dataset}) '
                'WHERE $fidelity=1.0 OR friend.sampleRank<$fidelity RETURN count(friend) AS count',
                person_id=person_id,fidelity=fidelity)[0]['count']
        else:
            values = self.execute(base+'-[:MFKNOWS*1..2]-(friend:MFSNBPerson {dataset:$dataset}) '
                'WHERE friend<>root RETURN count(DISTINCT friend) AS count', person_id=person_id)[0]['count']
        return result(kind, values, fidelity, 1000*(perf_counter()-start))
