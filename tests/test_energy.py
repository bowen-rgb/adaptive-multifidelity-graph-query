import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from graph_mf.energy import RaplReader, EnergyWindow, counter_delta, require_query_energy
from graph_mf.energy_benchmark import run_energy_benchmark


class EnergyTests(unittest.TestCase):
    def test_units_and_single_wrap(self):
        self.assertEqual(counter_delta(1000000, 3000000, 1000000000, 1, 500), 2.)
        self.assertEqual(counter_delta(900000000, 100000000, 1000000000, 1, 500), 200.)

    def test_ambiguous_gap_reset_and_invalid_values_rejected(self):
        for args in [(0, 1, 1000000, 1, 500), (500000000, 0, 1000000000, .01, 500),
                     (-1, 1, 100, 1, 1), (0, 1, 100, 0, 1)]:
            with self.assertRaises(ValueError):
                counter_delta(*args)

    def test_package_domains_exclude_overlapping_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for location, name in [('rapl0', 'package-0'), ('rapl0/core', 'core'), ('rapl1', 'package-1')]:
                path = root/location
                path.mkdir(parents=True)
                (path/'name').write_text(name)
                (path/'energy_uj').write_text('1000000')
                (path/'max_energy_range_uj').write_text('1000000000')
            reader = RaplReader(root)
            self.assertEqual(reader.read(), {'package-0': 1000000, 'package-1': 1000000})

    def test_window_aggregation_and_flat_counter_not_reported_as_zero(self):
        class Reader:
            scope = RaplReader.scope
            zones = {'package-0': {'range_uj': 1000000000}}
        window = EnergyWindow(Reader())
        window.duration_seconds = 2
        window.rows = [dict(seconds=t, counters={'package-0': v}) for t,v in [(0,900000000),(1,100000000),(2,150000000)]]
        result = window.summary()
        self.assertEqual(result['joules'], 250.)
        self.assertEqual(result['average_watts'], 125.)
        window.rows[1]['counters']['package-0'] = 900000000
        window.rows[2]['counters']['package-0'] = 900000000
        self.assertEqual(window.summary()['status'], 'invalid')
        self.assertIsNone(window.summary()['joules'])

    def test_missing_source_preserves_null_energy(self):
        with EnergyWindow() as window:
            pass
        self.assertEqual(window.summary()['status'], 'unavailable')
        self.assertIsNone(window.summary()['joules'])

    def test_objective_gate_rejects_missing_gpu_invalid_and_zero(self):
        for record in [dict(status='unavailable', joules=None),
                       dict(status='measured', scope='GPU', joules=1.),
                       dict(status='invalid', scope=RaplReader.scope, joules=1.),
                       dict(status='measured', scope=RaplReader.scope, joules=0.)]:
            with self.assertRaises(ValueError):
                require_query_energy(record)
        self.assertEqual(require_query_energy(dict(status='measured', scope=RaplReader.scope, joules=2.)), 2.)

    def test_unavailable_energy_stream_still_validates_counts(self):
        info = dict(cpu_energy_reason='unit-test provider missing')
        with tempfile.TemporaryDirectory() as folder, patch('graph_mf.energy_benchmark.probe_energy', return_value=(info, None)):
            result = run_energy_benchmark('results/neo4j/deep-v06/synthetic-50000', folder, epochs=2, requests=5)
            self.assertFalse(result['energy_measured'])
            self.assertFalse(result['energy_objective_enabled'])
            self.assertTrue(result['all_counts_match_numpy'])
            window = json.loads((Path(folder)/'energy-window-0.json').read_text())
            self.assertIsNone(window['workload']['joules'])
