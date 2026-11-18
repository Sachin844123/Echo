"""Sample actual parent-plus-child RSS; sampled peaks are lower bounds."""

import threading
import psutil

from evaluation.dataset import EvaluationError


class MemorySampler:
    def __init__(self, interval_seconds: float):
        self.interval = interval_seconds
        self.process = psutil.Process()
        self.phases = {}
        self.baseline = None
        self.stop = threading.Event()
        self.thread = None
        self.phase = "setup"
        self.lock = threading.Lock()
        self.error = None
        self.missed_children = 0

    def sample(self):
        # The parent failing to sample invalidates memory measurement. Child exits
        # between enumeration and read are counted and disclosed in the report.
        with self.lock:
            phase = self.phase
        parent = self.process.memory_info().rss
        total = parent
        missed_children = 0
        for child in self.process.children(recursive=True):
            try:
                total += child.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                missed_children += 1
        with self.lock:
            self.missed_children += missed_children
            if self.baseline is None:
                self.baseline = parent
            row = self.phases.setdefault(phase, {"samples": 0, "peak_parent_rss_bytes": 0, "peak_process_tree_rss_bytes": 0})
            row["samples"] += 1
            row["peak_parent_rss_bytes"] = max(row["peak_parent_rss_bytes"], parent)
            row["peak_process_tree_rss_bytes"] = max(row["peak_process_tree_rss_bytes"], total)

    def _loop(self):
        while not self.stop.wait(self.interval):
            try:
                self.sample()
            except (psutil.Error, OSError):
                self.error = "memory_sampling_failed"
                return

    def __enter__(self):
        self.sample()
        self.thread = threading.Thread(target=self._loop, name="echo-eval-memory", daemon=True)
        self.thread.start()
        return self

    def mark(self, phase):
        with self.lock:
            self.phase = phase
        self.sample()

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop.set()
        self.thread.join()
        try:
            self.sample()
        except (psutil.Error, OSError):
            self.error = "memory_sampling_failed"
        if self.error:
            if exc_value is not None:
                exc_value.add_note(self.error)
            else:
                raise EvaluationError(self.error) from None

    def report(self):
        if self.error:
            raise EvaluationError(self.error)
        return {"sampling_interval_ms": self.interval * 1000, "baseline_parent_rss_bytes": self.baseline,
                "peak_parent_rss_bytes": max(row["peak_parent_rss_bytes"] for row in self.phases.values()),
                "peak_process_tree_rss_bytes": max(row["peak_process_tree_rss_bytes"] for row in self.phases.values()),
                "missed_child_reads": self.missed_children, "phases": self.phases,
                "interpretation": "Sampled RSS lower bound; shared pages may be double-counted across processes."}
