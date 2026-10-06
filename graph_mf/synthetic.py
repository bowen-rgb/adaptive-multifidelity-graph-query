"""Matched v0.1 generator, preserving every stored edge pair including duplicates."""
import hashlib
from dataclasses import dataclass
from time import perf_counter
from .dataset import cypher


def numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError('Install experiment dependencies: python -m pip install -e ".[experiments]"') from exc
    return np


@dataclass
class SyntheticGraph:
    countries: object
    src: object
    dst: object
    seed: int
    avg_degree: int

    @property
    def fingerprint(self):
        h = hashlib.sha256()
        h.update('\n'.join(self.countries.tolist()).encode())
        h.update(self.src.astype('<i8').tobytes())
        h.update(self.dst.astype('<i8').tobytes())
        return h.hexdigest()

    @property
    def dataset(self):
        return 'graph-mf-synthetic-' + self.fingerprint[:16]


def generate_graph(n_nodes=50000, avg_degree=6, seed=42):
    if type(n_nodes) is not int or n_nodes < 2:
        raise ValueError('n_nodes must be an integer >=2')
    if type(avg_degree) is not int or avg_degree < 0:
        raise ValueError('avg_degree must be a nonnegative integer')
    np = numpy()
    rng = np.random.default_rng(seed)
    countries = rng.choice(np.array(['FR', 'DE', 'ES', 'IT', 'NL']), size=n_nodes,
                           p=[0.30, 0.20, 0.18, 0.17, 0.15])
    n_edges = n_nodes * avg_degree // 2
    src = rng.integers(0, n_nodes, size=n_edges, endpoint=False)
    dst = rng.integers(0, n_nodes, size=n_edges, endpoint=False)
    mask = src != dst
    return SyntheticGraph(countries, src[mask], dst[mask], seed, avg_degree)


def validate_fidelity(fidelity):
    if not 0 < fidelity <= 1:
        raise ValueError('fidelity must be in (0, 1]')


class SyntheticMemory:
    name = 'memory'

    def __init__(self, graph):
        self.graph = graph
        self.sample = numpy().zeros(len(graph.countries))
        self.sample_generation = 0

    def prepare(self, seed):
        self.sample = numpy().random.default_rng(seed).random(len(self.graph.countries))
        self.sample_generation += 1

    def counts(self, country='FR', fidelity=1.0):
        validate_fidelity(fidelity)
        g = self.graph
        start = perf_counter()
        target = g.countries == country
        if fidelity < 1:
            target = target & (self.sample < fidelity)
        nodes = int(target.sum())
        node_ms = 1000 * (perf_counter() - start)
        start = perf_counter()
        edges = int((target[g.src] & target[g.dst]).sum())
        edge_ms = 1000 * (perf_counter() - start)
        return dict(node_count=nodes, edge_count=edges, node_query_ms=node_ms,
                    edge_query_ms=edge_ms, query_ms=node_ms + edge_ms)

    def count_component(self, country, fidelity, kind):
        validate_fidelity(fidelity)
        if kind not in ('node', 'edge'):
            raise ValueError('Unknown COUNT component')
        start = perf_counter()
        target = self.graph.countries == country
        if fidelity < 1:
            target = target & (self.sample < fidelity)
        count = int(target.sum()) if kind == 'node' else int((target[self.graph.src] & target[self.graph.dst]).sum())
        return dict(count=count, query_ms=1000*(perf_counter()-start))


class SyntheticNeo4j:
    name = 'neo4j'

    def __init__(self, graph, connection, batch_size=2000):
        if type(batch_size) is not int or batch_size <= 0:
            raise ValueError('batch_size must be a positive integer')
        self.graph, self.connection = graph, connection
        self.dataset = graph.dataset
        self.batch_size = batch_size

    def write_batches(self, query, rows):
        for start in range(0, len(rows), self.batch_size):
            self.connection.driver.execute_query(cypher(query),
                rows=rows[start:start + self.batch_size], dataset=self.dataset,
                database_=self.connection.database)

    def seed(self):
        # A reimport resets sample ranks. Existing materialization must not stay ready.
        self.connection.driver.execute_query(cypher('synthetic_invalidate'),
            dataset=self.dataset, database_=self.connection.database)
        for suffix in ['schema', 'edge_schema', 'country_index', 'sample_index']:
            self.connection.driver.execute_query(cypher('synthetic_' + suffix),
                database_=self.connection.database)
        self.write_batches('synthetic_nodes', [dict(id=i, country=str(country))
            for i, country in enumerate(self.graph.countries)])
        self.write_batches('synthetic_edges', [dict(edge_id=i, source=int(a), target=int(b))
            for i, (a, b) in enumerate(zip(self.graph.src, self.graph.dst))])
        self.connection.driver.execute_query('CALL db.awaitIndexes(120)',
                                            database_=self.connection.database)
        self.validate_import()

    def validate_import(self):
        records, _, _ = self.connection.driver.execute_query(
            'MATCH (n:MFNode {dataset:$dataset}) RETURN count(n) AS count',
            dataset=self.dataset, database_=self.connection.database)
        edges, _, _ = self.connection.driver.execute_query(
            'MATCH ()-[r:MF_EDGE {dataset:$dataset}]->() RETURN count(r) AS count',
            dataset=self.dataset, database_=self.connection.database)
        if records[0]['count'] != len(self.graph.countries) or edges[0]['count'] != len(self.graph.src):
            raise RuntimeError('Imported graph size mismatch; benchmark cancelled')

    def prepare(self, seed):
        self.connection.driver.execute_query(cypher('synthetic_invalidate'),
            dataset=self.dataset, database_=self.connection.database)
        sample = numpy().random.default_rng(seed).random(len(self.graph.countries))
        self.write_batches('synthetic_prepare', [dict(id=i, sample=float(value))
                           for i, value in enumerate(sample)])

    def counts(self, country='FR', fidelity=1.0):
        validate_fidelity(fidelity)
        suffix = 'exact' if fidelity == 1 else 'sampled'
        parameters = dict(dataset=self.dataset, country=country)
        if fidelity < 1:
            parameters['fidelity'] = fidelity
        observed = {}
        # Same driver API for every query. Timing includes client/transaction overhead.
        for kind, key in [('nodes', 'node'), ('edges', 'edge')]:
            start = perf_counter()
            records, summary, _ = self.connection.driver.execute_query(
                cypher(f'synthetic_{suffix}_{kind}'), parameters_=parameters,
                database_=self.connection.database, routing_='r')
            observed[key + '_query_ms'] = 1000 * (perf_counter() - start)
            observed[key + '_count'] = int(records[0]['count'])
        observed['query_ms'] = observed['node_query_ms'] + observed['edge_query_ms']
        return observed

    def count_component(self, country, fidelity, kind):
        validate_fidelity(fidelity)
        if kind not in ('node', 'edge'):
            raise ValueError('Unknown COUNT component')
        suffix = 'exact' if fidelity == 1 else 'sampled'
        parameters = dict(dataset=self.dataset, country=country)
        if fidelity < 1:
            parameters['fidelity'] = fidelity
        start = perf_counter()
        records, _, _ = self.connection.driver.execute_query(
            cypher(f'synthetic_{suffix}_{kind}s'), parameters_=parameters,
            database_=self.connection.database, routing_='r')
        return dict(count=int(records[0]['count']), query_ms=1000*(perf_counter()-start))
