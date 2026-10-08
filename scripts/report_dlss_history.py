"""Reconstruct speed/error frontiers and charge recorded preparation/training."""
import argparse
import csv
import json
from pathlib import Path
from statistics import mean


def load(source):
    meta=json.loads((source/'metadata.json').read_text())
    if meta['status']!='completed' or not meta.get('all_raw_counts_match'):
        raise ValueError('Completed raw-validated source required')
    with (source/'streams.csv').open(newline='') as f: streams=list(csv.DictReader(f))
    with (source/'requests.csv').open(newline='') as f: requests=list(csv.DictReader(f))
    with (source/'preparation.csv').open(newline='') as f: prep=list(csv.DictReader(f))
    keys=[(r['epoch'],r['tier'],r['mode'],r['request'],r['kind']) for r in requests]
    if len(set(keys))!=len(keys):
        raise ValueError('Duplicate request measurements')
    for stream in streams:
        selected=[r for r in requests if (r['epoch'],r['tier'],r['mode'])==
                  (stream['epoch'],stream['tier'],stream['mode'])]
        if len(selected)!=2*meta['requests'] or len(selected)!=int(stream['components']):
            raise ValueError('Incomplete paired node/edge requests')
        if sum(r['within_budget']=='False' for r in selected)!=int(stream['failures']):
            raise ValueError('Error counts disagree with stream summary')
    return meta,streams,requests,sum(float(r['build_ms']) for r in prep)


def summarize(source):
    meta,streams,requests,preparation=load(source)
    output=[]
    for tier,budget in meta['tiers'].items():
        baseline=sum(float(r['online_ms']) for r in streams if r['tier']==tier and r['mode']=='exact')
        for mode in sorted({r['mode'] for r in streams}):
            selected=[r for r in streams if r['tier']==tier and r['mode']==mode]
            if len(selected)!=meta['epochs']:
                raise ValueError('Missing paired epochs')
            records=[r for r in requests if r['tier']==tier and r['mode']==mode]
            online=sum(float(r['online_ms']) for r in selected)
            startup=0 if mode=='exact' else meta['training_ms']+preparation
            pairs=len(records)/2
            saving=(baseline-online)/pairs
            output.append(dict(tier=tier,mode=mode,budget=budget,request_pairs=int(pairs),
                online_ms=online,startup_ms=startup,phase_total_ms=online+startup,
                online_speedup=baseline/online,phase_total_speedup=baseline/(online+startup),
                failures=sum(int(r['failures']) for r in selected),
                max_error=max(float(r['error']) for r in records),
                mean_error=mean(float(r['error']) for r in records),
                mean_attempts=mean(int(r['attempts']) for r in records),
                break_even_pairs=startup/saving if saving>0 else None))
    (source/'summary.json').write_text(json.dumps(output,indent=2)+'\n')
    return meta,output


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--long-source',type=Path)
    a=p.parse_args()
    meta,short=summarize(a.source)
    table='\n'.join(f"| {r['tier']} | {r['mode']} | {r['online_speedup']:.2f} | {r['max_error']:.2%} | "
        f"{r['failures']} | {r['mean_attempts']:.2f} | {r['phase_total_speedup']:.3f} |" for r in short)
    long_text='Long-stream comparison has not been completed.'
    if a.long_source:
        lm,long=summarize(a.long_source)
        long_text='\n'.join(f"- {r['mode']}: {r['request_pairs']:,} request pairs, online {r['online_ms']/1000:.2f} s, "
            f"recorded startup {r['startup_ms']/1000:.2f} s, phase total {r['phase_total_ms']/1000:.2f} s, "
            f"phase-total ratio {r['phase_total_speedup']:.2f}×, max error {r['max_error']:.2%}, {r['failures']} budget failures."
            for r in long)
    Path('docs/v015-dlss-history.md').write_text(f'''# v0.15 — Speed/accuracy tiers with reusable work

## DLSS-inspired scope

The controller trades allowed COUNT error for computation: quality 5%, balanced 10%,
performance 20%. These are explicit application error budgets, not NVIDIA presets.
It uses empirical calibration and history to choose the first probe, then escalates
if current uncertainty is too high. Demotion is considered after three sufficiently
confident requests. There is no neural rendering, GPU-pressure integration or formal
per-request confidence guarantee. Unseen predicates fall back to exact.

## What changed

- Start from a measured feasible forecast or the last accepted fidelity, rather than
  replaying every low tier for every request.
- Incremental node probes count only the new rank interval. Edge probes partition
  newly included directed edges into new-source/any-destination and old-source/new-
  destination groups. Parallel edges remain separate and are counted once.
- Keep graph validation at the static-session boundary and guard incremental queries
  against rank-generation replacement using published ready state. Concurrent arbitrary
  graph writers and in-place graph mutation are unsupported. Exact fallback remains exact.
- Execute fresh COUNTs for every request: no cached answer table. Only sampling ranks,
  calibration and controller history are reused. Exact terminal probes discard already
  paid approximate work. All intermediate counts match the direct Python reference.

## Short matched streams

One static 50k-node synthetic graph, FR/DE, three held-out rank epochs, 60 request pairs
per tier/epoch; mode order randomized, warm server cache without flushes. A pair is node
and edge COUNT. Repeated requests on an epoch are correlated; the epoch is the repeat
unit, not each COUNT. The fixture has only two known predicates, so this does not show
unseen-query or cross-graph generalization. No correction gain is used in either dynamic
variant because v0.14 did not establish a correction benefit.

| Tier | Method | Online ratio vs exact | Max actual error | Budget failures | Mean COUNT attempts | Ratio incl. recorded startup |
|---|---|---:|---:|---:|---:|---:|
{table}

## Longer stream and amortization

{long_text}

The phase-total comparison sums separately measured training from v0.14, sample builds
for this comparison and measured online controller/query durations. Training is charged
once to each alternative method; each tier is considered a separate deployment.
Exact pays no training or sample build. This is a composition of measured phases,
not one continuous timed lifecycle. The existing graph import, source-profile loading,
session constructor and offline oracle checking are excluded. Harness wall time includes
validation and is retained separately. No energy or whole-machine throughput claim is made.
Long runs use distinct held-out seeds; only two independent epochs and one graph limit
statistical confidence. Do not infer general 1.x/2.x speedups from these local observations.

Break-even estimates in summary.json use measured mean savings, assuming unchanged future
workload, cache, sample validity and timing. A nonpositive saving has no break-even.
Higher tiers may still overshoot empirical error estimates, and history can become stale.
Results include the slower original progressive policy and its budget failures.
Most optimized requests used one probe, so the measured gain cannot be attributed
specifically to incremental deltas. Calibration hot starts, accepted-tier reuse and
moving fingerprint work to the static-session boundary are combined here; separate
ablations against fixed calibrated tiers remain necessary.

## Reproduce

```powershell
python scripts/benchmark_dlss_history.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 3 --requests 60 --output results/local/new-frontier
python scripts/benchmark_dlss_history.py --backend neo4j --source results/neo4j/dynamic-correction-v014 --epochs 2 --seed-start 20000 --requests 4000 --tiers performance --modes exact history_incremental --output results/local/new-long-stream
python scripts/report_dlss_history.py --source {a.source.as_posix()} --long-source results/neo4j/dlss-history-v015-long
```

Existing valid synthetic import is required; no graph is deleted/reimported. Sample ranks
are explicitly refreshed once per epoch. Original experiments and full LDBC results remain.
Next gates are more independent epochs/topologies, nonrepeating parameterized aggregates,
and explicit stale-profile/update detection before deployment.
''',encoding='utf-8')
    print(table); print(long_text)


if __name__=='__main__': main()
