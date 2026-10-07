"""Run the official Java SNB driver; every query/update remains enabled and exact."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
from time import perf_counter
from graph_mf.ldbc_full import reference_headers,file_sha256
from graph_mf import __version__
from graph_mf.snb import COMMIT

p = argparse.ArgumentParser()
p.add_argument('--reference', required=True)
p.add_argument('--java', required=True)
p.add_argument('--parameters', required=True)
p.add_argument('--updates', required=True)
p.add_argument('--validation-file')
p.add_argument('--mode', choices=['validate_database', 'execute_benchmark'], required=True)
p.add_argument('--output', required=True)
p.add_argument('--scale-factor', default='0.1')
p.add_argument('--operations', type=int, default=10000)
p.add_argument('--warmup', type=int, default=1000)
p.add_argument('--threads', type=int, default=1)
p.add_argument('--tcr', type=float, default=0.001)
p.add_argument('--optimized-ic14', action='store_true')
p.add_argument('--materialized-ic14', action='store_true')
p.add_argument('--resume-from', help='Completed materialized validation manifest for a contiguous suffix; never a benchmark shortcut')
a = p.parse_args()
reference = Path(a.reference).resolve()
reference_headers(reference)
password = os.environ.get('NEO4J_PASSWORD')
database = os.environ.get('NEO4J_DATABASE')
if not password or not database or database in ('neo4j','system'):
    raise ValueError('Credentials and dedicated NEO4J_DATABASE required')
output = Path(a.output).resolve()
if output.exists():
    raise ValueError('New output directory required')
if a.mode == 'validate_database' and not a.validation_file:
    raise ValueError('Independent validation file required')
output.mkdir(parents=True)
query_dir = output/'queries'
shutil.copytree(reference/'cypher/queries', query_dir)
from graph_mf.ldbc_reference import patch_reference_queries
patch_reference_queries(query_dir)
if a.optimized_ic14:
    shutil.copyfile(Path(__file__).resolve().parents[1]/'graph_mf/cypher/ldbc_ic14_bound.cypher',
                    query_dir/'interactive-complex-14.cypher')
preparation=None
if a.materialized_ic14:
    if a.optimized_ic14:
        raise ValueError('Choose one IC14 implementation')
    from graph_mf.backends import Neo4jBackend
    from graph_mf.ldbc_weights import build_weights, patch_weight_queries
    connection=Neo4jBackend()
    try:
        if a.resume_from:
            previous=json.loads(Path(a.resume_from).read_text(encoding='utf-8'))
            if a.mode!='validate_database' or previous.get('status')!='completed' or not previous.get('validation_pass') or not previous.get('materialized_ic14') or previous.get('database')!=database:
                raise ValueError('Only contiguous successful materialized validation may resume')
            state=connection.driver.execute_query('MATCH (s:MFIC14State) RETURN s.ready AS ready,s.algorithm AS algorithm',database_=database)[0]
            if len(state)!=1 or dict(state[0])!=dict(ready=True,algorithm='exact-replies-v1'):
                raise ValueError('Matching ready weight state required')
            preparation=dict(build_ms=0,reused_validation_checkpoint=True,previous_manifest=str(Path(a.resume_from).resolve()))
        else:
            preparation=build_weights(connection)
    finally:
        connection.close()
    patch_weight_queries(query_dir)
elif a.resume_from:
    raise ValueError('Resume requires materialized validation')
config = dict(line.split('=',1) for line in (reference/'cypher/driver/benchmark.properties').read_text().splitlines()
              if '=' in line and not line.startswith('#'))
config.update(endpoint=os.environ.get('NEO4J_URI','bolt://127.0.0.1:7687'),
    user=os.environ.get('NEO4J_USER','neo4j'), password=password,
    queryDir=query_dir.as_posix()+'/', mode=a.mode, operation_count=str(a.operations),
    warmup=str(a.warmup if a.mode=='execute_benchmark' else 0), thread_count=str(a.threads),
    time_compression_ratio=str(a.tcr), status='10', ignore_scheduled_start_times='false')
config['neo4j.database'] = database
config['ldbc.snb.interactive.parameters_dir'] = Path(a.parameters).resolve().as_posix()+'/'
config['ldbc.snb.interactive.updates_dir'] = Path(a.updates).resolve().as_posix()+'/'
config['ldbc.snb.interactive.scale_factor'] = a.scale_factor
if a.validation_file:
    config['validate_database'] = Path(a.validation_file).resolve().as_posix()
meta = dict(status='running',mode=a.mode, database=database, scale_factor=a.scale_factor,
    version=__version__,reference_commit=COMMIT,
    operations_requested=a.operations, warmup_requested=a.warmup if a.mode=='execute_benchmark' else 0,
    threads=a.threads,tcr=a.tcr,optimized_ic14=a.optimized_ic14,
    materialized_ic14=a.materialized_ic14,preparation=preparation,
    all_29_operation_types_enabled=True, exact_semantics=True, certified_audit=False,
    query_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in query_dir.glob('*.cypher')})
if a.resume_from and meta['query_sha256']!=previous['query_sha256']:
    raise ValueError('Validation continuation queries changed')
meta['java_implementation_sha256']=file_sha256(reference/'cypher/target/cypher-1.2.0-SNAPSHOT.jar')
if a.validation_file:
    meta['validation_sha256'] = file_sha256(a.validation_file)
manifest = output/'metadata.json'
manifest.write_text(json.dumps(meta,indent=2)+'\n')
start = perf_counter()
def redact_exports():
    # Driver configuration exports may contain DB credentials even when stdout is safe.
    for path in output.rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.json','.log','.txt','.properties','.csv'):
            text=path.read_text(encoding='utf-8',errors='replace')
            safe=text.replace(password,'[REDACTED]')
            if safe!=text:
                path.write_text(safe,encoding='utf-8')
task_config = None
process = None
try:
    with tempfile.NamedTemporaryFile(mode='w',suffix='.properties',delete=False,encoding='utf-8') as f:
        task_config = Path(f.name)
        f.write('\n'.join(k+'='+v for k,v in config.items()))
    cmd = [str(Path(a.java).resolve()),'-Xmx2g','-cp',str(reference/'cypher/target/cypher-1.2.0-SNAPSHOT.jar'),
           'org.ldbcouncil.snb.driver.Client','-P',str(task_config),'-rd',str(output/'driver-results')]
    with (output/'driver.log').open('w',encoding='utf-8') as log:
        process = subprocess.Popen(cmd,cwd=reference/'cypher',stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                   text=True,encoding='utf-8',errors='replace')
        for line in process.stdout:
            log.write(line.replace(password,'[REDACTED]'))
            log.flush()
        code = process.wait()
    meta.update(status='process_completed' if code==0 else 'failed',exit_code=code,
                elapsed_ms=1000*(perf_counter()-start))
    log_text=(output/'driver.log').read_text(encoding='utf-8')
    if a.mode=='validate_database':
        counts={}
        for line in log_text.splitlines():
            match=re.match(r'^\s*([\d\s?,]+) / ([\d\s?,]+)\s+(Ldbc\w+)',line)
            if match:
                counts[match[3]]={k:int(re.sub(r'\D','',v)) for k,v in zip(('correct','total'),match.groups()[:2])}
        meta['operation_coverage']=counts
        meta['validated_operation_types']=len(counts)
        meta['validation_pass']='Validation Result: PASS' in log_text
        meta['status']='completed' if meta['validation_pass'] and code==0 else 'failed'
    else:
        meta['schedule_audit_pass']='PASSED SCHEDULE AUDIT' in log_text
        meta['status']='completed' if meta['schedule_audit_pass'] and code==0 else 'failed'
    # Benchmark exit status alone does not establish schedule audit success.
    manifest.write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps({k:v for k,v in meta.items() if k not in ('query_sha256','operation_coverage')},indent=2))
    raise SystemExit(code or (1 if meta['status']=='failed' else 0))
except (KeyboardInterrupt,Exception):
    if process and process.poll() is None:
        process.terminate()
        process.wait(timeout=30)
    meta.update(status='failed_or_interrupted',elapsed_ms=1000*(perf_counter()-start))
    manifest.write_text(json.dumps(meta,indent=2)+'\n')
    raise
finally:
    redact_exports()
    if task_config:
        task_config.unlink(missing_ok=True)
