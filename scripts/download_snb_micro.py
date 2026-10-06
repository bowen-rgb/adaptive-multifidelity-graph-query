"""Download hash-pinned official SNB v1 micro-fixture inputs; retain upstream license."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
from graph_mf.snb import COMMIT, FILES, UPSTREAM


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = dict(source=UPSTREAM, commit=COMMIT, files={})
    for name in (*FILES, 'LICENSE.txt', 'NOTICE.txt'):
        prefix = 'cypher/test-data/vanilla/dynamic/' if name in FILES else ''
        url = f'https://raw.githubusercontent.com/ldbc/ldbc_snb_interactive_v1_impls/{COMMIT}/{prefix}{name}'
        path = args.output/name
        raw = path.read_bytes() if path.exists() else urllib.request.urlopen(url, timeout=20).read()
        digest = hashlib.sha256(raw).hexdigest()
        if name in FILES and digest != FILES[name]:
            raise ValueError('Downloaded/local file hash mismatch: '+name)
        if not path.exists():
            path.write_bytes(raw)
        manifest['files'][name] = dict(sha256=digest, bytes=len(raw), source=url)
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2))


if __name__ == '__main__':
    main()
