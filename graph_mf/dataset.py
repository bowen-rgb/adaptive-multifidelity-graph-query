"""One dataset definition shared by both backends."""
import json
from importlib.resources import files


def load_tiny():
    return json.loads(files("graph_mf").joinpath("data/tiny.json").read_text(encoding="utf-8"))


def cypher(name):
    allowed = {"schema", "seed_people", "seed_friends", "node_count", "edge_count", "city_count", "age_count"}
    allowed.update({"synthetic_" + suffix for suffix in (
        "schema", "edge_schema", "country_index", "sample_index", "nodes", "edges", "prepare",
        "exact_nodes", "exact_edges", "sampled_nodes", "sampled_edges", "invalidate")})
    if name not in allowed:
        raise ValueError(f"Unknown query: {name}")
    return files("graph_mf").joinpath(f"cypher/{name}.cypher").read_text(encoding="utf-8")
