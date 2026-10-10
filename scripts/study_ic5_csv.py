"""Cross-scale IC5 quality only; CSV execution is not Neo4j performance evidence."""
import argparse
import json
import random
from pathlib import Path
from graph_mf.ic5_offline import load_ic5_csv
from graph_mf.ldbc_ic5_sampling import LEVELS, quality, calibrate_quality
from graph_mf.benchmark import write_csv


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,required=True)
    p.add_argument('--scale-factor',required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--calibration-epochs',type=int,default=20)
    p.add_argument('--test-epochs',type=int,default=50)
    a=p.parse_args()
    if a.output.exists():raise ValueError('Fresh output required')
    if a.calibration_epochs<2 or a.test_epochs<1:raise ValueError('Invalid epoch count')
    a.output.mkdir(parents=True)
    graph,manifest=load_ic5_csv(a.data_dir)
    roots=[int(x) for x in graph.people];random.Random(45019).shuffle(roots)
    work=dict(calibration=roots[:5],test=roots[5:25])
    truth={split:[graph.query(root,-1) for root in selected] for split,selected in work.items()}
    density=[]
    for split,answers in truth.items():
        for i,answer in enumerate(answers):
            counts=[r['postCount'] for r in answer]
            density.append(dict(split=split,parameter=i,personId=work[split][i],
                groups=len(answer),positive_groups=sum(c>0 for c in counts),
                minimum=min(counts,default=0),maximum=max(counts,default=0),
                mean=sum(counts)/max(len(counts),1)))
    rows=[]
    seeds=dict(calibration=list(range(46000,46000+a.calibration_epochs)),
               test=list(range(47000,47000+a.test_epochs)))
    for split in ('calibration','test'):
        for seed in seeds[split]:
            prefixes=graph.prefixes(seed,LEVELS)
            for i,root in enumerate(work[split]):
                for f in (*LEVELS,1.):
                    answer=graph.query(root,-1,f,prefixes)
                    metric=quality(truth[split][i],answer)
                    rows.append(dict(split=split,seed=seed,parameter=i,personId=root,fidelity=f,
                        meets_quality=metric['recall']>=.9 and metric['max_count_error']<=.2,**metric))
            print(split,seed,'checked',flush=True)
    profile=calibrate_quality([r for r in rows if r['split']=='calibration'],seeds['calibration'],5)
    chosen=min(r['fidelity'] for r in profile if r['quality_score']<=1)
    write_csv(a.output/'quality.csv',rows);write_csv(a.output/'density.csv',density)
    meta=dict(status='completed',scale_factor=a.scale_factor,scope='offline CSV IC5 minDate=-1; quality only',
        performance_measured=False,people=len(graph.people),forums=len(graph.forums),posts=len(graph.posts),
        parameter_seed=45019,parameters=work,seeds=seeds,source_manifest=manifest,
        profile=profile,least_calibrated_fidelity=chosen,
        selection='quality-only least feasible tier; no database cost gate, not the live adaptive policy',
        quality_target=dict(recall=.9,max_count_error=.2),
        independent_calibration_and_test=True,no_test_oracle_in_selection=True)
    (a.output/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n')


if __name__=='__main__':main()
