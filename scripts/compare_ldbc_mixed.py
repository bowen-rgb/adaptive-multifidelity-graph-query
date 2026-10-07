"""Serial, fresh-snapshot paired official-driver runs with all read/update types enabled.

Only an explicitly resettable ldbcmfbench* experimental database may be used.
All imports, construction, updates, warmup and execution timings remain recorded.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
from graph_mf.backends import Neo4jBackend
from graph_mf.ldbc_full import load_full

p=argparse.ArgumentParser()
p.add_argument('--reference',required=True)
p.add_argument('--java',required=True)
p.add_argument('--dataset-path',required=True)
p.add_argument('--parameters',required=True)
p.add_argument('--updates',required=True)
p.add_argument('--output',required=True)
p.add_argument('--blocks',type=int,default=3)
p.add_argument('--operations',type=int,default=10000)
p.add_argument('--warmup',type=int,default=1000)
p.add_argument('--tcr',type=float,default=0.001)
p.add_argument('--initial-import-manifest')
p.add_argument('--allow-reset-experiment-db',action='store_true')
a=p.parse_args()
database=os.environ.get('NEO4J_DATABASE','')
if not a.allow_reset_experiment_db or not database.startswith('ldbcmfbench') or not database.isalnum():
    raise ValueError('Explicit reset permission and a dedicated ldbcmfbench* database required')
output=Path(a.output)
if output.exists():
    raise ValueError('New output directory required')
output.mkdir(parents=True)
meta=dict(status='running',database=database,blocks=a.blocks,operations=a.operations,warmup=a.warmup,tcr=a.tcr,
          order='AB, BA, AB alternating; serial no other benchmark/validation processes',runs=[])
def checkpoint():
    (output/'matrix.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
try:
    checkpoint()
    for block in range(a.blocks):
        order=['reference','materialized'] if block%2==0 else ['materialized','reference']
        for variant in order:
            start=perf_counter()
            root=output/f'block-{block}-{variant}'
            root.mkdir()
            connection=Neo4jBackend()
            try:
                if not meta['runs'] and a.initial_import_manifest:
                    source=Path(a.initial_import_manifest)
                    initial=json.loads(source.read_text(encoding='utf-8'))
                    if initial['status']!='completed' or initial['database']!=database:
                        raise ValueError('Initial manifest mismatch')
                    rows=connection.driver.execute_query('MATCH (n) RETURN count(n) AS n',database_=database)[0]
                    rels=connection.driver.execute_query('MATCH ()-[r]->() RETURN count(r) AS n',database_=database)[0]
                    if (rows[0]['n'],rels[0]['n'])!=(initial['nodes'],initial['relationships']):
                        raise ValueError('Initial snapshot totals mismatch')
                    (root/'import.json').write_text(json.dumps(initial,indent=2)+'\n')
                else:
                    connection.driver.execute_query('CREATE OR REPLACE DATABASE '+database+' WAIT 30 SECONDS',database_='system')
                    initial=load_full(connection,a.dataset_path,a.reference,root/'import.json',batch_size=10000)
            finally:
                connection.close()
            cmd=[sys.executable,str(Path(__file__).with_name('run_ldbc_driver.py')),
                 '--reference',a.reference,'--java',a.java,'--parameters',a.parameters,'--updates',a.updates,
                 '--mode','execute_benchmark','--output',str(root/'driver'),
                 '--operations',str(a.operations),'--warmup',str(a.warmup),'--tcr',str(a.tcr)]
            if variant=='materialized':
                cmd.append('--materialized-ic14')
            result=subprocess.run(cmd)
            details=json.loads((root/'driver/metadata.json').read_text())
            meta['runs'].append(dict(block=block,variant=variant,import_ms=initial['import_ms'],
                driver_elapsed_ms=details.get('elapsed_ms'),preparation=details.get('preparation'),
                import_preparation_driver_ms=initial['import_ms']+details['elapsed_ms']+
                    (details.get('preparation') or {}).get('build_ms',0),
                actual_wall_ms=1000*(perf_counter()-start),exit_code=result.returncode))
            checkpoint()
            if result.returncode:
                raise RuntimeError('Official driver run failed; retain output and restore before retry')
    meta['status']='processes_completed'  # Requires schedule/result inspection before any speedup claim.
    checkpoint()
except BaseException:
    meta['status']='failed_or_interrupted'; checkpoint(); raise
