import logging
import threading
from collections.abc import Callable

log = logging.getLogger("steward.scheduler")


class Scheduler:
    """Runs `job` every `interval_s` seconds on a daemon thread. Job errors are logged, never raised."""

    def __init__(self, interval_s: float, job: Callable[[], None], name: str = "steward-sync") -> None:
        self.interval_s, self.job = interval_s, job
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.job()
            except Exception as e:  # noqa: BLE001 - the thread must outlive any job failure
                log.warning("sync job failed: %s", type(e).__name__)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5)
