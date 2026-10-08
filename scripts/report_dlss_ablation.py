"""Whole-epoch paired bootstrap and accuracy/cost ablation summary."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean
from graph_mf.synthetic import numpy


def summarize(source):
    meta=json.loads((source/'metadata.json').read_text())
    if meta['status']!='completed' or not meta['all_raw_counts_match']:
        raise ValueError('Completed, validated ablation required')
    with (source/'streams.csv').open(newline='') as f:streams=list(csv.DictReader(f))
    with (source/'requests.csv').open(newline='') as f:requests=list(csv.DictReader(f))
    with (source/'builds.csv').open(newline='') as f:builds=list(csv.DictReader(f))
    if sorted(int(r['epoch']) for r in builds)!=list(range(meta['epochs'])):
        raise ValueError('Incomplete preparation coverage')
    preparation=sum(float(r['build_ms']) for r in builds)
    np=numpy();resamples=np.random.default_rng(16016).integers(0,meta['epochs'],size=(10000,meta['epochs']))
    keyed={(int(r['epoch']),r['mode']):r for r in streams}
    if len(keyed)!=len(streams) or len(keyed)!=meta['epochs']*len(meta['modes']):
        raise ValueError('Duplicate or incomplete paired epochs')
    request_keys=[(r['epoch'],r['mode'],r['request'],r['kind']) for r in requests]
    if len(set(request_keys))!=len(request_keys):raise ValueError('Duplicate request measurements')
    for (epoch,mode),stream in keyed.items():
        actual=[r for r in requests if int(r['epoch'])==epoch and r['mode']==mode]
        if len(actual)!=2*meta['requests'] or len(actual)!=int(stream['components']):
            raise ValueError('Incomplete stream coverage')
        if sum(r['within_budget']=='False' for r in actual)!=int(stream['failures']):
            raise ValueError('Stream error counts disagree')
    baseline=np.array([float(keyed[e,'exact']['online_ms'])+float(keyed[e,'exact']['init_ms']) for e in range(meta['epochs'])])
    output=[]
    for mode in meta['modes']:
        costs=np.array([float(keyed[e,mode]['online_ms'])+float(keyed[e,mode]['init_ms']) for e in range(meta['epochs'])])
        ratios=baseline[resamples].mean(axis=1)/costs[resamples].mean(axis=1)
        actual=[r for r in requests if r['mode']==mode]
        if len(actual)!=2*meta['epochs']*meta['requests']:raise ValueError('Incomplete request coverage')
        output.append(dict(mode=mode,epochs=meta['epochs'],mean_stream_ms=float(costs.mean()),
            online_speedup=float(baseline.sum()/costs.sum()),paired_bootstrap_low=float(np.quantile(ratios,.025)),
            paired_bootstrap_high=float(np.quantile(ratios,.975)),failures=sum(r['within_budget']=='False' for r in actual),
            components=len(actual),mean_attempts=mean(int(r['attempts']) for r in actual),
            max_error=max(float(r['error']) for r in actual),
            startup_ms=0 if mode=='exact' else meta['training_ms']+preparation,
            phase_total_speedup=float(baseline.sum()/(costs.sum()+(0 if mode=='exact' else meta['training_ms']+preparation)))))
    (source/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    return meta,output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--scale-source',type=Path)
    a=p.parse_args();meta,summary=summarize(a.source)
    short_cost=f"50k `no_history`: {next(r['phase_total_speedup'] for r in summary if r['mode']=='no_history'):.2f}× including recorded training/build/online phases."
    def table(rows):
        return '\n'.join(f"| {r['mode']} | {r['online_speedup']:.2f} | [{r['paired_bootstrap_low']:.2f}, {r['paired_bootstrap_high']:.2f}] | "
            f"{r['failures']}/{r['components']} | {r['mean_attempts']:.2f} |" for r in rows)
    scale='The independent second-scale experiment is not yet completed.'
    if a.scale_source:
        sm,sr=summarize(a.scale_source)
        short_cost+=f" 100k: {next(r['phase_total_speedup'] for r in sr if r['mode']=='no_history'):.2f}× on the same basis."
        scale=f"Second scale: {sm['nodes']:,} nodes; independently refit/recalibrated, {sm['epochs']} fresh test epochs.\n\n"+\
            '| Method | Online ratio vs exact | Paired bootstrap 95% interval | Budget failures | Mean COUNT attempts |\n'+\
            '|---|---:|---:|---:|---:|\n'+table(sr)
    Path('docs/v016-ablation-publication.md').write_text(f'''# v0.16 — What actually helps, and public evidence

## Acceptance scope

The project has a reproducible, measurable use: calibration-guided approximate COUNTs
can save query computation on known static predicates at explicit error budgets.
This supports a scoped CV engineering/research claim. It does not establish an original
DLSS algorithm, superiority over every search method, complete SNB approximate speedup,
or accuracy guarantees under changed graphs. The v0.15 longer stream demonstrated a
1.78× ratio across recorded training/preparation/online phases at a 20% budget.

## Changing-budget ablations

50,000-node synthetic graph, six independent new rank epochs, 60 request pairs/epoch,
FR/DE, identical inputs per method. Error budgets change through 20%, 5%, 10%, 20%, 5%,
20%, exercising tightening and relaxation. Every output/probe COUNT matches the raw oracle.
All variants use the same static-session fingerprint boundary and generation guards.
Session construction is measured here. No answer cache is used.

- `full`: forecast + accepted-tier history + incremental escalation.
- `no_history`: recalculates the forecasted start for each request, keeps current-sample gating.
- `no_incremental`: same history/start decisions but re-queries the full selected sample.
- `cold_incremental`: starts at the lowest tier every request and uses incremental escalation.
- `exact`: fresh exact node/edge queries without learning or sample requirements.

| Method | Online ratio vs exact | Paired bootstrap 95% interval | Budget failures | Mean COUNT attempts |
|---|---:|---:|---:|---:|
{table(summary)}

The bootstrap resamples whole paired seed epochs, not individual repeated requests.
Six blocks on one host are a small descriptive uncertainty estimate, not a general
significance/coverage guarantee. Sampling/training startup is excluded in this table;
the separate long-stream v0.15 comparison charges it explicitly. All methods share
warm-server conditions and randomized per-epoch order without cache flushing.
These short streams do not amortize startup: {short_cost}
That phase-cost comparison excludes graph import, profile loading and offline checks;
each strategy is charged the shared recorded training and all epoch builds once.

## Independent graph-size check

{scale}

This refits for each size; it is not zero-shot transfer of the 50k profile. Both graphs
use the same generator/topology family and two known predicates. Nonrepeating queries,
different topology, stale-profile detection and update workloads remain acceptance gaps.
At 100k, `no_history` misses the requested budget on 9/720 components (1.25%);
the combined variant misses on 20/720 (2.78%). The raw COUNT checks validate query
implementation, not the extrapolated estimates. Empirical bounds are not certified
coverage guarantees. The faster 100k result must be reported with these violations.

## Interpretation and implementation decision

History and incrementality must earn their cost rather than being assumed helpful.
On the 50k fixture the forecast/current-uncertainty variant without history was faster
than the combined variant, and removing incremental accumulation did not harm its
mean latency. The cold-start variant was slower than exact despite sampling.
The strongest supported mechanism is calibration-guided starting fidelity and acceptance,
not temporal history or delta accumulation in this workload. The prototype exposes
these mechanisms as optional ablations; none is presented as a proven universal improvement.
Failed demotion now resets hysteresis patience to avoid retrying the same futile low
probe on every request. Precision losses and preparation costs stay explicit.

## Public repository and CV

Repository: https://github.com/bowen-rgb/adaptive-multifidelity-graph-query (PUBLIC).
Before exposure, reachable Git history was scanned for the known session credential,
common API/token/key signatures and unredacted driver properties. No findings were
reported; this is a signature check, not security certification. Large input archives,
database credentials and environments are not tracked. Official query snapshots retain
the pinned upstream attribution, Apache LICENSE and NOTICE under `third_party/ldbc`.
No new license grant for original project code is inferred from public visibility.

[CV wording](cv-project.md) states measured scope and known limitations. Prefer the
calibration/sampling result for algorithm roles, and official-reference validation for
database roles. Be ready to reproduce and explain the contribution and error/cost trade-off.

```powershell
python scripts/benchmark_dlss_ablation.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 6 --requests 60 --output results/local/new-ablation
python scripts/report_dlss_ablation.py --source {a.source.as_posix()}
python scripts/benchmark_sample_correction.py --backend neo4j --nodes 100000 --runs 3 --output results/local/new-100k-profile
python scripts/benchmark_dlss_ablation.py --backend neo4j --source results/local/new-100k-profile --epochs 6 --requests 60 --output results/local/new-100k-ablation
python scripts/audit_publication.py --output results/local/new-publication-audit.json
```
''',encoding='utf-8')
    print(table(summary)); print(scale)


if __name__=='__main__':main()
