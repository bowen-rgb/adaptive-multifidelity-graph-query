"""Scan reachable Git blobs for common credentials; report locations, never values."""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    lines=subprocess.check_output(['git','rev-list','--objects','--all']).decode().splitlines()
    paths={line.split(' ',1)[0]:line.partition(' ')[2] for line in lines}
    patterns=[('github_token',re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})')),
              ('private_key',re.compile(rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')),
              ('cloud_key',re.compile(rb'AKIA[A-Z0-9]{16}')),
              ('api_key',re.compile(rb'sk-[A-Za-z0-9_-]{32,}'))]
    known=os.environ.get('PUBLIC_AUDIT_KNOWN_SECRET')
    if known:patterns.append(('known_session_secret',re.compile(re.escape(known.encode()))))
    process=subprocess.Popen(['git','cat-file','--batch'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    findings=[];blobs=0;redacted=0
    try:
        for oid,path in paths.items():
            process.stdin.write((oid+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().decode().split();size=int(header[2])
            data=process.stdout.read(size);process.stdout.read(1)
            if header[1]!='blob':continue
            blobs+=1
            for category,pattern in patterns:
                if pattern.search(data):findings.append(dict(category=category,object=oid,path=path))
            if path.endswith('.properties'):
                for line in data.decode(errors='replace').splitlines():
                    key,sep,value=line.partition('=')
                    if sep and any(x in key.lower() for x in ('password','secret','token')):
                        if 'REDACTED' in value.upper():redacted+=1
                        else:findings.append(dict(category='unredacted_driver_credential',object=oid,path=path))
    finally:
        process.stdin.close();process.wait()
    report=dict(status='passed' if not findings else 'findings',blobs_scanned=blobs,
                redacted_historical_driver_fields=redacted,findings=findings,
                scope='reachable local Git objects; signature/known-secret checks, not a security certification')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));raise SystemExit(bool(findings))


if __name__=='__main__':main()
