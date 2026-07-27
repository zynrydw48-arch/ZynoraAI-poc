"""Sprint 8.5: DatabaseIndexer.iter_index_files() parallel extraction/vision
+ batched embedding calls. Uses a fake VisionPipeline (with an artificial
delay) and a fake EmbeddingProvider so these tests are fast and deterministic
while still exercising the real ThreadPoolExecutor-based code path -- no real
ML models needed, matching the FakeEmbeddingProvider pattern already used in
tests/test_main_window.py.
"""

import os
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from memoryos.database.db import Database
from memoryos.indexing import DatabaseIndexer
from memoryos.scanner.discover import ScannedFile
from memoryos.vision.pipeline import VisionResult

EMBED_DIM = 8


class FakeEmbeddingProvider:
    def __init__(self):
        self.encode_calls: list[int] = []  # records each call's batch size

    @property
    def dimension(self) -> int:
        return EMBED_DIM

    @property
    def model_name(self) -> str:
        return "fake"

    def encode(self, texts: list[str]) -> np.ndarray:
        self.encode_calls.append(len(texts))
        vectors = np.ones((len(texts), EMBED_DIM), dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors


class SlowFakeVisionPipeline:
    """Stands in for the real VisionPipeline: an artificial per-call delay
    makes real wall-clock parallel speedup measurable without loading any
    real ML models."""

    def __init__(self, delay_seconds: float = 0.0):
        self._delay_seconds = delay_seconds

    def analyze(self, image) -> VisionResult:
        time.sleep(self._delay_seconds)
        return VisionResult(colors=["blue"], tags=["object"], ocr_text="", caption="a scene")


def _make_image_files(tmp_path: Path, count: int) -> list[ScannedFile]:
    files = []
    for i in range(count):
        path = tmp_path / f"img_{i:03d}.png"
        Image.new("RGB", (4, 4), (i % 255, 0, 0)).save(path)
        files.append(
            ScannedFile(
                path=path,
                filename=path.name,
                extension=".png",
                file_type="image",
                mtime=path.stat().st_mtime,
                size_bytes=path.stat().st_size,
            )
        )
    return files


def _database(tmp_path: Path, name: str = "test.sqlite3") -> Database:
    return Database(tmp_path / name)


def test_parallel_is_meaningfully_faster_than_sequential(tmp_path):
    delay = 0.05
    files = _make_image_files(tmp_path, 12)

    db_sequential = _database(tmp_path, "sequential.sqlite3")
    try:
        indexer = DatabaseIndexer(
            FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(delay), db_sequential
        )
        start = time.time()
        list(indexer.iter_index_files(files, max_workers=1))
        sequential_elapsed = time.time() - start
    finally:
        db_sequential.close()

    db_parallel = _database(tmp_path, "parallel.sqlite3")
    try:
        indexer = DatabaseIndexer(
            FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(delay), db_parallel
        )
        start = time.time()
        list(indexer.iter_index_files(files, max_workers=6))
        parallel_elapsed = time.time() - start
    finally:
        db_parallel.close()

    assert parallel_elapsed < sequential_elapsed * 0.6, (
        f"parallel ({parallel_elapsed:.3f}s) not meaningfully faster than "
        f"sequential ({sequential_elapsed:.3f}s)"
    )


def test_embedding_calls_are_batched_not_one_per_file(tmp_path):
    files = _make_image_files(tmp_path, 10)
    provider = FakeEmbeddingProvider()
    database = _database(tmp_path)
    try:
        indexer = DatabaseIndexer(provider, None, SlowFakeVisionPipeline(0.0), database)
        results = list(
            indexer.iter_index_files(files, max_workers=4, embedding_batch_size=4)
        )

        assert len(results) == 10
        assert all(r.outcome == "indexed" for r in results)
        assert len(database) == 10
        assert sum(provider.encode_calls) == 10
        assert max(provider.encode_calls) > 1, "encode() was called once per file, not batched"
    finally:
        database.close()


def test_results_correct_regardless_of_completion_order(tmp_path):
    # Per-file delay varies so completion order differs from submission order.
    class VariableDelayVision:
        def __init__(self):
            self._count = 0
            self._lock = threading.Lock()

        def analyze(self, image) -> VisionResult:
            with self._lock:
                self._count += 1
                n = self._count
            time.sleep(0.01 * (n % 3))
            return VisionResult(caption=f"scene {n}")

    files = _make_image_files(tmp_path, 15)
    database = _database(tmp_path)
    try:
        indexer = DatabaseIndexer(FakeEmbeddingProvider(), None, VariableDelayVision(), database)
        results = list(indexer.iter_index_files(files, max_workers=4, embedding_batch_size=3))

        assert len(results) == 15
        assert all(r.outcome == "indexed" for r in results)
        for scanned in files:
            record = database.get_by_path(str(scanned.path))
            assert record is not None
            assert record.filename == scanned.filename
    finally:
        database.close()


def test_pause_stops_new_submissions_but_lets_in_flight_finish(tmp_path):
    files = _make_image_files(tmp_path, 10)
    resume_event = threading.Event()
    resume_event.set()
    results = []

    def consume():
        # Sprint 2's WAL-mode design requires the Database connection be
        # created and used on the same thread -- constructed here, inside the
        # consuming thread, matching how IndexingWorker's real
        # indexer_factory pattern works (see memoryos/background/worker.py).
        database = _database(tmp_path)
        indexer = DatabaseIndexer(
            FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(0.05), database
        )
        for item in indexer.iter_index_files(
            files, max_workers=2, embedding_batch_size=2, resume_event=resume_event
        ):
            results.append(item)
        database.close()  # same thread that created the connection

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.08)  # let the first couple of in-flight files finish
    resume_event.clear()  # pause: no new submissions
    time.sleep(0.15)  # would process several more files if not paused
    count_at_pause = len(results)
    time.sleep(0.15)
    # Only the up-to-max_workers files already in flight when paused may
    # still land; no further progress should happen beyond that.
    assert len(results) <= count_at_pause + 2, "new work was submitted while paused"

    resume_event.set()  # resume
    thread.join(timeout=10)
    assert not thread.is_alive(), "worker did not finish after resume"
    assert len(results) == 10


def test_cancel_stops_early_without_processing_everything(tmp_path):
    files = _make_image_files(tmp_path, 20)
    resume_event = threading.Event()
    resume_event.set()
    cancel_event = threading.Event()
    results = []

    def consume():
        database = _database(tmp_path)
        indexer = DatabaseIndexer(
            FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(0.03), database
        )
        for item in indexer.iter_index_files(
            files, max_workers=3, resume_event=resume_event, cancel_event=cancel_event
        ):
            results.append(item)
        database.close()  # same thread that created the connection

    thread = threading.Thread(target=consume)
    thread.start()
    time.sleep(0.1)
    cancel_event.set()
    thread.join(timeout=10)

    assert not thread.is_alive(), "worker did not stop after cancel"
    assert 0 < len(results) < 20


def test_default_call_with_no_events_still_works(tmp_path):
    """index_files()'s one-shot wrapper (and any other caller that doesn't
    care about pause/cancel) must keep working with resume_event/cancel_event
    left at their None defaults."""
    files = _make_image_files(tmp_path, 5)
    database = _database(tmp_path)
    try:
        indexer = DatabaseIndexer(FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(0.0), database)
        stats = indexer.index_files(files)
        assert stats.indexed == 5
        assert stats.errors == []
    finally:
        database.close()


def test_eml_file_is_indexed_and_searchable_end_to_end(tmp_path):
    """Email Search Integration Phase 1: exercises the full real pipeline
    (ScannedFile -> indexing.py's EMAIL dispatch branch -> extract_email ->
    embedding -> Database storage) rather than just the extractor in
    isolation (see tests/test_extractors.py) -- this is what actually proves
    the new dispatch wiring in memoryos/indexing.py works end to end."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Coffee Export Contract"
    msg["From"] = "supplier@example.com"
    msg["To"] = "buyer@example.com"
    msg.set_content("Attached is the signed contract for the Q3 green coffee export.")
    eml_path = tmp_path / "contract.eml"
    eml_path.write_bytes(bytes(msg))

    scanned = ScannedFile(
        path=eml_path,
        filename=eml_path.name,
        extension=".eml",
        file_type="email",
        mtime=eml_path.stat().st_mtime,
        size_bytes=eml_path.stat().st_size,
    )

    database = _database(tmp_path)
    try:
        indexer = DatabaseIndexer(FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(0.0), database)
        results = list(indexer.iter_index_files([scanned]))

        assert len(results) == 1
        assert results[0].outcome == "indexed"

        record = database.get_by_path(str(eml_path))
        assert record is not None
        assert "Coffee Export Contract" in record.semantic_text
        assert record.metadata["structural"]["email_subject"] == "Coffee Export Contract"
        assert "supplier@example.com" in record.metadata["structural"]["email_sender"]
        assert "Coffee Export Contract" in record.metadata["text_snippet"]
    finally:
        database.close()


def test_unchanged_files_skip_via_bulk_mtime_check_not_reprocessed(tmp_path):
    """Performance-pass regression: the unchanged-file pre-check now does one
    bulk Database.all_mtimes() fetch instead of one get_by_path() per file --
    confirms it still correctly identifies unchanged files (same mtime) as
    "unchanged" and changed files (different mtime) as needing reprocessing."""
    files = _make_image_files(tmp_path, 6)
    database = _database(tmp_path)
    try:
        indexer = DatabaseIndexer(
            FakeEmbeddingProvider(), None, SlowFakeVisionPipeline(0.0), database
        )
        first_pass = list(indexer.iter_index_files(files))
        assert all(r.outcome == "indexed" for r in first_pass)

        # Bump one file's mtime to simulate a real edit; the rest are untouched.
        new_mtime = files[0].mtime + 100
        os.utime(files[0].path, (new_mtime, new_mtime))
        files[0] = ScannedFile(
            path=files[0].path,
            filename=files[0].filename,
            extension=files[0].extension,
            file_type=files[0].file_type,
            mtime=new_mtime,
            size_bytes=files[0].size_bytes,
        )

        second_pass = list(indexer.iter_index_files(files))
        outcomes = {str(r.scanned_file.path): r.outcome for r in second_pass}
        assert outcomes[str(files[0].path)] == "indexed"
        for scanned in files[1:]:
            assert outcomes[str(scanned.path)] == "unchanged"
    finally:
        database.close()
