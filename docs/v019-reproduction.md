# v0.19 reproduction

Use Python 3.10+ and install `.[experiments,ldbc]`. The tiny memory fallback still
has no optional dependencies. Credentials come only from local environment
variables; never commit passwords or populated env files.

```powershell
python -m unittest discover -s tests -v
python -m graph_mf --backend memory smoke
python scripts/validate_parameter_stress.py --source results/neo4j/parameter-transfer-v018 --confirmation results/neo4j/parameter-cost-guard-v018 --output results/local/new-parameter-stress
```

The stress script regenerates the published static topology graphs and checks the
old profile fingerprint, 100 new sample seeds, and globally unique new intervals.
It is an offline quality replay, not a database performance measurement.

For IC5, obtain the pinned upstream implementation and initial official SNB v1
CsvComposite LongDateFormatter inputs using the existing full runbook. Create
separate empty databases for reference replay (`ldbcmfvalidate019b`), the physical
view experiment (`ldbcmfic5bench019`), and pristine comparison
(`ldbcmfic5reference019`). The loader creates no databases and refuses nonempty
ones. The IC5 writer deliberately accepts only the experiment/test database names
in its source; it never modifies the learning database or full replay database.

```powershell
python scripts/screen_ldbc_aggregates.py --help
python scripts/benchmark_ldbc_ic5_adaptive.py --help
python scripts/confirm_ldbc_ic5_adaptive.py --help
python scripts/download_ldbc_full.py --scale-factor 1 --output <outside-repository-input-directory>
python scripts/study_ic5_csv.py --data-dir <SF1-initial-CSV-root> --scale-factor 1 --output results/local/new-sf1-quality
```

Output directories must be fresh. Run only one IC5 builder at a time, with no
external source writes. Complete imports, downloads, CSV studies and full reference
replay before confirmation timing. Confirmation requires a successful reference
metadata file, identical initial import manifests and the unchanged pilot profile;
it uses ten other roots and six fresh seeds. Its CSV oracle checks the exact
results and all four sample tiers against the physical views before each block.
The CSV oracle caches static eligibility, never measured Neo4j results or sample
counts. These oracle and warmup calls are excluded from online timings.

`python scripts/report_ldbc_v019.py` regenerates the published report and summaries
from the named completed output directories. Keep interrupted attempts and
unfavorable results; never select a profile or change the quality target using
confirmation answers. The experiment uses recall >= 0.9 and maximum relative
count error <= 0.2; it does not implement a certified approximate SNB contract.

The full driver log is stored losslessly as gzip with source SHA-256 recorded in
its companion manifest. Decode it with Python's `gzip` module to inspect every
reference operation. The publication audit also scans decompressed gzip blobs.
