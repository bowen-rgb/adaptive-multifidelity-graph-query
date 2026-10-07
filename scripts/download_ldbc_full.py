"""Official SNB v1 initial snapshot, one-partition updates and parameters.

HTTPS origin plus recorded SHA-256 provides reproducibility after download, not
an independent published checksum certification. Raw data stays outside Git.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import urllib.request
from graph_mf.ldbc_full import file_sha256

p=argparse.ArgumentParser()
p.add_argument('--scale-factor',choices=['0.1','0.3','1','3','10'],default='0.1')
p.add_argument('--output',required=True)
a=p.parse_args()
try:
    import zstandard
except ImportError:
    raise SystemExit('Install optional decompressor: python -m pip install zstandard')
root=Path(a.output).resolve()
# Normalize every archive member through Path; extended Windows paths reject '/'.
import os
if os.name=='nt':
    root=Path(chr(92)*2+'?'+chr(92)+str(root))
root.mkdir(parents=True,exist_ok=True)
sf=a.scale_factor
urls={
    'initial':f'https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf{sf}-CsvComposite-LongDateFormatter.tar.zst',
    'updates':f'https://datasets.ldbcouncil.org/snb-interactive-v1-updates/social_network-sf{sf}-numpart-1.tar.zst',
    'parameters':f'https://datasets.ldbcouncil.org/snb-interactive-v1-parameters/substitution_parameters-sf{sf}.tar.zst'}
meta=dict(scale_factor=sf,format='CsvComposite LongDateFormatter',source='https://ldbcouncil.org/benchmarks/snb/datasets/',files={})
for name,url in urls.items():
    dest=root/(name+'.tar.zst')
    if dest.exists():
        raise ValueError('Fresh directory required; existing files are not silently trusted')
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(request,timeout=60) as src,dest.open('wb') as out:
        shutil.copyfileobj(src,out)
    digest=file_sha256(dest)
    meta['files'][name]=dict(url=url,bytes=dest.stat().st_size,sha256=digest)
    with dest.open('rb') as f,zstandard.ZstdDecompressor().stream_reader(f) as reader,tarfile.open(fileobj=reader,mode='r|') as archive:
        for member in archive:
            parts=PurePosixPath(member.name).parts
            if '..' in parts or PurePosixPath(member.name).is_absolute() or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive path')
            target=root/name/Path(*parts)
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(member) as src,target.open('wb') as out:
                    shutil.copyfileobj(src,out)
            else:
                raise ValueError('Unsupported archive member')
    (root/'downloads.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(name,dest.stat().st_size,digest,flush=True)
