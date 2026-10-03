"""Memory evaluation and optional Neo4j adapter for fixed exact queries."""
import os
from typing import Protocol
from .dataset import cypher, load_tiny

QUERIES = ("node_count", "edge_count", "city_count", "age_count")


class Backend(Protocol):
    name: str
    def seed(self): ...
    def count(self, query, **parameters) -> int: ...
    def close(self): ...


def query_parameters(query, parameters):
    if query not in QUERIES:
        raise ValueError(f"Unknown count query: {query}")
    required = {"city"} if query == "city_count" else {"min_age"} if query == "age_count" else set()
    if set(parameters) != required:
        raise ValueError(f"{query} requires exactly {sorted(required)}")
    if query == "city_count" and not isinstance(parameters["city"], str):
        raise ValueError("city must be a string")
    if query == "age_count" and type(parameters["min_age"]) is not int:
        raise ValueError("min_age must be an integer")
    return parameters


class MemoryBackend:
    """Evaluates equivalent fixed predicates; this is not a Cypher engine."""
    name = "memory"

    def __init__(self):
        self.data = load_tiny()

    def seed(self):
        self.data = load_tiny()

    def count(self, query, **parameters):
        query_parameters(query, parameters)
        if query == "node_count":
            return len(self.data["people"])
        if query == "edge_count":
            return len(self.data["friends"])
        if query == "city_count":
            return sum(p["city"] == parameters["city"] for p in self.data["people"])
        return sum(p["age"] >= parameters["min_age"] for p in self.data["people"])

    def close(self):
        pass


class Neo4jBackend:
    name = "neo4j"

    def __init__(self):
        password = os.environ.get("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError("Set NEO4J_PASSWORD before using the neo4j backend.")
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RuntimeError('Install the optional driver: python -m pip install -e ".[neo4j]"') from exc
        self.dataset = load_tiny()["dataset"]
        self.database = os.environ.get("NEO4J_DATABASE", "neo4j")
        self.driver = GraphDatabase.driver(
            os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
            auth=(os.environ.get("NEO4J_USER", "neo4j"), password),
            connection_timeout=5,
            max_transaction_retry_time=5,
        )
        try:
            self.driver.verify_connectivity()
        except Exception:
            self.driver.close()
            raise RuntimeError("Neo4j connection failed. Check service, URI and credentials; use --backend memory for offline learning.") from None

    def seed(self):
        # Schema is a separate transaction; both data writes commit atomically.
        self.driver.execute_query(cypher("schema"), database_=self.database)
        data = load_tiny()
        def write(tx):
            tx.run(cypher("seed_people"), dataset=self.dataset, people=data["people"]).consume()
            tx.run(cypher("seed_friends"), dataset=self.dataset, friends=data["friends"]).consume()
        with self.driver.session(database=self.database) as session:
            session.execute_write(write)

    def count(self, query, **parameters):
        query_parameters(query, parameters)
        records, _, _ = self.driver.execute_query(
            cypher(query), parameters_={"dataset": self.dataset, **parameters},
            database_=self.database, routing_="r",
        )
        if len(records) != 1:
            raise RuntimeError("Expected a single COUNT result")
        return int(records[0]["count"])

    def close(self):
        self.driver.close()
