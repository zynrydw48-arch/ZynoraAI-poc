"""SummaryWorker: mirrors memoryos/background/worker.py's IndexingWorker
testing pattern -- start the real QThread, wait() on it, assert on the
signals it emitted."""

import sys

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from memoryos.background.summary_worker import SummaryWorker

_app = QApplication.instance() or QApplication(sys.argv)

WAIT_TIMEOUT_MS = 5000


class FakeEmbeddingProvider:
    """Assigns each unique sentence a deterministic pseudo-random vector
    (hash-seeded) -- doesn't need to produce meaningful similarity
    relationships since these tests only check that the worker correctly
    wires summarize() and emits its result, not the algorithm's ranking
    quality (see tests/test_summarizer.py for that)."""

    @property
    def dimension(self) -> int:
        return 8

    @property
    def model_name(self) -> str:
        return "fake"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            vector = rng.random(self.dimension).astype(np.float32)
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.vstack(vectors)


def _connect_direct(signal, slot):
    signal.connect(slot, Qt.ConnectionType.DirectConnection)


def test_worker_emits_bullets_for_real_text():
    text = (
        "This is the first sentence of the document. "
        "This is the second sentence with different words. "
        "This is the third sentence about the topic. "
        "This is the fourth sentence also relevant here. "
        "This is the fifth and final sentence of it all."
    )
    worker = SummaryWorker(text, FakeEmbeddingProvider())
    results = []
    errors = []
    _connect_direct(worker.finished_summary, lambda bullets: results.append(bullets))
    _connect_direct(worker.error, lambda msg: errors.append(msg))

    worker.start()
    finished = worker.wait(WAIT_TIMEOUT_MS)

    assert finished
    assert errors == []
    assert len(results) == 1
    assert len(results[0]) == 3
    assert all(isinstance(b, str) for b in results[0])


def test_worker_emits_empty_list_for_empty_text():
    worker = SummaryWorker("", FakeEmbeddingProvider())
    results = []
    _connect_direct(worker.finished_summary, lambda bullets: results.append(bullets))

    worker.start()
    finished = worker.wait(WAIT_TIMEOUT_MS)

    assert finished
    assert results == [[]]


def test_worker_emits_error_on_unexpected_failure():
    class BrokenEmbeddingProvider(FakeEmbeddingProvider):
        def encode(self, texts):
            raise RuntimeError("model exploded")

    # Needs strictly more than DEFAULT_NUM_SENTENCES (3) *distinct*
    # sentences -- summarize() short-circuits without ever calling encode()
    # when there are 3 or fewer, which would make this test pass for the
    # wrong reason (never actually exercising the failure path).
    text = (
        "This is the first distinct sentence right here. "
        "This is the second distinct sentence right here. "
        "This is the third distinct sentence right here. "
        "This is the fourth distinct sentence right here."
    )
    worker = SummaryWorker(text, BrokenEmbeddingProvider())
    errors = []
    finished_signals = []
    _connect_direct(worker.error, lambda msg: errors.append(msg))
    _connect_direct(worker.finished_summary, lambda bullets: finished_signals.append(bullets))

    worker.start()
    finished = worker.wait(WAIT_TIMEOUT_MS)

    assert finished
    assert len(errors) == 1
    assert "model exploded" in errors[0]
    assert finished_signals == []
