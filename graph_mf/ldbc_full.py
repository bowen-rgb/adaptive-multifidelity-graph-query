"""Streaming full SNB v1 CsvComposite/LongDateFormatter loader into a fresh database.

Uses the pinned reference importer headers and relationship mapping. It deliberately
refuses populated databases: mixed-workload runs must start from the initial snapshot.
"""
import csv
import hashlib
import json
import re
import os
from pathlib import Path
from time import perf_counter
from .snb import COMMIT

NODES = {'place': ('Place',), 'organisation': ('Organisation',), 'tagclass': ('TagClass',),
         'tag': ('Tag',), 'person': ('Person',), 'forum': ('Forum',),
         'post': ('Post', 'Message'), 'comment': ('Comment', 'Message')}
RELATIONS = {'isPartOf': 'IS_PART_OF', 'isSubclassOf': 'IS_SUBCLASS_OF',
    'isLocatedIn': 'IS_LOCATED_IN', 'hasType': 'HAS_TYPE', 'hasCreator': 'HAS_CREATOR',
    'replyOf': 'REPLY_OF', 'containerOf': 'CONTAINER_OF', 'hasMember': 'HAS_MEMBER',
    'hasModerator': 'HAS_MODERATOR', 'hasTag': 'HAS_TAG', 'hasInterest': 'HAS_INTEREST',
    'knows': 'KNOWS', 'likes': 'LIKES', 'studyAt': 'STUDY_AT', 'workAt': 'WORK_AT'}


def filesystem_path(path):
    """Absolute extended paths avoid Win32's legacy 260-character CSV limit."""
    resolved = str(Path(path).resolve())
    if os.name == 'nt' and not resolved.startswith('\\\\?\\'):
        resolved = ('\\\\?\\UNC\\' + resolved[2:]) if resolved.startswith('\\\\') else '\\\\?\\' + resolved
    return Path(resolved)


def file_sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def reference_headers(reference):
    reference = Path(reference)
    import subprocess
    commit = subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != COMMIT:
        raise ValueError('Pinned reference checkout required')
    return dict(line.split() for line in (reference/'cypher/scripts/headers.txt').read_text().splitlines())


def parse_node(header, row, base):
    if len(header) != len(row):
        raise ValueError('CSV column count mismatch')
    props, labels = {}, list(NODES[base])
    for descriptor, value in zip(header, row):
        name, datatype = descriptor.rsplit(':', 1)
        if descriptor == ':LABEL':
            expected={'place': {'city','country','continent'}, 'organisation': {'company','university'}}
            if value not in expected.get(base,set()):
                raise ValueError('Unexpected SNB subtype label')
            labels.append(value.capitalize())
        elif datatype.startswith('ID(') or datatype in ('LONG', 'INT'):
            props[name] = int(value)
        elif datatype == 'STRING[]':
            props[name] = value.split(';') if value else []
        else:
            # neo4j-admin import maps empty string cells to absent properties.
            if value:
                props[name] = value
    return props, labels


def batches(path, size):
    with path.open(encoding='utf-8', newline='') as f:
        reader = csv.reader(f, delimiter='|')
        next(reader)
        batch = []
        for row in reader:
            batch.append(row)
            if len(batch) == size:
                yield batch
                batch = []
        if batch:
            yield batch


def load_full(connection, data_dir, reference, output, batch_size=2000):
    if connection.database in ('neo4j', 'system'):
        raise ValueError('Use a dedicated fresh LDBC database, never the project/default database')
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('Positive batch size required')
    output = Path(output)
    if output.exists():
        raise ValueError('New manifest path required')
    headers = reference_headers(reference)
    data_dir = filesystem_path(data_dir)
    files = {stem: sorted(p for p in (data_dir/Path(stem).parent).glob(Path(stem).name+'_*.csv')
                         if re.fullmatch(re.escape(Path(stem).name)+r'_\d+_\d+\.csv', p.name))
             for stem in headers}
    if any(not paths for paths in files.values()):
        raise ValueError('All reference node and relationship tables required')
    def execute(q, **params):
        return connection.driver.execute_query(q, parameters_=params, database_=connection.database)[0]
    if execute('MATCH (n) RETURN count(n) AS n')[0]['n']:
        raise ValueError('Fresh empty database required; restore/reload between mixed runs')
    meta = dict(status='loading', reference_commit=COMMIT, database=connection.database,
                format='CsvComposite LongDateFormatter', files=[], nodes=0, relationships=0)
    output.parent.mkdir(parents=True, exist_ok=True)
    def checkpoint():
        output.write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    checkpoint()
    start = perf_counter()
    try:
        for label in NODES.values():
            execute(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label[0]}) REQUIRE n.id IS UNIQUE')
        # Nodes first; reference header ordering interleaves the static relationships.
        ordered = sorted(files, key=lambda s: '_' in Path(s).name)
        for stem in ordered:
            base = Path(stem).name
            header = headers[stem].split('|')
            for path in files[stem]:
                count = 0
                for batch in batches(path, batch_size):
                    if base in NODES:
                        grouped = {}
                        for row in batch:
                            props, labels = parse_node(header, row, base)
                            grouped.setdefault(tuple(labels), []).append(props)
                        for labels, rows in grouped.items():
                            execute('UNWIND $rows AS row CREATE (n:'+':'.join(labels)+') SET n=row', rows=rows)
                        meta['nodes'] += len(batch)
                    else:
                        src, rel, dst = base.split('_')
                        rows = []
                        for row in batch:
                            if len(row) != len(header):
                                raise ValueError('Relationship CSV column mismatch')
                            rows.append(dict(a=int(row[0]), b=int(row[1]), props={
                                h.split(':')[0]: int(v) for h,v in zip(header[2:],row[2:])}))
                        q = ('UNWIND $rows AS row MATCH (a:'+NODES[src][0]+' {id:row.a}),'
                            '(b:'+NODES[dst][0]+' {id:row.b}) CREATE (a)-[r:'+RELATIONS[rel]+']->(b) '
                            'SET r=row.props RETURN count(r) AS n')
                        if execute(q, rows=rows)[0]['n'] != len(rows):
                            raise RuntimeError('Missing relationship endpoints')
                        meta['relationships'] += len(batch)
                    count += len(batch)
                digest = file_sha256(path)
                meta['files'].append(dict(name=str(path.relative_to(data_dir)), rows=count, sha256=digest))
                print(base, count, flush=True)
                checkpoint()
        for label in ('City', 'Country', 'Message'):
            execute(f'CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE')
        for label, prop in [('Country','name'), ('Message','creationDate'), ('Person','firstName'),
                            ('Post','creationDate'), ('Tag','name'), ('TagClass','name')]:
            execute(f'CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})')
        execute('CALL db.awaitIndexes(120)')
        nodes = execute('MATCH (n) RETURN count(n) AS n')[0]['n']
        rels = execute('MATCH ()-[r]->() RETURN count(r) AS n')[0]['n']
        if (nodes, rels) != (meta['nodes'], meta['relationships']):
            raise RuntimeError('Imported table totals mismatch')
        meta.update(status='completed', import_ms=1000*(perf_counter()-start))
        checkpoint()
        return meta
    except BaseException:
        meta['status'] = 'failed_or_interrupted'
        checkpoint()
        raise
