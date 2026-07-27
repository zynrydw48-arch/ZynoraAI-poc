"""Orchestrates scanner -> extractors -> vision -> embeddings -> index.

Every file type is normalized into the same metadata shape so the search
engine's reason-generation doesn't need type-specific branches:
    text_snippet, colors, tags, ocr_text, caption, structural
"""

import os
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, field
from pathlib import Path

import psutil
from PIL import Image

from memoryos.database.db import Database, FileRecord as DbFileRecord
from memoryos.embeddings.provider import EmbeddingProvider
from memoryos.extractors.docx_extractor import extract_docx
from memoryos.extractors.email_extractor import extract_email
from memoryos.extractors.pdf_extractor import extract_pdf
from memoryos.extractors.pptx_extractor import extract_pptx
from memoryos.extractors.xlsx_extractor import extract_xlsx
from memoryos.index.store import IndexRecord, IndexStore
from memoryos.ocr.engine import OcrEngine
from memoryos.scanner.discover import ScannedFile
from memoryos.utils.extensions import DOCX, EMAIL, IMAGE, PDF, PPTX, XLSX
from memoryos.utils.thread_priority import set_current_thread_background_priority
from memoryos.vision.pipeline import VisionPipeline, VisionResult

TEXT_SNIPPET_LENGTH = 300

# Sprint 8.5: bounded worker count for parallel extraction/OCR/vision -- one
# core held back for the UI thread and OS, capped so a very high-core-count
# machine doesn't oversubscribe disk I/O or (via the vision/embedding models)
# native BLAS threads. Starting point, tuned empirically against this
# project's real test corpus.
DEFAULT_MAX_WORKERS = min(max(1, (os.cpu_count() or 4) - 1), 8)

# Batch size for embedding-model calls -- accumulated from completed
# extraction results before a single encode() call, instead of one call per
# file. Starting point, tuned empirically against this project's real test
# corpus.
EMBEDDING_BATCH_SIZE = 16


def _apply_worker_thread_tuning() -> None:
    """ThreadPoolExecutor initializer, run once per pool worker thread.
    Two things: (1) the same OS-level background priority the coordinating
    IndexingWorker QThread already gets, so every indexing-related thread
    stays deprioritized versus the user's foreground work; (2) PyTorch's own
    per-call internal multithreading (used by the embedding model and the
    vision pipeline's tagger/captioner) would otherwise oversubscribe CPU
    cores when multiple worker threads call it concurrently -- confining
    each call to a single thread lets the *outer* thread pool provide the
    real parallelism instead. The torch step is a no-op if torch isn't
    actually the active backend."""
    set_current_thread_background_priority()
    try:
        import torch

        torch.set_num_threads(1)
    except ImportError:
        pass


@dataclass
class IndexStats:
    indexed: int = 0
    unchanged_skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    pruned: int = 0
    elapsed_seconds: float = 0.0


def _empty_metadata() -> dict:
    return {
        "text_snippet": "",
        "colors": [],
        "tags": [],
        "ocr_text": "",
        "caption": "",
        "structural": {},
    }


def _merge_embedded_image_results(metadata: dict, vision_results: list[VisionResult]) -> None:
    captions = []
    for i, vr in enumerate(vision_results, start=1):
        for color in vr.colors:
            if color not in metadata["colors"]:
                metadata["colors"].append(color)
        for tag in vr.tags:
            if tag not in metadata["tags"]:
                metadata["tags"].append(tag)
        if vr.ocr_text:
            metadata["ocr_text"] = (metadata["ocr_text"] + " " + vr.ocr_text).strip()
        if vr.caption:
            captions.append(f"image {i}: {vr.caption}")
    if captions:
        metadata["caption"] = "; ".join(captions)


def build_semantic_text_and_metadata(
    scanned: ScannedFile, ocr_engine: OcrEngine, vision_pipeline: VisionPipeline
) -> tuple[str, dict]:
    metadata = _empty_metadata()

    if scanned.file_type == IMAGE:
        image = Image.open(scanned.path)
        vision_result = vision_pipeline.analyze(image)
        metadata["colors"] = vision_result.colors
        metadata["tags"] = vision_result.tags
        metadata["ocr_text"] = vision_result.ocr_text
        metadata["caption"] = vision_result.caption
        return vision_result.semantic_text, metadata

    if scanned.file_type == PDF:
        result = extract_pdf(scanned.path, ocr_engine)
        metadata["structural"] = result.structural_metadata
    elif scanned.file_type == PPTX:
        result = extract_pptx(scanned.path)
        metadata["structural"] = result.structural_metadata
    elif scanned.file_type == DOCX:
        result = extract_docx(scanned.path)
        metadata["structural"] = result.structural_metadata
    elif scanned.file_type == XLSX:
        result = extract_xlsx(scanned.path)
        metadata["structural"] = result.structural_metadata
    elif scanned.file_type == EMAIL:
        result = extract_email(scanned.path)
        metadata["structural"] = result.structural_metadata
    else:
        raise ValueError(f"Unhandled file type: {scanned.file_type}")

    metadata["text_snippet"] = result.text[:TEXT_SNIPPET_LENGTH]

    if result.embedded_images:
        vision_results = [
            vr
            for vr in (vision_pipeline.analyze_bytes(b) for b in result.embedded_images)
            if vr is not None
        ]
        _merge_embedded_image_results(metadata, vision_results)

    semantic_parts = [result.text]
    if metadata["caption"]:
        semantic_parts.append(f"Embedded images: {metadata['caption']}")
    if metadata["tags"]:
        semantic_parts.append(f"Objects in embedded images: {', '.join(metadata['tags'])}")
    if metadata["colors"]:
        semantic_parts.append(f"Colors in embedded images: {', '.join(metadata['colors'])}")
    if metadata["ocr_text"]:
        semantic_parts.append(f"Text in embedded images: {metadata['ocr_text']}")

    return " ".join(p for p in semantic_parts if p), metadata


class Indexer:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        ocr_engine: OcrEngine,
        vision_pipeline: VisionPipeline,
        index_store: IndexStore,
    ):
        self._embedding_provider = embedding_provider
        self._ocr_engine = ocr_engine
        self._vision_pipeline = vision_pipeline
        self._index_store = index_store

    def index_files(self, scanned_files: list[ScannedFile]) -> IndexStats:
        stats = IndexStats()
        start = time.time()

        existing_paths = {str(f.path) for f in scanned_files}
        stats.pruned = self._index_store.prune_missing(existing_paths)

        for scanned in scanned_files:
            path_str = str(scanned.path)
            existing = self._index_store.get_by_path(path_str)
            if existing is not None and existing.mtime == scanned.mtime:
                stats.unchanged_skipped += 1
                continue

            try:
                semantic_text, metadata = build_semantic_text_and_metadata(
                    scanned, self._ocr_engine, self._vision_pipeline
                )
                embedding = self._embedding_provider.encode([semantic_text])[0]
                record = IndexRecord(
                    id=existing.id if existing else str(uuid.uuid4()),
                    path=path_str,
                    filename=scanned.filename,
                    extension=scanned.extension,
                    file_type=scanned.file_type,
                    semantic_text=semantic_text,
                    metadata=metadata,
                    mtime=scanned.mtime,
                    indexed_at=time.time(),
                )
                self._index_store.upsert(record, embedding)
                stats.indexed += 1
            except Exception as exc:
                stats.errors.append((path_str, repr(exc)))

        self._index_store.save()
        stats.elapsed_seconds = time.time() - start
        return stats


@dataclass
class FileIndexProgress:
    """One yield per file from DatabaseIndexer.iter_index_files -- lets a
    caller (e.g. memoryos/background/worker.py) interleave pause/cancel
    checks and progress reporting between files."""

    scanned_file: ScannedFile
    outcome: str  # "indexed" | "unchanged" | "error"
    error: str | None = None


@dataclass
class _ExtractedItem:
    """Sprint 8.5: result of one file's extraction/OCR/vision work, produced
    by a thread-pool worker. Carries existing_id forward from the coordinator
    thread's earlier Database lookup so workers never touch the Database
    themselves -- only the coordinator thread does, preserving the one
    connection/one writer-thread invariant from Sprint 2's WAL-mode design."""

    scanned_file: ScannedFile
    existing_id: str | None
    semantic_text: str | None = None
    metadata: dict | None = None
    error: str | None = None


class DatabaseIndexer:
    """Same orchestration as Indexer, writing to the SQLite Database instead of
    the legacy IndexStore. Kept as a separate class -- not a shared base --
    while IndexStore/Indexer still exist as the verified fallback; the two
    collapse into one once that legacy path is retired in a later sprint."""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        ocr_engine: OcrEngine,
        vision_pipeline: VisionPipeline,
        database: Database,
    ):
        self._embedding_provider = embedding_provider
        self._ocr_engine = ocr_engine
        self._vision_pipeline = vision_pipeline
        self._database = database

    def prune_missing(self, scanned_files: list[ScannedFile]) -> int:
        existing_paths = {str(f.path) for f in scanned_files}
        return self._database.delete_missing(existing_paths)

    def record_indexing_run(self, **kwargs) -> None:
        """Passthrough to the owned Database -- lets a caller (e.g.
        memoryos/background/worker.py) depend only on DatabaseIndexer's
        interface, not reach into its private Database, which matters for
        tests that fake out the whole indexer."""
        self._database.record_indexing_run(**kwargs)

    def close(self) -> None:
        self._database.close()

    def iter_index_files(
        self,
        scanned_files: list[ScannedFile],
        max_workers: int = DEFAULT_MAX_WORKERS,
        embedding_batch_size: int = EMBEDDING_BATCH_SIZE,
        resume_event: threading.Event | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[FileIndexProgress]:
        """Sprint 8.5: the cheap "is this file unchanged?" check stays
        sequential (it's already fast -- one Database lookup per file) and
        yields immediately; files that need real work (extraction/OCR/vision)
        run concurrently in a bounded thread pool, with embedding calls
        batched across the completed results rather than one call per file.
        Still yields exactly one FileIndexProgress per file, same as before,
        so callers (memoryos/background/worker.py) don't need to change how
        they consume this. resume_event/cancel_event are plain
        threading.Event objects (not Qt types) so this stays Qt-decoupled;
        passing None (the default for callers that don't need pause/cancel,
        e.g. index_files() below) means "never pause, never cancel."

        Does not prune missing files or record perf_log -- callers that want
        the Sprint 1 one-shot behavior should use index_files() below instead.
        """
        # Sprint 10 (performance pass): one bulk fetch instead of one
        # get_by_path() round-trip (with a full metadata JSON decode) per
        # file -- for a mostly-unchanged incremental reindex, this turns N
        # SQLite queries into 1 plus N cheap dict lookups.
        existing_by_path = self._database.all_mtimes()

        to_process: list[tuple[ScannedFile, str | None]] = []
        for scanned in scanned_files:
            existing = existing_by_path.get(str(scanned.path))
            if existing is not None and existing[1] == scanned.mtime:
                yield FileIndexProgress(scanned_file=scanned, outcome="unchanged")
            else:
                to_process.append((scanned, existing[0] if existing else None))

        if not to_process:
            return

        yield from self._process_in_parallel(
            to_process, max_workers, embedding_batch_size, resume_event, cancel_event
        )

    def _extract_one(self, scanned: ScannedFile, existing_id: str | None) -> _ExtractedItem:
        """Runs on a pool worker thread -- extraction/OCR/vision only, no
        Database access (the coordinator thread is the sole writer)."""
        try:
            semantic_text, metadata = build_semantic_text_and_metadata(
                scanned, self._ocr_engine, self._vision_pipeline
            )
            return _ExtractedItem(
                scanned_file=scanned,
                existing_id=existing_id,
                semantic_text=semantic_text,
                metadata=metadata,
            )
        except Exception as exc:
            return _ExtractedItem(
                scanned_file=scanned, existing_id=existing_id, error=repr(exc)
            )

    def _flush_batch(self, batch: list[_ExtractedItem]) -> list[FileIndexProgress]:
        """Coordinator-thread-only: one embedding-model call for the whole
        batch, then a Database write per successfully-extracted item."""
        results = [
            FileIndexProgress(scanned_file=item.scanned_file, outcome="error", error=item.error)
            for item in batch
            if item.error is not None
        ]
        successes = [item for item in batch if item.error is None]
        if not successes:
            return results

        embeddings = self._embedding_provider.encode([item.semantic_text for item in successes])
        # One batched upsert (one transaction/commit) for the whole batch
        # instead of a per-file commit -- avoids a disk sync per file.
        to_upsert = []
        for item, embedding in zip(successes, embeddings):
            record = DbFileRecord(
                id=item.existing_id or str(uuid.uuid4()),
                path=str(item.scanned_file.path),
                filename=item.scanned_file.filename,
                extension=item.scanned_file.extension,
                file_type=item.scanned_file.file_type,
                semantic_text=item.semantic_text,
                metadata=item.metadata,
                mtime=item.scanned_file.mtime,
                indexed_at=time.time(),
            )
            to_upsert.append((record, embedding))
            results.append(FileIndexProgress(scanned_file=item.scanned_file, outcome="indexed"))
        self._database.upsert_files(to_upsert)
        return results

    def _process_in_parallel(
        self,
        to_process: list[tuple[ScannedFile, str | None]],
        max_workers: int,
        embedding_batch_size: int,
        resume_event: threading.Event | None,
        cancel_event: threading.Event | None,
    ) -> Iterator[FileIndexProgress]:
        pending_batch: list[_ExtractedItem] = []
        remaining = iter(to_process)

        with ThreadPoolExecutor(
            max_workers=max_workers, initializer=_apply_worker_thread_tuning
        ) as executor:
            in_flight: dict[Future, ScannedFile] = {}

            def submit_more() -> None:
                while len(in_flight) < max_workers:
                    if resume_event is not None:
                        resume_event.wait()  # blocks new submissions while paused
                    if cancel_event is not None and cancel_event.is_set():
                        return  # in-flight work still finishes below; just stop feeding more
                    try:
                        scanned, existing_id = next(remaining)
                    except StopIteration:
                        return
                    future = executor.submit(self._extract_one, scanned, existing_id)
                    in_flight[future] = scanned

            submit_more()
            while in_flight:
                done, _ = wait_futures(in_flight.keys(), return_when=FIRST_COMPLETED)
                for future in done:
                    del in_flight[future]
                    pending_batch.append(future.result())
                    if len(pending_batch) >= embedding_batch_size:
                        yield from self._flush_batch(pending_batch)
                        pending_batch = []
                submit_more()

        yield from self._flush_batch(pending_batch)

    def index_files(self, scanned_files: list[ScannedFile]) -> IndexStats:
        """One-shot, uninterruptible convenience wrapper around
        iter_index_files -- same signature/behavior as Sprint 1."""
        stats = IndexStats()
        start = time.time()

        stats.pruned = self.prune_missing(scanned_files)

        for progress in self.iter_index_files(scanned_files):
            if progress.outcome == "indexed":
                stats.indexed += 1
            elif progress.outcome == "unchanged":
                stats.unchanged_skipped += 1
            else:
                stats.errors.append((str(progress.scanned_file.path), progress.error))

        stats.elapsed_seconds = time.time() - start

        process = psutil.Process()
        self._database.record_indexing_run(
            duration_seconds=stats.elapsed_seconds,
            files_indexed=stats.indexed,
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_mb=process.memory_info().rss / (1024 * 1024),
        )
        return stats
