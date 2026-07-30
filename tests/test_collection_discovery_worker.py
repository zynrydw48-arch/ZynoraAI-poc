"""CollectionDiscoveryWorker: mirrors memoryos/background/worker.py's
IndexingWorker pattern -- its own SQLite connection, opened from inside
run() on the worker thread, while the main thread's own Database connection
to the same file stays open throughout (WAL mode supports this; it's the
same concurrent-connections setup real usage relies on)."""

import sys

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from memoryos.background.collection_discovery_worker import CollectionDiscoveryWorker
from memoryos.database.db import Database, FileRecord

_app = QApplication.instance() or QApplication(sys.argv)

WAIT_TIMEOUT_MS = 5000


def _normalize(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.linalg.norm(vectors, axis=-1, keepdims=True)


def _upsert(db, path: str, semantic_text: str, embedding: np.ndarray) -> None:
    db.upsert_file(
        FileRecord(
            id=f"id-{path}",
            path=path,
            filename=path,
            extension=".pdf",
            file_type="pdf",
            semantic_text=semantic_text,
            metadata={},
            mtime=1.0,
            indexed_at=1.0,
        ),
        embedding,
    )


def _connect_direct(signal, slot):
    signal.connect(slot, Qt.ConnectionType.DirectConnection)


def test_worker_creates_collection_from_a_real_cluster(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    main_thread_db = Database(db_path)  # stays open, mirrors real usage
    try:
        budget = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
        pitch = np.array([0.88, 0.12, 0.0, 0.0], dtype=np.float32)
        unrelated = np.array([0.0, 0.0, 0.9, 0.1], dtype=np.float32)
        embeddings = _normalize(np.vstack([budget, pitch, unrelated]))
        _upsert(main_thread_db, "budget.pdf", "Project Zephyr budget", embeddings[0])
        _upsert(main_thread_db, "pitch.pdf", "Project Zephyr pitch deck", embeddings[1])
        _upsert(main_thread_db, "vacation.pdf", "photos from a trip", embeddings[2])

        worker = CollectionDiscoveryWorker(db_path, eps=0.2, min_samples=2)
        results = []
        errors = []
        _connect_direct(worker.finished_discovery, lambda created: results.append(created))
        _connect_direct(worker.error, lambda msg: errors.append(msg))

        worker.start()
        finished = worker.wait(WAIT_TIMEOUT_MS)

        assert finished
        assert errors == []
        assert len(results) == 1
        created = results[0]
        assert len(created) == 1
        assert set(created[0].file_paths) == {"budget.pdf", "pitch.pdf"}

        # The main thread's own connection sees the new collection too (same
        # underlying file, WAL mode).
        assert len(main_thread_db.list_collections()) == 1
    finally:
        main_thread_db.close()


def test_worker_emits_empty_list_when_nothing_clusters(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    main_thread_db = Database(db_path)
    try:
        embeddings = _normalize(
            np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
        )
        _upsert(main_thread_db, "a.pdf", "alpha", embeddings[0])
        _upsert(main_thread_db, "b.pdf", "beta", embeddings[1])

        worker = CollectionDiscoveryWorker(db_path, eps=0.2, min_samples=2)
        results = []
        _connect_direct(worker.finished_discovery, lambda created: results.append(created))

        worker.start()
        finished = worker.wait(WAIT_TIMEOUT_MS)

        assert finished
        assert results == [[]]
    finally:
        main_thread_db.close()


def test_worker_emits_error_on_unexpected_failure(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    Database(db_path).close()  # create a valid, empty db file first

    def broken_init(self, path):
        raise RuntimeError("boom")

    monkeypatch.setattr(Database, "__init__", broken_init)

    worker = CollectionDiscoveryWorker(db_path)
    errors = []
    finished_signals = []
    _connect_direct(worker.error, lambda msg: errors.append(msg))
    _connect_direct(worker.finished_discovery, lambda created: finished_signals.append(created))

    worker.start()
    finished = worker.wait(WAIT_TIMEOUT_MS)

    assert finished
    assert len(errors) == 1
    assert "boom" in errors[0]
    assert finished_signals == []
