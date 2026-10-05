"""Explicit reusable samples for static graphs; query requests never rebuild samples."""
from time import perf_counter
from uuid import uuid4
from .synthetic import validate_fidelity

ALGORITHM = 'numpy-default_rng-uniform-v1'


class ReusableSample:
    def __init__(self, backend):
        self.backend = backend
        self.dataset = backend.graph.dataset
        self.fingerprint = backend.graph.fingerprint
        self.active_state = None
        self.memory_state = None

    def read_state(self):
        if self.backend.name == 'memory':
            return self.memory_state.copy() if self.memory_state else None
        connection = self.backend.connection
        records, _, _ = connection.driver.execute_query(
            'MATCH (s:MFMaterialization {dataset: $dataset}) RETURN properties(s) AS state',
            dataset=self.dataset, database_=connection.database, routing_='r')
        return dict(records[0]['state']) if records else None

    def write_state(self, state):
        if self.backend.name == 'memory':
            self.memory_state = dict(state)
            return
        connection = self.backend.connection
        connection.driver.execute_query(
            'MERGE (s:MFMaterialization {dataset: $dataset}) SET s = $state',
            dataset=self.dataset, state=state, database_=connection.database)

    def matching(self, state, sample_seed):
        return (state is not None and state.get('status') == 'ready'
                and state.get('graph_sha256') == self.fingerprint
                and state.get('sample_seed') == sample_seed
                and state.get('algorithm') == ALGORITHM
                and (self.backend.name != 'memory'
                     or state.get('memory_generation') == self.backend.sample_generation))

    def attach(self, sample_seed):
        state = self.read_state()
        if not self.matching(state, sample_seed):
            raise RuntimeError('No ready matching sample. Run sample-build or explicitly refresh it.')
        self.active_state = state
        return state

    def build(self, sample_seed=1000, refresh=False):
        if type(sample_seed) is not int or sample_seed < 0:
            raise ValueError('sample_seed must be a nonnegative integer')
        start = perf_counter()
        state = self.read_state()
        if not refresh and self.matching(state, sample_seed):
            self.active_state = state
            return dict(reused=True, build_ms=0.0, lookup_ms=1000 * (perf_counter() - start),
                        generation=state['generation'], sample_seed=sample_seed)
        if self.backend.name == 'neo4j':
            connection = self.backend.connection
            connection.driver.execute_query(
                'CREATE CONSTRAINT mf_materialization_identity IF NOT EXISTS '
                'FOR (s:MFMaterialization) REQUIRE s.dataset IS UNIQUE',
                database_=connection.database)
            self.backend.validate_import()
        state = dict(dataset=self.dataset, graph_sha256=self.fingerprint, algorithm=ALGORITHM,
                     sample_seed=sample_seed, generation=uuid4().hex, status='building')
        # Publish ready only after every rank batch commits. Failed/interrupted builds stay unusable.
        self.write_state(state)
        try:
            self.backend.prepare(sample_seed)
            if self.backend.name == 'memory':
                state['memory_generation'] = self.backend.sample_generation
            state['status'] = 'ready'
            self.write_state(state)
        except Exception:
            state['status'] = 'failed'
            try:
                self.write_state(state)
            except Exception:
                pass
            self.active_state = None
            raise
        self.active_state = state
        return dict(reused=False, build_ms=1000 * (perf_counter() - start), lookup_ms=0.0,
                    generation=state['generation'], sample_seed=sample_seed)

    def counts(self, country='FR', fidelity=1.0):
        validate_fidelity(fidelity)
        start = perf_counter()
        if fidelity < 1:
            if self.active_state is None:
                raise RuntimeError('Attach or build a sample before an approximate request.')
            current = self.read_state()
            if (not self.matching(current, self.active_state['sample_seed'])
                    or current['generation'] != self.active_state['generation']):
                raise RuntimeError('Sample was invalidated or refreshed. Attach the current sample explicitly.')
            if (self.backend.name == 'memory'
                    and self.backend.sample_generation != self.active_state['memory_generation']):
                raise RuntimeError('Memory sample was overwritten. Rebuild it explicitly.')
        lookup_ms = 1000 * (perf_counter() - start)
        result = self.backend.counts(country, fidelity)
        result.update(state_check_ms=lookup_ms, request_ms=1000 * (perf_counter() - start))
        return result


def sample_operation(backend_name, operation, n_nodes, avg_degree, graph_seed,
                     sample_seed, fidelity=0.1, country='FR', refresh=False, import_graph=False):
    from .backends import Neo4jBackend
    from .synthetic import generate_graph, SyntheticMemory, SyntheticNeo4j
    if operation == 'sample-count' and backend_name != 'neo4j':
        raise ValueError('sample-count needs persistent Neo4j state; use reuse-benchmark for offline reuse.')
    graph = generate_graph(n_nodes, avg_degree, graph_seed)
    connection = None
    try:
        if backend_name == 'neo4j':
            connection = Neo4jBackend()
            backend = SyntheticNeo4j(graph, connection)
            if import_graph:
                backend.seed()
        else:
            backend = SyntheticMemory(graph)
        cache = ReusableSample(backend)
        if operation == 'sample-build':
            return dict(backend=backend_name, dataset=graph.dataset,
                        **cache.build(sample_seed, refresh=refresh))
        state = cache.attach(sample_seed)
        observed = cache.counts(country=country, fidelity=fidelity)
        return dict(backend=backend_name, dataset=graph.dataset, sample_seed=sample_seed,
                    generation=state['generation'], fidelity=fidelity, country=country,
                    node_estimate=observed['node_count']/fidelity,
                    edge_estimate=observed['edge_count']/(fidelity*fidelity), **observed)
    finally:
        if connection:
            connection.close()
