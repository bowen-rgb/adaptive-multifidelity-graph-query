"""Small reproducible algorithm demo; never presents memory timings as Neo4j speedups."""
import argparse
import json
from pathlib import Path

from graph_mf.adaptive import LEVELS
from graph_mf.incremental_sampling import HistorySampler
from graph_mf.reusable import ReusableSample
from graph_mf.sample_correction import fit_joint_profile
from graph_mf.synthetic import SyntheticMemory, generate_graph


def demonstrate(nodes=50000, seed=25000):
    if seed in set(range(16000,16004)) | set(range(17000,17020)):
        raise ValueError('Demo seed must be independent of fitting/calibration')
    graph=generate_graph(nodes)
    backend=SyntheticMemory(graph)
    countries=['FR','DE']
    truth={(c,k):backend.count_component(c,1,k)['count']
           for c in countries for k in ('node','edge')}
    records=[]
    for split,seeds in [('fitting',range(16000,16004)),('calibration',range(17000,17020))]:
        for rank_seed in seeds:
            backend.prepare(rank_seed)
            for country in countries:
                for kind in ('node','edge'):
                    for fidelity in LEVELS:
                        records.append(dict(split=split,seed=rank_seed,country=country,
                            kind=kind,fidelity=fidelity,truth=truth[country,kind],
                            **backend.count_component(country,fidelity,kind)))
    profile=fit_joint_profile([r for r in records if r['split']=='fitting'],
        [r for r in records if r['split']=='calibration'],LEVELS,countries,graph.fingerprint)
    sample=ReusableSample(backend)
    sample.build(seed)
    controller=HistorySampler(profile,sample,use_history=False)
    answers=[]
    for country in countries+['ES']:
        for budget in (.05,.1,.2):
            for kind in ('node','edge'):
                result=controller.request(country,kind,budget)
                exact=backend.count_component(country,1,kind)['count']
                # The oracle is checked afterward and is not an input to selection.
                error=abs(result['estimate']-exact)/max(exact,1)
                answers.append(dict(country=country,kind=kind,budget=budget,
                    fidelity=result['fidelity'],attempts=result['attempts'],
                    estimate=result['estimate'],exact=exact,relative_error=error,
                    within_budget=error<=budget,exact_fallback=result['fallback']))
    return dict(backend='memory',performance_measured=False,nodes=nodes,
        test_seed=seed,fitting_seeds=profile['fit_seeds'],
        calibration_seeds=profile['calibration_seeds'],
        scope='toy static-graph demonstration; empirical bounds, not an accuracy guarantee',
        answers=answers)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nodes',type=int,default=50000)
    parser.add_argument('--seed',type=int,default=25000)
    parser.add_argument('--output',type=Path,default=Path('results/local/demo-joint.json'))
    args=parser.parse_args()
    report=demonstrate(args.nodes,args.seed)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Offline algorithm demo (no Neo4j performance measurement)')
    print('country kind  budget fidelity error  attempts')
    for row in report['answers']:
        print(f"{row['country']:7} {row['kind']:5} {row['budget']:6.0%} {row['fidelity']:8.0%} "
              f"{row['relative_error']:6.2%} {row['attempts']:8}")
    print(f'Full results: {args.output}')


if __name__=='__main__':main()
