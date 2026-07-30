"""One-Click Context Summary: runs the extractive summarizer on its own
thread. Summarizing is cheap (a handful of short-sentence encode() calls,
no generation), but the spec calls for a real "sleek loading state" on the
card, not a synchronous UI freeze -- so this still gets its own QThread,
one per ResultCard rather than one MainWindow-owned slot the way
IndexingWorker/CollectionDiscoveryWorker are, since summarizing different
files is cheap and independent (no shared SQLite writes to serialize, no
reason to queue).

Unlike those two workers, this one never touches the database -- it only
calls the shared EmbeddingProvider's encode(), which is why the
torch-thread-limiting here matches DatabaseIndexer's parallel worker pool
in memoryos/indexing.py: multiple threads (indexing's pool, other
SummaryWorkers, this one) can all legitimately call the same shared model
concurrently, and letting each one's own internal BLAS/torch threading run
unbounded would oversubscribe CPU cores.
"""

import logging

from PySide6.QtCore import QThread, Signal

from memoryos.embeddings.provider import EmbeddingProvider
from memoryos.summarization.summarizer import summarize
from memoryos.utils.thread_priority import set_current_thread_background_priority

logger = logging.getLogger(__name__)


class SummaryWorker(QThread):
    finished_summary = Signal(list)  # list[str] bullets
    error = Signal(str)

    def __init__(self, text: str, embedding_provider: EmbeddingProvider, parent=None):
        super().__init__(parent)
        self._text = text
        self._embedding_provider = embedding_provider

    def run(self) -> None:
        set_current_thread_background_priority()
        try:
            import torch

            torch.set_num_threads(1)
        except ImportError:
            pass

        try:
            bullets = summarize(self._text, self._embedding_provider)
            self.finished_summary.emit(bullets)
        except Exception as exc:
            logger.exception("summary worker failed")
            self.error.emit(repr(exc))
