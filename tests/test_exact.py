import contextlib
import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch

from graph_mf.__main__ import main
from graph_mf.backends import MemoryBackend, Neo4jBackend
from graph_mf.dataset import cypher, load_tiny


class ExactTests(unittest.TestCase):
    def test_counts_and_boundaries(self):
        backend = MemoryBackend()
        self.assertEqual(backend.count("node_count"), 3)
        self.assertEqual(backend.count("edge_count"), 2)
        self.assertEqual(backend.count("city_count", city="Paris"), 1)
        self.assertEqual(backend.count("city_count", city="Missing"), 0)
        self.assertEqual(backend.count("city_count", city="Paris' RETURN 99 //"), 0)
        self.assertEqual(backend.count("age_count", min_age=24), 2)
        self.assertEqual(backend.count("age_count", min_age=28), 0)
        backend.seed()
        backend.seed()
        self.assertEqual(backend.count("edge_count"), 2)

    def test_invalid_queries_and_parameters(self):
        for query, params in [("unknown", {}), ("city_count", {}),
                              ("node_count", {"city": "Paris"}), ("age_count", {"min_age": "24"})]:
            with self.assertRaises(ValueError):
                MemoryBackend().count(query, **params)
        with self.assertRaises(ValueError):
            cypher("../secrets")

    def test_fixture_referential_integrity(self):
        data = load_tiny()
        ids = {p["id"] for p in data["people"]}
        self.assertEqual(len(ids), len(data["people"]))
        self.assertTrue(all(e["source"] in ids and e["target"] in ids for e in data["friends"]))

    def test_offline_cli(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["smoke"]), 0)
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["passed"])
        self.assertEqual(result["backend"], "memory")
        self.assertFalse(result["neo4j_query_executed"])
        self.assertFalse(result["neo4j_measured"])

    def test_missing_credentials_never_fall_back(self):
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--backend", "neo4j", "smoke"]), 2)

    def test_adapter_parameterization_and_atomic_seed(self):
        # Adapter contract only. Does not validate Cypher on a real server.
        backend = Neo4jBackend.__new__(Neo4jBackend)
        backend.driver = MagicMock()
        backend.database = "neo4j"
        backend.dataset = load_tiny()["dataset"]
        backend.driver.execute_query.return_value = ([{"count": 1}], None, None)
        city = "Paris' RETURN 99 //"
        self.assertEqual(backend.count("city_count", city=city), 1)
        args, kwargs = backend.driver.execute_query.call_args
        self.assertNotIn(city, args[0])
        self.assertEqual(kwargs["parameters_"], {"dataset": backend.dataset, "city": city})
        backend.seed()
        session = backend.driver.session.return_value.__enter__.return_value
        tx = MagicMock()
        session.execute_write.call_args.args[0](tx)
        self.assertEqual(tx.run.call_count, 2)
        self.assertEqual(tx.run.call_args_list[0].kwargs["people"], load_tiny()["people"])
        backend.close()
        backend.driver.close.assert_called_once()


@unittest.skipUnless(os.environ.get("RUN_NEO4J_TESTS") == "1", "Live Neo4j opt-in required")
class LiveNeo4jTests(unittest.TestCase):
    def test_seed_twice_and_compare_backends(self):
        backend = Neo4jBackend()
        try:
            backend.seed()
            backend.seed()
            memory = MemoryBackend()
            for query, params in [("node_count", {}), ("edge_count", {}),
                                  ("city_count", {"city": "Paris"}),
                                  ("city_count", {"city": "Missing"}),
                                  ("age_count", {"min_age": 24})]:
                self.assertEqual(backend.count(query, **params), memory.count(query, **params))
        finally:
            backend.close()
