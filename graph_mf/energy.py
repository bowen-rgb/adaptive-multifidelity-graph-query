"""Read-only CPU-package counters; missing energy stays None, never a latency proxy."""
import math
import platform
from pathlib import Path
import shutil
import subprocess
import threading
from time import perf_counter

KERNEL_DOC = 'https://www.kernel.org/doc/html/latest/power/powercap/powercap.html'


class RaplReader:
    scope = 'sum of top-level CPU packages; includes other processes and monitor overhead'

    def __init__(self, root='/sys/class/powercap'):
        root = Path(root)
        self.zones = {}
        # Inspect two common sysfs layouts, without recursively following device links.
        seen = set()
        for name_path in sorted(set(root.glob('*/name')) | set(root.glob('*/*/name'))):
            folder = name_path.parent
            name = name_path.read_text().strip()
            if not name.startswith('package-') or folder.resolve() in seen:
                continue
            if name in self.zones:
                raise ValueError('Duplicate package domain; ambiguous aggregation')
            limit = int((folder/'max_energy_range_uj').read_text())
            if limit <= 0:
                raise ValueError('Invalid energy counter range')
            self.zones[name] = dict(path=folder/'energy_uj', range_uj=limit)
            seen.add(folder.resolve())
        if not self.zones:
            raise FileNotFoundError('No readable top-level CPU package counters found')
        self.read()

    def read(self):
        output = {}
        for name, zone in self.zones.items():
            value = int(zone['path'].read_text())
            if not 0 <= value < zone['range_uj']:
                raise ValueError('Counter outside declared range')
            output[name] = value
        return output

    def description(self):
        return dict(provider='linux-powercap-rapl', scope=self.scope, unit='microjoules',
            source=KERNEL_DOC, zones={k: dict(path=str(v['path']), range_uj=v['range_uj']) for k,v in self.zones.items()})


def counter_delta(previous, current, range_uj, seconds, max_package_watts):
    """At most one wrap, conditional on a conservative user-supplied power ceiling.

    External resets are forbidden; they cannot always be distinguished from wraps.
    The ceiling checks ambiguity, and is never used to estimate consumed energy.
    """
    if (not all(math.isfinite(v) for v in (seconds, max_package_watts))
            or seconds <= 0 or max_package_watts <= 0 or range_uj <= 0
            or not 0 <= previous < range_uj or not 0 <= current < range_uj):
        raise ValueError('Invalid counter interval')
    allowed_uj = seconds*max_package_watts*1e6
    if allowed_uj >= range_uj:
        raise ValueError('Sampling gap permits multiple wraps; energy is ambiguous')
    delta = (current-previous) % range_uj
    if delta > allowed_uj:
        raise ValueError('Counter jump exceeds power ceiling; possible reset or invalid ceiling')
    return delta/1e6


def probe_energy():
    info = dict(platform=platform.system(), cpu_energy_status='unavailable', cpu_energy_reason=None,
                eligible_for_query_energy=False, gpu_telemetry=None)
    reader = None
    if platform.system() == 'Linux':
        try:
            reader = RaplReader()
            info.update(cpu_energy_status='available', cpu_energy_reason=None,
                        eligible_for_query_energy=True, cpu_provider=reader.description())
        except (OSError, ValueError) as exc:
            info['cpu_energy_reason'] = f'{type(exc).__name__}: {exc}'
    else:
        info['cpu_energy_reason'] = 'No supported read-only CPU energy provider detected; Linux powercap is not present on this OS'
    executable = shutil.which('nvidia-smi')
    if executable:
        try:
            result = subprocess.run([executable, '--query-gpu=name,power.draw', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=5, check=True)
            info['gpu_telemetry'] = dict(provider='nvidia-smi', raw_snapshot=result.stdout.strip(),
                query_field='power.draw', unit='watts', source='https://docs.nvidia.com/deploy/nvidia-smi/index.html',
                eligible_for_query_energy=False, reason='GPU-only board power snapshot; current Neo4j queries run on CPU')
        except (OSError, subprocess.SubprocessError) as exc:
            info['gpu_telemetry'] = dict(status='unavailable', reason=type(exc).__name__)
    return info, reader


class EnergyWindow:
    def __init__(self, reader=None, interval=.1, max_package_watts=500.):
        if not math.isfinite(interval) or interval <= 0 or not math.isfinite(max_package_watts) or max_package_watts <= 0:
            raise ValueError('Positive finite sampling interval and power ceiling required')
        self.reader, self.interval, self.max_package_watts = reader, interval, max_package_watts
        self.rows, self.errors = [], []
        self.stop = threading.Event()
        self.thread = None

    def sample(self):
        try:
            counts = self.reader.read()
            timestamp = perf_counter()
            if self.rows and set(counts) != set(self.rows[0]['counters']):
                raise ValueError('Counter domain set changed')
            self.rows.append(dict(seconds=timestamp-self.start, counters=counts))
        except (OSError, ValueError) as exc:
            self.errors.append(f'{type(exc).__name__}: {exc}')
            self.stop.set()

    def _loop(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.start = perf_counter()
        if self.reader:
            self.sample()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join()
            self.sample()
        self.duration_seconds = perf_counter()-self.start

    def summary(self):
        result = dict(status='unavailable', joules=None, average_watts=None,
                      duration_seconds=self.duration_seconds, samples=len(self.rows), errors=list(self.errors),
                      max_package_watts=self.max_package_watts,
                      assumptions='power ceiling valid per package; no external resets; no overlapping domain aggregation')
        if not self.reader:
            result['reason'] = 'CPU counter source unavailable'
            return result
        result['scope'] = self.reader.scope
        if self.errors or len(self.rows) < 2:
            result.update(status='invalid', reason='Incomplete counter samples')
            return result
        try:
            totals = {k: 0. for k in self.rows[0]['counters']}
            for before, after in zip(self.rows, self.rows[1:]):
                for name in totals:
                    totals[name] += counter_delta(before['counters'][name], after['counters'][name],
                        self.reader.zones[name]['range_uj'], after['seconds']-before['seconds'], self.max_package_watts)
            duration = self.rows[-1]['seconds']-self.rows[0]['seconds']
            if sum(totals.values()) <= 0:
                raise ValueError('No counter progress; resolution or disabled counter cannot establish zero energy')
            result.update(status='measured', joules=sum(totals.values()), domain_joules=totals,
                          average_watts=sum(totals.values())/duration, counter_duration_seconds=duration)
        except ValueError as exc:
            result.update(status='invalid', reason=str(exc))
        return result


def require_query_energy(record):
    """Gate objective use; never accept GPU-only, missing or invalid measurements."""
    if (record.get('status') != 'measured' or record.get('scope') != RaplReader.scope
            or not isinstance(record.get('joules'), (int, float))
            or not math.isfinite(record['joules']) or record['joules'] <= 0):
        raise ValueError('Measured CPU-package energy required; energy objective remains disabled')
    return record['joules']
