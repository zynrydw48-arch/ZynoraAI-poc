"""SQLite-backed storage for indexed files and local-only performance logs.

This is the V1 implementation of the "Index"/"Database" components. The
embedding storage here is deliberately narrow-interfaced (upsert_file /
get_by_path / all_files / embedding_matrix / delete_missing) so it can be
swapped later (FAISS, LanceDB, Qdrant, ...) without touching the ranking or
search engine, which never see SQLite directly.

perf_log is local-only, development-facing diagnostics: counts and timings,
never file paths, queries, or content. Nothing here is ever transmitted
anywhere -- see the project's Privacy Rule.
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    file_type TEXT NOT NULL,
    semantic_text TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at REAL NOT NULL,
    embedding BLOB NOT NULL,
    embedding_dtype TEXT NOT NULL,
    embedding_shape TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS perf_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    duration_seconds REAL NOT NULL,
    files_indexed INTEGER,
    cpu_percent REAL,
    ram_mb REAL,
    result_count INTEGER
);
"""

# Sprint 3 addition. Database is the single persistence layer for all local
# structured data (this table now, Settings/Favorites/Collections/Tags/Recent
# Files in later sprints) -- deliberately not a separate store/connection per
# feature, so the codebase never grows multiple ad-hoc "database managers."
_SEARCH_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    timestamp REAL NOT NULL,
    result_count INTEGER NOT NULL
);
"""

# Sprint 5 addition. Generic key-value store for this sprint's theme setting
# and any future one -- one table, not one per setting.
_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# Sprint 2 addition. A plain ALTER TABLE (not a migrations framework -- one
# additive column doesn't warrant one) guarded by a PRAGMA check so it's a
# no-op against a database that already has the column, including Sprint 1's
# pre-existing .memoryos/memoryos.sqlite3.
_PERF_LOG_PAUSED_SECONDS_COLUMN = "paused_seconds"

_FILE_COLUMNS = (
    "id, path, filename, extension, file_type, semantic_text, metadata_json, mtime, indexed_at"
)


@dataclass
class FileRecord:
    id: str
    path: str
    filename: str
    extension: str
    file_type: str
    semantic_text: str
    metadata: dict = field(default_factory=dict)
    mtime: float = 0.0
    indexed_at: float = 0.0


@dataclass
class SearchHistoryEntry:
    query: str
    timestamp: float
    result_count: int


def _row_to_record(row: tuple) -> FileRecord:
    id_, path, filename, extension, file_type, semantic_text, metadata_json, mtime, indexed_at = row
    return FileRecord(
        id=id_,
        path=path,
        filename=filename,
        extension=extension,
        file_type=file_type,
        semantic_text=semantic_text,
        metadata=json.loads(metadata_json),
        mtime=mtime,
        indexed_at=indexed_at,
    )


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # NORMAL is WAL mode's own recommended pairing: still durable against
        # an application crash, just skips the fsync-per-commit FULL does --
        # the only added risk is losing the last few not-yet-checkpointed
        # writes on an OS crash/power loss, which for a locally-rebuildable
        # search index (source files are the real data) is a fine trade for
        # indexing throughput.
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate_perf_log_paused_seconds()
        self._ensure_search_history_table()
        self._ensure_settings_table()

        # Sprint 10 (performance pass): embedding_matrix() is called on every
        # search, but the underlying rows only change on a write -- caching
        # the parsed records + assembled matrix here turns repeated searches
        # between indexing runs into an O(1) cache hit instead of re-querying
        # and re-json-decoding every row each time. Invalidated by any write
        # method below and rebuilt lazily on the next embedding_matrix() call.
        self._cache_dirty = True
        self._cached_records: list[FileRecord] = []
        self._cached_embeddings: np.ndarray | None = None

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True

    def _migrate_perf_log_paused_seconds(self) -> None:
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(perf_log)")}
        if _PERF_LOG_PAUSED_SECONDS_COLUMN not in columns:
            self._conn.execute(
                f"ALTER TABLE perf_log ADD COLUMN {_PERF_LOG_PAUSED_SECONDS_COLUMN} REAL"
            )
            self._conn.commit()

    def _ensure_search_history_table(self) -> None:
        self._conn.executescript(_SEARCH_HISTORY_SCHEMA)
        self._conn.commit()

    def _ensure_settings_table(self) -> None:
        self._conn.executescript(_SETTINGS_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def upsert_file(self, record: FileRecord, embedding: np.ndarray) -> None:
        self.upsert_files([(record, embedding)])

    def upsert_files(self, items: list[tuple[FileRecord, np.ndarray]]) -> None:
        """Batched upsert -- one transaction/commit for the whole list instead
        of one fsync-ing commit per record, used by DatabaseIndexer's
        per-batch flush so indexing throughput doesn't pay a disk sync per
        file. upsert_file() above is just this called with a single item."""
        if not items:
            return

        params = []
        for record, embedding in items:
            embedding = np.asarray(embedding)
            params.append(
                (
                    record.id,
                    record.path,
                    record.filename,
                    record.extension,
                    record.file_type,
                    record.semantic_text,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.mtime,
                    record.indexed_at,
                    embedding.tobytes(),
                    str(embedding.dtype),
                    json.dumps(embedding.shape),
                )
            )

        self._conn.executemany(
            f"""
            INSERT INTO files ({_FILE_COLUMNS}, embedding, embedding_dtype, embedding_shape)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                id=excluded.id, filename=excluded.filename, extension=excluded.extension,
                file_type=excluded.file_type, semantic_text=excluded.semantic_text,
                metadata_json=excluded.metadata_json, mtime=excluded.mtime,
                indexed_at=excluded.indexed_at, embedding=excluded.embedding,
                embedding_dtype=excluded.embedding_dtype, embedding_shape=excluded.embedding_shape
            """,
            params,
        )
        self._conn.commit()
        self._invalidate_cache()

    def get_by_path(self, path: str) -> FileRecord | None:
        row = self._conn.execute(
            f"SELECT {_FILE_COLUMNS} FROM files WHERE path = ?", (path,)
        ).fetchone()
        return _row_to_record(row) if row is not None else None

    def all_files(self) -> list[FileRecord]:
        rows = self._conn.execute(
            f"SELECT {_FILE_COLUMNS} FROM files ORDER BY rowid"
        ).fetchall()
        return [_row_to_record(r) for r in rows]

    def all_mtimes(self) -> dict[str, tuple[str, float]]:
        """Lightweight bulk fetch of path -> (id, mtime) only -- no metadata
        JSON decode, no embedding blob -- for the "is this file unchanged?"
        pre-check that used to run as one get_by_path() round-trip per file.
        One query instead of N lets an incremental reindex skip straight to a
        dict lookup for the (usually large) majority of already-indexed,
        unchanged files."""
        rows = self._conn.execute("SELECT id, path, mtime FROM files").fetchall()
        return {path: (id_, mtime) for id_, path, mtime in rows}

    def embedding_matrix(self) -> tuple[list[FileRecord], np.ndarray | None]:
        """Records and their embeddings, aligned by position (row i <-> records[i]).
        Served from the in-memory cache when nothing has been written since
        the last call; rebuilt from SQLite (and re-cached) otherwise."""
        if not self._cache_dirty:
            return self._cached_records, self._cached_embeddings

        rows = self._conn.execute(
            f"SELECT {_FILE_COLUMNS}, embedding, embedding_dtype, embedding_shape "
            f"FROM files ORDER BY rowid"
        ).fetchall()
        if not rows:
            self._cached_records, self._cached_embeddings = [], None
            self._cache_dirty = False
            return self._cached_records, self._cached_embeddings

        records = []
        vectors = []
        for row in rows:
            record_fields, embedding_blob, dtype_str, shape_json = row[:9], row[9], row[10], row[11]
            records.append(_row_to_record(record_fields))
            shape = tuple(json.loads(shape_json))
            vectors.append(np.frombuffer(embedding_blob, dtype=np.dtype(dtype_str)).reshape(shape))

        self._cached_records = records
        self._cached_embeddings = np.vstack(vectors)
        self._cache_dirty = False
        return self._cached_records, self._cached_embeddings

    def delete_missing(self, existing_paths: set[str]) -> int:
        rows = self._conn.execute("SELECT path FROM files").fetchall()
        to_delete = [row[0] for row in rows if row[0] not in existing_paths]
        if to_delete:
            self._conn.executemany(
                "DELETE FROM files WHERE path = ?", [(p,) for p in to_delete]
            )
            self._conn.commit()
            self._invalidate_cache()
        return len(to_delete)

    def update_file_path(self, old_path: str, new_path: str, new_filename: str) -> None:
        """Sprint 4 (rename): a pure metadata update -- renaming doesn't change
        file content, so embedding/semantic_text/metadata are left as-is. The
        UNIQUE constraint on path naturally rejects a collision with a
        different existing record (raises sqlite3.IntegrityError) rather than
        silently overwriting it."""
        self._conn.execute(
            "UPDATE files SET path = ?, filename = ? WHERE path = ?",
            (new_path, new_filename, old_path),
        )
        self._conn.commit()
        self._invalidate_cache()

    def delete_file_by_path(self, path: str) -> None:
        """Sprint 4 (delete): removes the record immediately so search
        reflects the deletion right away, rather than waiting for the next
        indexing run's delete_missing() pass."""
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.commit()
        self._invalidate_cache()

    def record_indexing_run(
        self,
        duration_seconds: float,
        files_indexed: int,
        cpu_percent: float,
        ram_mb: float,
        paused_seconds: float = 0.0,
    ) -> None:
        self._conn.execute(
            "INSERT INTO perf_log (event_type, timestamp, duration_seconds, files_indexed, "
            "cpu_percent, ram_mb, result_count, paused_seconds) "
            "VALUES ('indexing', ?, ?, ?, ?, ?, NULL, ?)",
            (time.time(), duration_seconds, files_indexed, cpu_percent, ram_mb, paused_seconds),
        )
        self._conn.commit()

    def record_search(self, duration_seconds: float, result_count: int) -> None:
        self._conn.execute(
            "INSERT INTO perf_log (event_type, timestamp, duration_seconds, files_indexed, "
            "cpu_percent, ram_mb, result_count) VALUES ('search', ?, ?, NULL, NULL, NULL, ?)",
            (time.time(), duration_seconds, result_count),
        )
        self._conn.commit()

    def record_search_history(self, query: str, result_count: int) -> None:
        """User-facing search history (Sprint 3) -- distinct from record_search()
        above, which is perf_log's search-latency diagnostics. Named
        differently to avoid colliding with that existing method."""
        self._conn.execute(
            "INSERT INTO search_history (query, timestamp, result_count) VALUES (?, ?, ?)",
            (query, time.time(), result_count),
        )
        self._conn.commit()

    def get_recent_searches(self, limit: int = 20) -> list[SearchHistoryEntry]:
        rows = self._conn.execute(
            "SELECT query, timestamp, result_count FROM search_history "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            SearchHistoryEntry(query=query, timestamp=timestamp, result_count=result_count)
            for query, timestamp, result_count in rows
        ]

    def clear_search_history(self) -> None:
        self._conn.execute("DELETE FROM search_history")
        self._conn.commit()

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row is not None else default

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
