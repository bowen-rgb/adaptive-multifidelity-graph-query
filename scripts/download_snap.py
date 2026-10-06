"""Download the pinned official SNAP file; do not redistribute raw data in Git."""
import argparse
import hashlib
from pathlib import Path
from urllib.request import urlopen

URL = 'https://snap.stanford.edu/data/facebook_combined.txt.gz'
SHA256 = '125e84db872eeba443d270c70315c256b0af43a502fcfe51f50621166ad035d7'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('results/local/facebook_combined.txt.gz'))
    args = parser.parse_args()
    if args.output.exists():
        data = args.output.read_bytes()
    else:
        with urlopen(URL, timeout=60) as response:
            data = response.read(10_000_001)
        if len(data) > 10_000_000:
            raise ValueError('Unexpected dataset size')
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Dataset checksum mismatch; file not written')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists():
        args.output.write_bytes(data)
    print(f'Verified {args.output}: {len(data)} bytes, SHA256 {SHA256}')


if __name__ == '__main__':
    main()
