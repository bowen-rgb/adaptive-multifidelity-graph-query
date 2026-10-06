"""Full IS3 tuple checks on a micro-fixture, plus explicitly custom COUNT experiments."""
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from . import __version__
from .backends import Neo4jBackend
from .benchmark import relative_error, write_csv
from .snb import load_snb, SNBMemory, SNBNeo4j


def run_snb_benchmark(dataset_path, output, backend='memory', epochs=3, root_count=32):
    if type(epochs) is not int or epochs < 2 or type(root_count) is not int or root_count < 2:
        raise ValueError('At least two sample epochs and roots required')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('New output directory required')
    graph = load_snb(dataset_path)
    reference = SNBMemory(graph)
    ordered = sorted(graph.persons, key=lambda p: (len(reference.adj[p]), p))
    n = min(root_count,len(ordered))
    roots = [ordered[i*(len(ordered)-1)//(n-1)] for i in range(n)]
    meta = dict(status='running',version=__version__,backend=backend,provenance=graph.provenance,
        graph_sha256=graph.fingerprint,nodes=len(graph.persons),edges=len(graph.edges),epochs=epochs,
        roots=[dict(id=p,degree=len(reference.adj[p])) for p in roots],
        root_selection='deterministic quantiles across full-snapshot degree then ID, includes degree extremes',
        official_scope='IS3 ordered tuple semantics on all Person IDs in pinned projection; no official driver, updates or full benchmark',
        custom_queries=['anchored friends_count','distinct persons at distance 1..2 excluding root'],
        estimator_scope='uniform neighbor inclusion, root held fixed, 1/f only for one-hop count; no calibrated budget guarantee',
        multi_hop_scope='always exact; requested low fidelity is rejected by exact fallback',
        performance_scope='micro-fixture semantic check, sequential requests, not representative scale/throughput evidence',
        energy_measured=False,nsga_adaptive_integrated=False)
    output.mkdir(parents=True,exist_ok=True)
    def checkpoint():
        (output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
    checkpoint()
    connection = None
    rows, builds, is3_rows = [], [], []
    try:
        if backend == 'neo4j':
            connection = Neo4jBackend()
            client = SNBNeo4j(graph,connection)
            start = perf_counter()
            client.seed()
            client.seed()  # Idempotence plus full property/edge snapshot validation.
            meta['import_and_double_validation_ms'] = 1000*(perf_counter()-start)
        elif backend == 'memory':
            client = SNBMemory(graph)
        else:
            raise ValueError('Unknown backend')
        for person_id in sorted(graph.persons):
            observed = client.query('is3',person_id)
            expected = reference.query('is3',person_id)['value']
            if observed['value'] != expected:
                raise RuntimeError('IS3 ordered tuples differ from Python reference')
            is3_rows.append(dict(person_id=person_id,rows=len(expected),query_ms=observed['query_ms']))
        write_csv(output/'is3-validation.csv',is3_rows)
        print(f'IS3 validated all {len(is3_rows)} persons',flush=True)
        for epoch in range(epochs):
            seed = 31000+epoch
            start = perf_counter()
            client.prepare(seed)
            builds.append(dict(epoch=epoch,sample_seed=seed,build_ms=1000*(perf_counter()-start)))
            reference.prepare(seed)
            for person_id in roots:
                for kind, fidelities in [('friends_count',(.1,.25,.5,.75,1.)),('reach_2_count',(.1,1.))]:
                    exact = reference.query(kind,person_id)['value']
                    for f in fidelities:
                        observed = client.query(kind,person_id,f)
                        expected = reference.query(kind,person_id,f)
                        if observed['value'] != expected['value'] or observed['estimate'] != expected['estimate']:
                            raise RuntimeError('Projected SNB raw COUNT/estimate mismatch')
                        rows.append(dict(epoch=epoch,sample_seed=seed,person_id=person_id,degree=len(reference.adj[person_id]),
                            kind=kind,requested_fidelity=f,effective_fidelity=observed['fidelity'],
                            raw_count=observed['value'],estimate=observed['estimate'],exact=exact,
                            relative_error=relative_error(observed['estimate'],exact),query_ms=observed['query_ms'],
                            fallback_reason=observed['fallback_reason']))
            write_csv(output/'raw-results.csv',rows)
            write_csv(output/'sample-builds.csv',builds)
            print(f'COUNT epoch {epoch+1}/{epochs} validated',flush=True)
        summary = []
        for kind,fids in [('friends_count',(.1,.25,.5,.75,1.)),('reach_2_count',(.1,1.))]:
            for f in fids:
                selected = [r for r in rows if r['kind']==kind and r['requested_fidelity']==f]
                summary.append(dict(kind=kind,requested_fidelity=f,requests=len(selected),
                    mean_error=mean(r['relative_error'] for r in selected),max_error=max(r['relative_error'] for r in selected),
                    mean_query_ms=mean(r['query_ms'] for r in selected),
                    zero_sample_nonzero_truth=sum(r['raw_count']==0 and r['exact']>0 for r in selected),
                    fallbacks=sum(r['fallback_reason'] is not None for r in selected)))
        write_csv(output/'summary.csv',summary)
        meta.update(status='completed',timed_requests=len(rows)+len(is3_rows),
            is3_all_ordered_tuples_match=True,all_raw_counts_match=True,
            exact_zero_degree_persons=sum(not reference.adj[p] for p in graph.persons),
            max_degree=max(map(len,reference.adj.values())))
        checkpoint()
        return meta
    except BaseException:
        meta['status']='interrupted_or_failed'
        checkpoint()
        raise
    finally:
        if connection:
            connection.close()
