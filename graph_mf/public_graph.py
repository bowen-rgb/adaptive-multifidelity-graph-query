"""Strict SNAP edge-list import; real topology, derived degree predicates."""
import gzip
import hashlib
from pathlib import Path
from .synthetic import SyntheticGraph, numpy

SOURCE = 'https://snap.stanford.edu/data/ego-Facebook.html'
GROUPS = ('degree_0_9', 'degree_10_19', 'degree_20_39', 'degree_40_79', 'degree_80_plus')


def load_snap(path):
    path = Path(path)
    raw = path.read_bytes()
    text = gzip.decompress(raw).decode('utf-8') if path.suffix == '.gz' else raw.decode('utf-8')
    edges, seen = [], set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError('Expected two integer endpoints per edge')
        a, b = map(int, parts)
        if min(a, b) < 0 or a == b:
            raise ValueError('Negative IDs and self-loops are unsupported')
        pair = tuple(sorted((a, b)))
        if pair in seen:
            raise ValueError('Duplicate undirected edge')
        seen.add(pair)
        edges.append(pair)
    if not edges:
        raise ValueError('Empty edge list')
    np = numpy()
    ids = sorted({v for edge in edges for v in edge})
    mapping = {v: i for i, v in enumerate(ids)}
    endpoints = np.array([(mapping[a], mapping[b]) for a, b in sorted(edges)], dtype=np.int64)
    degree = np.bincount(endpoints.ravel(), minlength=len(ids))
    partitions = np.searchsorted([10, 20, 40, 80], degree, side='right')
    labels = np.array([GROUPS[i] for i in partitions])
    graph = SyntheticGraph(labels, endpoints[:, 0], endpoints[:, 1], 0, 0)
    provenance = dict(source=SOURCE, file_sha256=hashlib.sha256(raw).hexdigest(),
        nodes=len(ids), edges=len(edges), id_mapping='sorted original IDs to contiguous IDs',
        edge_semantics='undirected input stored once with canonical endpoint order',
        predicates='degree buckets derived from full real topology; not real countries',
        legacy_property='country stores a degree-bucket label for shared query adapters',
        raw_dataset_redistributed=False)
    return graph, provenance
