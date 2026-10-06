"""Sample process resident memory; sampled maxima are not exact allocation peaks."""
import os
import threading
from time import perf_counter


class MemoryMonitor:
    def __init__(self, server_pid=None, interval=0.1):
        import psutil
        self.psutil, self.interval = psutil, interval
        self.processes = {'client': psutil.Process(os.getpid())}
        if server_pid is not None:
            self.processes['server'] = psutil.Process(server_pid)
        self.identities = {k: dict(pid=p.pid, name=p.name(), create_time=p.create_time())
                           for k, p in self.processes.items()}
        self.phase, self.rows, self.errors = 'baseline', [], []
        self.stop = threading.Event()
        self.start = perf_counter()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def sample(self):
        row = dict(seconds=perf_counter()-self.start, phase=self.phase)
        for kind, process in self.processes.items():
            try:
                row[kind+'_rss_bytes'] = process.memory_info().rss
            except self.psutil.Error as exc:
                row[kind+'_rss_bytes'] = None
                self.errors.append(type(exc).__name__)
        self.rows.append(row)

    def _loop(self):
        while not self.stop.wait(self.interval):
            self.sample()

    def __enter__(self):
        self.sample()
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join()
        self.sample()

    def summary(self):
        output = []
        for phase in sorted({r['phase'] for r in self.rows}):
            rows = [r for r in self.rows if r['phase'] == phase]
            for process in self.processes:
                values = [r[process+'_rss_bytes'] for r in rows if r[process+'_rss_bytes'] is not None]
                if values:
                    output.append(dict(phase=phase, process=process, samples=len(values),
                        min_rss_bytes=min(values), max_rss_bytes=max(values),
                        mean_rss_bytes=sum(values)/len(values)))
        return output
