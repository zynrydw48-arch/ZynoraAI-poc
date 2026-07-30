"""AI Project Collections (Week 2): Database's collections/collection_files
schema and CRUD, plus the cleanup wiring into the existing file-mutation
methods (delete_missing/delete_file_by_path/update_file_path) -- those don't
enforce a FOREIGN KEY, so this is what actually keeps collection membership
from silently going stale when a file is deleted or renamed.
"""

import numpy as np
import pytest

from memoryos.database.db import Database, FileRecord


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def _upsert(db, path: str) -> None:
    db.upsert_file(
        FileRecord(
            id=f"id-{path}",
            path=path,
            filename=path,
            extension=".txt",
            file_type="text",
            semantic_text="content",
            metadata={},
            mtime=1.0,
            indexed_at=1.0,
        ),
        np.zeros(8, dtype=np.float32),
    )


def test_create_collection_with_files_roundtrip(db):
    collection = db.create_collection(
        name="Project Delta", description="Q3 planning", file_paths=["a.pdf", "b.xlsx"]
    )

    assert collection.name == "Project Delta"
    assert collection.description == "Q3 planning"
    assert collection.auto_generated is False
    assert set(collection.file_paths) == {"a.pdf", "b.xlsx"}

    fetched = db.get_collection(collection.id)
    assert fetched is not None
    assert fetched.name == "Project Delta"
    assert set(fetched.file_paths) == {"a.pdf", "b.xlsx"}


def test_create_collection_without_files(db):
    collection = db.create_collection(name="Empty Collection")
    assert collection.file_paths == []
    assert db.get_collection(collection.id).file_paths == []


def test_create_auto_generated_collection(db):
    collection = db.create_collection(name="Trip to Rome", auto_generated=True)
    assert collection.auto_generated is True
    assert db.get_collection(collection.id).auto_generated is True


def test_get_collection_returns_none_for_unknown_id(db):
    assert db.get_collection("does-not-exist") is None


def test_list_collections_ordered_by_created_at(db):
    first = db.create_collection(name="First")
    second = db.create_collection(name="Second")

    listed = db.list_collections()

    assert [c.id for c in listed] == [first.id, second.id]


def test_rename_collection_updates_name(db):
    collection = db.create_collection(name="Old Name")

    db.rename_collection(collection.id, "New Name")

    assert db.get_collection(collection.id).name == "New Name"


def test_update_collection_description(db):
    collection = db.create_collection(name="X", description="old")

    db.update_collection_description(collection.id, "new description")

    assert db.get_collection(collection.id).description == "new description"


def test_delete_collection_removes_membership_rows(db):
    collection = db.create_collection(name="X", file_paths=["a.pdf"])

    db.delete_collection(collection.id)

    assert db.get_collection(collection.id) is None
    count = db._conn.execute(
        "SELECT COUNT(*) FROM collection_files WHERE collection_id = ?", (collection.id,)
    ).fetchone()[0]
    assert count == 0


def test_add_files_to_collection(db):
    collection = db.create_collection(name="X", file_paths=["a.pdf"])

    db.add_files_to_collection(collection.id, ["b.pdf", "c.pdf"])

    assert set(db.get_collection(collection.id).file_paths) == {"a.pdf", "b.pdf", "c.pdf"}


def test_add_files_to_collection_is_idempotent(db):
    collection = db.create_collection(name="X", file_paths=["a.pdf"])

    db.add_files_to_collection(collection.id, ["a.pdf"])  # already a member

    assert db.get_collection(collection.id).file_paths == ["a.pdf"]


def test_add_files_with_empty_list_is_a_no_op(db):
    collection = db.create_collection(name="X", file_paths=["a.pdf"])
    db.add_files_to_collection(collection.id, [])
    assert db.get_collection(collection.id).file_paths == ["a.pdf"]


def test_remove_files_from_collection(db):
    collection = db.create_collection(name="X", file_paths=["a.pdf", "b.pdf"])

    db.remove_files_from_collection(collection.id, ["a.pdf"])

    assert db.get_collection(collection.id).file_paths == ["b.pdf"]


def test_get_collections_for_file(db):
    c1 = db.create_collection(name="First", file_paths=["shared.pdf"])
    c2 = db.create_collection(name="Second", file_paths=["shared.pdf", "other.pdf"])
    db.create_collection(name="Unrelated", file_paths=["nothing_to_do_with_it.pdf"])

    found = db.get_collections_for_file("shared.pdf")

    assert {c.id for c in found} == {c1.id, c2.id}


def test_get_collections_for_file_with_no_membership_returns_empty(db):
    assert db.get_collections_for_file("nowhere.pdf") == []


def test_delete_file_by_path_removes_it_from_collections(db):
    _upsert(db, "a.txt")
    collection = db.create_collection(name="X", file_paths=["a.txt", "b.txt"])

    db.delete_file_by_path("a.txt")

    assert db.get_collection(collection.id).file_paths == ["b.txt"]


def test_delete_missing_removes_deleted_files_from_collections(db):
    _upsert(db, "a.txt")
    _upsert(db, "b.txt")
    collection = db.create_collection(name="X", file_paths=["a.txt", "b.txt"])

    db.delete_missing({"b.txt"})  # a.txt no longer exists on disk

    assert db.get_collection(collection.id).file_paths == ["b.txt"]


def test_update_file_path_carries_collection_membership_to_new_path(db):
    _upsert(db, "old.txt")
    collection = db.create_collection(name="X", file_paths=["old.txt"])

    db.update_file_path("old.txt", "new.txt", "new.txt")

    assert db.get_collection(collection.id).file_paths == ["new.txt"]
