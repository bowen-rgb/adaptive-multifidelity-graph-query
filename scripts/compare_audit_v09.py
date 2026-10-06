"""Matched audit interval and timing-only recovery ablations on the static 50k graph."""
import argparse
import json
from pathlib import Path
from graph_mf.audit_benchmark import run_audit_benchmark


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('memory', 'neo4j'), default='memory')
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--requests', type=int, default=60)
    parser.add_argument('--output', type=Path, default=Path('results/local/audit-v09'))
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError('New output directory required')
    args.output.mkdir(parents=True, exist_ok=True)
    cases = [(f'interval-{i}', i, 'full', ['healthy', 'gain_fault']) for i in (5, 10, 20)]
    cases += [('timing-full', 10, 'full', ['timing_fault']),
              ('timing-targeted', 10, 'timing_only', ['timing_fault'])]
    meta = dict(status='running', backend=args.backend, cases=[],
                design='matched sample seeds; block order fixed, within-block mode order randomized; no general speedup claim')
    path = args.output/'metadata.json'
    try:
        for name, interval, strategy, scenarios in cases:
            result = run_audit_benchmark('results/neo4j/deep-v06/synthetic-50000', args.output/name,
                args.backend, args.epochs, args.requests, interval, strategy, scenarios)
            meta['cases'].append(dict(name=name, requests=result['timed_requests']))
            path.write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
        meta['status'] = 'completed'
    except BaseException:
        meta['status'] = 'interrupted_or_failed'
        raise
    finally:
        path.write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
