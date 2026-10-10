"""Generate auditable summaries of v0.19 gates, not a full adaptive SNB claim."""
import csv
import json
from pathlib import Path
from statistics import median
from graph_mf.synthetic import numpy


def read(path):
    with path.open(newline='') as handle:return list(csv.DictReader(handle))


def summarize(root,baseline):
    meta=json.loads((root/'metadata.json').read_text())
    if meta['status']!='completed':raise ValueError('Completed experiment required')
    rows=read(root/'requests.csv');seeds=meta['seeds']['test'] if isinstance(meta['seeds'],dict) else meta['seeds']
    count=len(meta['parameters']['test']) if isinstance(meta['parameters'],dict) else len(meta['parameters'])
    modes=sorted({r['mode'] for r in rows})
    if len(rows)!=len(seeds)*count*len(modes) or len({(r['seed'],r['parameter'],r['mode']) for r in rows})!=len(rows):
        raise ValueError('Incomplete/duplicate requests')
    np=numpy();indices=np.random.default_rng(48019).integers(0,len(seeds),(10000,len(seeds)))
    def costs(mode):return np.array([sum(float(r['online_ms']) for r in rows if r['mode']==mode and int(r['seed'])==s) for s in seeds])
    base=costs(baseline);summary=[]
    builds=read(root/'builds.csv');build_ms=sum(float(r['build_ms']) for r in builds if r.get('split','test')=='test')
    for mode in modes:
        selected=[r for r in rows if r['mode']==mode];cost=costs(mode)
        boot=base[indices].sum(axis=1)/cost[indices].sum(axis=1)
        summary.append(dict(mode=mode,requests=len(selected),quality_passes=sum(r['meets_quality']=='True' for r in selected),
            approximate=sum(float(r['fidelity'])<1 for r in selected),online_ms=float(cost.sum()),
            upstream_online_ratio=float(base.sum()/cost.sum()),bootstrap_low=float(np.quantile(boot,.025)),
            bootstrap_high=float(np.quantile(boot,.975)),
            with_test_bundle_ratio=float(base.sum()/(cost.sum()+(build_ms if mode.startswith('fixed') or mode=='adaptive' else 0))),
            max_count_error=max(float(r['max_count_error']) for r in selected)))
    (root/'summary.json').write_text(json.dumps(dict(baseline=baseline,test_bundle_ms=build_ms,modes=summary),indent=2)+'\n')
    return summary


def main():
    pilot=Path('results/neo4j/ic5-adaptive-v019/validated')
    confirm=Path('results/neo4j/ic5-confirmation-v019')
    lines=['# v0.19 — Dense aggregation and remaining validation','',
        'The full adaptive SNB benefit is still unproven. This release screens official',
        'IC5/IC6/IC12 density, tests IC5 physical post sampling on fresh root holdouts,',
        'and records negative quality results rather than enabling a failed mixed adapter.','',
        '## Official aggregate screening','',
        '| Query | Unique substitutions | Nonempty results | Median top count | Positive groups with count 1 |',
        '|---|---:|---:|---:|---:|']
    rows=read(Path('results/neo4j/ldbc-aggregate-screen-v019/requests.csv'))
    for family in ('5','6','12'):
        part=[r for r in rows if r['family']==family]
        lines.append(f"| IC{family} | {len(part)} | {sum(int(r['returned'])>0 for r in part)} | {median(float(r['top_median']) for r in part):g} | {sum(int(r['ones']) for r in part)}/{sum(int(r['positive_groups']) for r in part)} |")
    lines+=['','The screen uses the prior updated SF0.1 snapshot, not the new initial IC5',
        'experiment database. All exact top tuples match the pinned upstream query.',
        'Each supplied substitution file contains 15 usable unique rows; failed',
        '24-row requests are retained as failed metadata, not measured experiments.',
        'Custom IC5 minDate=-1 increases the median top count to 19 (maximum 61),',
        'but these are custom wide-window parameters, not official substitutions.','',
        '## Fresh-root IC5 calibration and confirmation','',
        'Fit: 5 roots / 4 rank seeds. Calibration: 5 disjoint roots / 20 rank seeds.',
        'Test: 10 new roots / 6 new rank seeds. Approximate tiers 25/50/75/90% all',
        'fail the calibration target: top-20 recall >= 90% and maximum count error',
        '<= 20%. Missing true forums count as errors. Forum IDs distinguish equal titles.',
        'A missing positive-count forum incurs 100% error under this contract; hence',
        'the maximum-count criterion effectively requires retaining all positive true',
        'top-20 forums, even though the separate recall threshold is 90%. A contract',
        'that permits missing items would be different and needs a new preregistered',
        'calibration/holdout experiment; these results do not rule out every estimator.',
        'The empirical seed-max calibration is not a formal new-root confidence bound.',
        'The profile is frozen for independent confirmation; no test oracle chooses a tier.','',
        '| Run | Policy | Quality passes | Approximate requests | Upstream online ratio (95% seed bootstrap) | Ratio charging test view bundle |',
        '|---|---|---:|---:|---:|---:|']
    for title,root,baseline in [('concurrent pilot',pilot,'reference'),('isolated confirmation',confirm,'reference_pristine')]:
        for row in summarize(root,baseline):
            lines.append(f"| {title} | {row['mode']} | {row['quality_passes']}/{row['requests']} | {row['approximate']} | {row['upstream_online_ratio']:.3f} [{row['bootstrap_low']:.3f}, {row['bootstrap_high']:.3f}] | {row['with_test_bundle_ratio']:.3f} |")
    meta=json.loads((pilot/'metadata.json').read_text());fault=meta['invalidation_test']
    lines+=['','Pilot timings overlapped full reference replay and dataset preparation; they',
        'are not isolated performance claims. Confirmation runs after that work ends,',
        'against an additional pristine initial database with no sample relationships.',
        'The augmented upstream baseline is also recorded to expose storage/plan effects.',
        'Each block reuses ten roots; sixty records are not sixty independent parameters.',
        'Oracle checks warm these roots and query plans before timing; this is a',
        'warm-cache holdout comparison, not cold first-use parameter latency.',
        'Bootstrap uses six entire seed blocks and is descriptive on one machine.',
        'All four physical views are charged as actually built, including discarded probes.',
        'Training/preparation in the pilot takes %.2f s; no lifecycle gain is claimed.'%(meta['training_ms']/1000),
        'A calibration-rejected policy would skip view construction in deployment; the',
        'charged test bundle above represents this experiment, not necessary exact-only cost.',
        'Graph import, warmup, profile file reading and test-oracle work are excluded online.',
        'Confirmation also checks 240 sampled answers against an independently loaded CSV oracle.','',
        '## Update safety','',
        f"Controlled insertion: stale rejection, exact fallback, changed-source rebuild refusal, old-generation rejection and legitimate empty answers all pass. Fallback {fault['exact_fallback_ms']:.2f} ms; restored-snapshot recovery {fault['recovery_ms']/1000:.2f} s.",
        'The mutation explicitly invalidates sample state atomically. This is not an',
        'arbitrary external-write detector or a concurrent update/full official Update6 proof.',
        'Source totals detect this insertion, but not property edits or same-size rewrites.',
        'Two overlapping development attempts are marked interrupted and excluded.','',
        '## SF1 quality only','',
        '| Fidelity | Nonempty holdout quality passes | Failed seed epochs | Maximum count error |',
        '|---|---:|---:|---:|']
    root=Path('results/memory/ic5-sf1-quality-v019-complete');sf=json.loads((root/'metadata.json').read_text());rows=read(root/'quality.csv')
    density=read(root/'density.csv');nonempty={r['parameter'] for r in density if r['split']=='test' and int(r['groups'])>0}
    for f in (.25,.5,.75,.9,1.):
        part=[r for r in rows if r['split']=='test' and float(r['fidelity'])==f and r['parameter'] in nonempty]
        lines.append(f"| {f:g} | {sum(r['meets_quality']=='True' for r in part)}/{len(part)} | {len({r['seed'] for r in part if r['meets_quality']!='True'})}/50 | {100*max(float(r['max_count_error']) for r in part):.1f}% |")
    lines+=['',f"Official initial SF1: {sf['people']:,} people, {sf['forums']:,} forums, {sf['posts']:,} posts. Five calibration roots / 20 seeds and 20 other test roots / 50 seeds; custom full membership window.",
        f"{20-len(nonempty)} of 20 test roots have empty results; their empty/empty agreement is excluded from the table. Quality-only calibration selects fidelity {sf['least_calibrated_fidelity']:g}. This selection omits the database cost gate and is not live adaptive performance.",
        'Raw CSV inputs stay outside Git; table hashes and row counts are published.',
        'This is not SF1 Neo4j throughput, official substitution coverage or certification.','',
        '## New parameter stress','',
        'Three previously fitted topology profiles each face 100 new rank seeds and',
        '3,000 unique intervals, disjoint from training, pilot and confirmation.',
        'Each topology: 0/4,000 supported node/edge answers violate their individual',
        '5/10/20% budget. The 1,000 sparse and 1,000 unknown-country answers all run',
        'exactly. This offline quality replay adds no database speedup evidence.',
        'Seeds and graph generator are shared across topologies for controlled comparison,',
        'not 300 independent graph trials. Zero observed failures is not a guarantee.','',
        '## Full reference replay and decision','']
    validation=json.loads(Path('results/neo4j/ldbc-full-v019/driver/metadata.json').read_text())
    if validation['status']!='completed' or not validation['validation_pass']:raise ValueError('Full replay not complete')
    lines+=['The latest exact implementation passes the entire 138,474-operation reference',
        'file, all 29 operation types, after the update1 repair.',
        'In validate_database mode the whole reference file is processed; the',
        'operations_requested=10000 benchmark setting does not truncate that file.',
        'This validation is not an adaptive mixed-workload speed result or certified audit.',
        'The earlier long-path import failure is retained separately; the successful',
        'run uses a new database and never reuses the partially imported one.','',
        'Dense counts alone do not make top-k approximation safe: close/tied cutoff',
        'groups can swap rank. Retain exact execution for these ranked queries.',
        'The next useful approximation target is a count-only SUM/COUNT analytical',
        'workload without a fragile top-20 boundary (e.g. separately scoped SNB BI),',
        'with independent calibration, a pristine baseline, and a mixed read/update',
        'test only after a per-query quality-and-total-cost gate passes.',
        'The CV claim remains the prior scoped 1.34x static synthetic COUNT result.']
    Path('docs/v019-ldbc-aggregation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
