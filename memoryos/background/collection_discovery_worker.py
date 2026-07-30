"""Background worker for AI Project Collections' "Discover Projects" action
-- runs CollectionManager.run_auto_discovery() on its own thread with its
own SQLite connection (same reason memoryos/background/worker.py's
IndexingWorker does this -- see memoryos/database/db.py's WAL mode note),
so a large corpus's O(n^2) clustering pass doesn't freeze the UI.

One-shot, not interruptible (no pause/cancel): clustering is a single
in-memory computation over the already-indexed corpus, not the kind of
long-running, file-by-file I/O operation indexing is.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from memoryos.collections.clustering import DEFAULT_EPS, DEFAULT_MIN_SAMPLES
from memoryos.collections.manager import DEFAULT_OVERLAP_THRESHOLD, CollectionManager
from memoryos.database.db import Database

logger = logging.getLogger(__name__)


class CollectionDiscoveryWorker(QThread):
    # list[Collection] newly created
    finished_discovery = Signal(object)
    # error message
    error = Signal(str)

    def __init__(
        self,
        db_path: Path,
        eps: float = DEFAULT_EPS,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
        parent=None,
    ):
        super().__init__(parent)
        self._db_path = db_path
        self._eps = eps
        self._min_samples = min_samples
        self._overlap_threshold = overlap_threshold

    def run(self) -> None:
        database: Database | None = None
        try:
            database = Database(self._db_path)
            manager = CollectionManager(database)
            created = manager.run_auto_discovery(
                eps=self._eps,
                min_samples=self._min_samples,
                overlap_threshold=self._overlap_threshold,
            )
            self.finished_discovery.emit(created)
        except Exception as exc:
            logger.exception("collection discovery worker failed")
            self.error.emit(repr(exc))
        finally:
            if database is not None:
                database.close()
