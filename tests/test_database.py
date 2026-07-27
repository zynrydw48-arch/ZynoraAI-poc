import sqlite3

import numpy as np
import pytest

from memoryos.database.db import Database, FileRecord


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def _record(path="a.jpg", filename="a.jpg") -> FileRecord:
    return FileRecord(
        id=f"id-{path}",
        path=path,
        filename=filename,
        extension=".jpg",
        file_type="image",
        semantic_text="a dog on a beach",
        metadata={"colors": ["white", "blue"], "tags": ["dog"]},
        mtime=1.0,
        indexed_at=1.0,
    )


def test_upsert_and_get_by_path(db):
    assert db.get_by_path("a.jpg") is None

    embedding = np.random.rand(384).astype(np.float32)
    db.upsert_file(_record(), embedding)

    fetched = db.get_by_path("a.jpg")
    assert fetched is not None
    assert fetched.filename == "a.jpg"
    assert fetched.metadata == {"colors": ["white", "blue"], "tags": ["dog"]}
    assert len(db) == 1


def test_upsert_same_path_updates_in_place(db):
    embedding = np.zeros(384, dtype=np.float32)
    db.upsert_file(_record(), embedding)

    updated = _record()
    updated.semantic_text = "UPDATED"
    db.upsert_file(updated, np.ones(384, dtype=np.float32))

    assert len(db) == 1
    assert db.get_by_path("a.jpg").semantic_text == "UPDATED"


def test_embedding_roundtrip_is_bit_identical(db):
    original = np.random.rand(384).astype(np.float32)
    db.upsert_file(_record(), original)

    records, matrix = db.embedding_matrix()
    assert len(records) == 1
    assert matrix.dtype == original.dtype
    assert matrix.shape == (1, 384)
    assert np.array_equal(matrix[0], original)


def test_embedding_matrix_alignment_with_multiple_records(db):
    embeddings = {}
    for i in range(5):
        emb = np.random.rand(384).astype(np.float32)
        embeddings[f"file{i}.jpg"] = emb
        db.upsert_file(_record(path=f"file{i}.jpg", filename=f"file{i}.jpg"), emb)

    records, matrix = db.embedding_matrix()
    assert len(records) == 5
    for i, record in enumerate(records):
        assert np.array_equal(matrix[i], embeddings[record.path])


def test_delete_missing(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.zeros(384, dtype=np.float32))

    removed = db.delete_missing({"a.jpg"})
    assert removed == 1
    assert len(db) == 1
    assert db.get_by_path("b.jpg") is None
    assert db.get_by_path("a.jpg") is not None


def test_update_file_path_renames_in_place_without_touching_embedding(db):
    embedding = np.random.rand(384).astype(np.float32)
    db.upsert_file(_record(path="old.jpg", filename="old.jpg"), embedding)

    db.update_file_path("old.jpg", "new.jpg", "new.jpg")

    assert db.get_by_path("old.jpg") is None
    renamed = db.get_by_path("new.jpg")
    assert renamed is not None
    assert renamed.filename == "new.jpg"
    _, matrix = db.embedding_matrix()
    assert np.array_equal(matrix[0], embedding)


def test_update_file_path_rejects_collision_with_different_existing_record(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.ones(384, dtype=np.float32))

    with pytest.raises(sqlite3.IntegrityError):
        db.update_file_path("a.jpg", "b.jpg", "b.jpg")

    # both original records untouched
    assert db.get_by_path("a.jpg") is not None
    assert db.get_by_path("b.jpg") is not None


def test_delete_file_by_path_removes_record_immediately(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.zeros(384, dtype=np.float32))

    db.delete_file_by_path("a.jpg")

    assert db.get_by_path("a.jpg") is None
    assert len(db) == 1
    records, matrix = db.embedding_matrix()
    assert [r.path for r in records] == ["b.jpg"]
    assert matrix.shape == (1, 384)


def test_perf_log_indexing_and_search_roundtrip(db):
    db.record_indexing_run(duration_seconds=12.5, files_indexed=131, cpu_percent=45.0, ram_mb=512.0)
    db.record_search(duration_seconds=0.02, result_count=10)

    rows = db._conn.execute(
        "SELECT event_type, duration_seconds, files_indexed, cpu_percent, ram_mb, result_count "
        "FROM perf_log ORDER BY id"
    ).fetchall()

    assert len(rows) == 2
    indexing_row, search_row = rows

    assert indexing_row[0] == "indexing"
    assert indexing_row[1] == pytest.approx(12.5)
    assert indexing_row[2] == 131
    assert indexing_row[3] == pytest.approx(45.0)
    assert indexing_row[4] == pytest.approx(512.0)
    assert indexing_row[5] is None

    assert search_row[0] == "search"
    assert search_row[1] == pytest.approx(0.02)
    assert search_row[2] is None
    assert search_row[5] == 10


def test_search_history_recent_ordering_and_limit(db):
    db.record_search_history("green coffee", 5)
    db.record_search_history("white dog on beach", 3)
    db.record_search_history("invoice", 0)

    recent = db.get_recent_searches(limit=2)
    assert [e.query for e in recent] == ["invoice", "white dog on beach"]
    assert recent[0].result_count == 0
    assert recent[1].result_count == 3

    all_entries = db.get_recent_searches(limit=20)
    assert [e.query for e in all_entries] == ["invoice", "white dog on beach", "green coffee"]


def test_clear_search_history_does_not_touch_files_or_perf_log(db):
    db.upsert_file(_record(), np.zeros(384, dtype=np.float32))
    db.record_indexing_run(duration_seconds=1.0, files_indexed=1, cpu_percent=10.0, ram_mb=100.0)
    db.record_search_history("green coffee", 5)
    db.record_search_history("world map", 1)

    db.clear_search_history()

    assert db.get_recent_searches() == []
    assert len(db) == 1  # files table untouched
    perf_log_count = db._conn.execute("SELECT COUNT(*) FROM perf_log").fetchone()[0]
    assert perf_log_count == 1  # perf_log untouched


def test_get_setting_returns_default_when_unset(db):
    assert db.get_setting("theme") is None
    assert db.get_setting("theme", "system") == "system"


def test_set_setting_and_get_setting_roundtrip(db):
    db.set_setting("theme", "dark")
    assert db.get_setting("theme") == "dark"


def test_set_setting_updates_in_place_not_a_duplicate_row(db):
    db.set_setting("theme", "dark")
    db.set_setting("theme", "light")

    assert db.get_setting("theme") == "light"
    count = db._conn.execute(
        "SELECT COUNT(*) FROM settings WHERE key = ?", ("theme",)
    ).fetchone()[0]
    assert count == 1


# Performance-pass regression tests: embedding_matrix() now caches its result
# in memory instead of re-querying + re-JSON-decoding every row on every call
# -- these confirm both halves of that change (cache actually gets reused,
# and every write path still correctly invalidates it) since a stale cache
# would be a silent search-correctness bug hiding behind a speed win.


def test_embedding_matrix_is_served_from_cache_when_nothing_changed(db):
    db.upsert_file(_record(), np.zeros(384, dtype=np.float32))

    records_first, matrix_first = db.embedding_matrix()
    assert db._cache_dirty is False

    records_second, matrix_second = db.embedding_matrix()
    # Same cached objects returned, not freshly rebuilt from SQLite.
    assert records_second is records_first
    assert matrix_second is matrix_first


def test_embedding_matrix_cache_invalidated_by_upsert(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.embedding_matrix()  # populate cache
    assert db._cache_dirty is False

    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.ones(384, dtype=np.float32))

    records, matrix = db.embedding_matrix()
    assert len(records) == 2
    assert matrix.shape == (2, 384)


def test_embedding_matrix_cache_invalidated_by_upsert_files_batch(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.embedding_matrix()  # populate cache

    db.upsert_files(
        [
            (_record(path="b.jpg", filename="b.jpg"), np.ones(384, dtype=np.float32)),
            (_record(path="c.jpg", filename="c.jpg"), np.full(384, 2.0, dtype=np.float32)),
        ]
    )

    records, matrix = db.embedding_matrix()
    assert {r.path for r in records} == {"a.jpg", "b.jpg", "c.jpg"}
    assert matrix.shape == (3, 384)


def test_embedding_matrix_cache_invalidated_by_delete_missing(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.zeros(384, dtype=np.float32))
    db.embedding_matrix()  # populate cache

    db.delete_missing({"a.jpg"})

    records, matrix = db.embedding_matrix()
    assert [r.path for r in records] == ["a.jpg"]
    assert matrix.shape == (1, 384)


def test_embedding_matrix_cache_invalidated_by_delete_file_by_path(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))
    db.upsert_file(_record(path="b.jpg", filename="b.jpg"), np.zeros(384, dtype=np.float32))
    db.embedding_matrix()  # populate cache

    db.delete_file_by_path("a.jpg")

    records, matrix = db.embedding_matrix()
    assert [r.path for r in records] == ["b.jpg"]
    assert matrix.shape == (1, 384)


def test_embedding_matrix_cache_invalidated_by_update_file_path(db):
    embedding = np.random.rand(384).astype(np.float32)
    db.upsert_file(_record(path="old.jpg", filename="old.jpg"), embedding)
    db.embedding_matrix()  # populate cache

    db.update_file_path("old.jpg", "new.jpg", "new.jpg")

    records, matrix = db.embedding_matrix()
    assert [r.path for r in records] == ["new.jpg"]
    assert np.array_equal(matrix[0], embedding)


def test_embedding_matrix_returns_empty_when_no_files_and_stays_cached(db):
    records, matrix = db.embedding_matrix()
    assert records == []
    assert matrix is None
    assert db._cache_dirty is False


def test_all_mtimes_returns_id_and_mtime_by_path(db):
    db.upsert_file(_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32))

    mtimes = db.all_mtimes()

    assert mtimes == {"a.jpg": ("id-a.jpg", 1.0)}


def test_upsert_files_batch_stores_all_records_in_one_call(db):
    items = [
        (_record(path="a.jpg", filename="a.jpg"), np.zeros(384, dtype=np.float32)),
        (_record(path="b.jpg", filename="b.jpg"), np.ones(384, dtype=np.float32)),
    ]

    db.upsert_files(items)

    assert len(db) == 2
    assert db.get_by_path("a.jpg") is not None
    assert db.get_by_path("b.jpg") is not None


def test_upsert_files_with_empty_list_is_a_no_op(db):
    db.upsert_files([])
    assert len(db) == 0
