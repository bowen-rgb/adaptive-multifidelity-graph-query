"""Reject corrupted evidence rather than silently changing performance claims."""
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.report_dlss_ablation import summarize


class AblationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        fixture = Path(__file__).resolve().parents[1] / 'results/memory/dlss-ablation-v016'
        for name in ('metadata.json', 'streams.csv', 'requests.csv', 'builds.csv'):
            shutil.copyfile(fixture / name, self.source / name)

    def test_duplicate_request_is_rejected(self):
        path = self.source / 'requests.csv'
        with path.open(newline='') as f:
            rows = list(csv.reader(f))
        with path.open('a', newline='') as f:
            csv.writer(f).writerow(rows[1])
        with self.assertRaisesRegex(ValueError, 'Duplicate request'):
            summarize(self.source)

    def test_missing_preparation_epoch_is_rejected(self):
        path = self.source / 'builds.csv'
        with path.open(newline='') as f:
            rows = list(csv.reader(f))
        with path.open('w', newline='') as f:
            csv.writer(f).writerows(rows[:-1])
        with self.assertRaisesRegex(ValueError, 'Incomplete preparation'):
            summarize(self.source)
