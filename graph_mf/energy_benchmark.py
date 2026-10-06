"""Instrument the existing COUNT stream; no energy objective without usable counters."""
import json
import math
import os
from pathlib import Path
from time import process_time, sleep
from urllib.parse import urlparse
from .benchmark import write_csv
from .cost_benchmark import run_cost_benchmark
from .energy import EnergyWindow, probe_energy


def run_energy_benchmark(source, output, backend='memory', epochs=3, requests=30,
                         interval=.1, idle_seconds=1., max_package_watts=500.):
    if not math.isfinite(idle_seconds) or idle_seconds < .1:
        raise ValueError('At least 0.1 seconds idle baseline required')
    if backend == 'neo4j' and urlparse(os.environ.get('NEO4J_URI', 'bolt://localhost:7687')).hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('Host package measurement requires a local Neo4j endpoint')
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('New output directory required')
    capability, reader = probe_energy()
    # Validate controls even if the hardware provider is missing.
    EnergyWindow(reader, interval, max_package_watts)
    observations = []
    output.mkdir(parents=True, exist_ok=True)
    (output/'energy-capability.json').write_text(json.dumps(capability, indent=2)+'\n', encoding='utf-8')

    def idle():
        if reader is None:
            return dict(status='unavailable', joules=None, average_watts=None)
        with EnergyWindow(reader, interval, max_package_watts) as window:
            sleep(idle_seconds)
        return window.summary()

    class Meter:
        def __init__(self, **identity):
            self.identity = identity
            self.closed = False
        def __enter__(self):
            self.before = idle()
            self.window = EnergyWindow(reader, interval, max_package_watts)
            self.window.__enter__()
            self.cpu_start = process_time()
            return self
        def __exit__(self, failed, *args):
            if self.closed:
                return
            self.closed = True
            cpu = process_time()-self.cpu_start
            self.window.__exit__()
            measured = self.window.summary()
            after = idle() if not failed else dict(status='unavailable', average_watts=None)
            valid = not failed and all(r['status'] == 'measured' for r in (self.before, measured, after))
            idle_watts = (self.before['average_watts']+after['average_watts'])/2 if valid else None
            gross = measured['joules'] if valid else None
            baseline_adjusted = gross-idle_watts*measured['counter_duration_seconds'] if valid else None
            row = dict(**self.identity, status='measured' if valid else 'invalid' if reader else 'unavailable',
                joules=gross, joules_per_request=gross/self.identity['horizon'] if valid else None,
                baseline_adjusted_joules=baseline_adjusted,
                baseline_adjusted_joules_per_request=baseline_adjusted/self.identity['horizon'] if valid else None,
                idle_watts=idle_watts, python_cpu_seconds=cpu,
                window_seconds=measured['duration_seconds'],
                energy_objective_enabled=False, failed=bool(failed))
            detail = dict(**self.identity, workload=measured, idle_before=self.before, idle_after=after,
                          raw_samples=self.window.rows)
            observations.append(row)
            index = len(observations)-1
            (output/f'energy-window-{index}.json').write_text(json.dumps(detail, indent=2)+'\n', encoding='utf-8')
            write_csv(output/'energy-streams.csv', observations)

    pending = dict(status='running', energy_measured=False, energy_objective_enabled=False,
                   cpu_energy_reason=capability['cpu_energy_reason'])
    (output/'metadata.json').write_text(json.dumps(pending, indent=2)+'\n', encoding='utf-8')
    try:
        meta = run_cost_benchmark(source, output/'queries', backend, epochs, (requests,), energy_factory=Meter)
    except BaseException:
        pending['status'] = 'interrupted_or_failed'
        (output/'metadata.json').write_text(json.dumps(pending, indent=2)+'\n', encoding='utf-8')
        raise
    result = dict(status=meta['status'], version=meta['version'], timed_requests=meta['timed_requests'],
        all_counts_match_numpy=meta['all_counts_match_numpy'], backend=backend,
        energy_status='measured' if observations and all(r['status']=='measured' for r in observations) else 'unavailable_or_invalid',
        energy_measured=bool(observations) and all(r['status']=='measured' for r in observations),
        energy_objective_enabled=False, cpu_energy_reason=capability['cpu_energy_reason'],
        interval_seconds=interval, idle_seconds=idle_seconds, max_package_watts=max_package_watts,
        scope='CPU package aggregate includes Python, local database, background processes and sampler; not per-process or whole-machine energy',
        window_scope='whole stream including actual sample build, dispatch, query calls, Python reference validation and sampler; CSV/report writes and warmup excluded',
        cpu_time_scope='Python process user+system CPU time, all threads; not database CPU or energy',
        baseline_scope='mean before/after idle watts, descriptive subtraction, negative values retained; not causal attribution',
        energy_objective_reason='instrumentation-only release; no calibrated multi-policy energy table or energy policy comparison implemented')
    (output/'metadata.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    return result
