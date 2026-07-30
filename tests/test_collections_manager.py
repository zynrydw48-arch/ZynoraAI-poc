"""AI Project Collections (Week 2): CollectionManager -- the thin CRUD
delegation to Database, plus run_auto_discovery's dedup-against-existing-
auto-collections behavior (memoryos/collections/clustering.py's algorithm
itself is tested in isolation in tests/test_collections_clustering.py)."""

import numpy as np
import pytest

from memoryos.collections.manager import CollectionManager
from memoryos.database.db import Database, FileRecord


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


@pytest.fixture
def manager(db):
    return CollectionManager(db)


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


def test_create_collection_delegates_to_database(manager):
    collection = manager.create_collection("Project Delta", file_paths=["a.pdf"])
    assert collection.name == "Project Delta"
    assert collection.auto_generated is False
    assert manager.get_collection(collection.id).file_paths == ["a.pdf"]


def test_rename_and_update_description_delegate(manager):
    collection = manager.create_collection("Old")
    manager.rename_collection(collection.id, "New")
    manager.update_description(collection.id, "a description")

    fetched = manager.get_collection(collection.id)
    assert fetched.name == "New"
    assert fetched.description == "a description"


def test_add_and_remove_files_delegate(manager):
    collection = manager.create_collection("X", file_paths=["a.pdf"])
    manager.add_files(collection.id, ["b.pdf"])
    assert set(manager.get_collection(collection.id).file_paths) == {"a.pdf", "b.pdf"}

    manager.remove_files(collection.id, ["a.pdf"])
    assert manager.get_collection(collection.id).file_paths == ["b.pdf"]


def test_delete_collection_delegates(manager):
    collection = manager.create_collection("X")
    manager.delete_collection(collection.id)
    assert manager.get_collection(collection.id) is None


def test_list_collections_and_collections_for_file(manager):
    c1 = manager.create_collection("First", file_paths=["shared.pdf"])
    manager.create_collection("Second", file_paths=["other.pdf"])

    assert len(manager.list_collections()) == 2
    assert [c.id for c in manager.collections_for_file("shared.pdf")] == [c1.id]


def test_run_auto_discovery_creates_collection_from_a_real_cluster(db, manager):
    budget = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
    pitch = np.array([0.88, 0.12, 0.0, 0.0], dtype=np.float32)
    unrelated = np.array([0.0, 0.0, 0.9, 0.1], dtype=np.float32)
    embeddings = _normalize(np.vstack([budget, pitch, unrelated]))

    _upsert(db, "budget.pdf", "Project Zephyr budget", embeddings[0])
    _upsert(db, "pitch.pdf", "Project Zephyr pitch deck", embeddings[1])
    _upsert(db, "vacation.pdf", "photos from a trip", embeddings[2])

    created = manager.run_auto_discovery(eps=0.2, min_samples=2)

    assert len(created) == 1
    assert created[0].auto_generated is True
    assert set(created[0].file_paths) == {"budget.pdf", "pitch.pdf"}
    assert "Zephyr" in created[0].name


def test_run_auto_discovery_returns_empty_when_nothing_clusters(db, manager):
    embeddings = _normalize(
        np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
    )
    _upsert(db, "a.pdf", "alpha", embeddings[0])
    _upsert(db, "b.pdf", "beta", embeddings[1])

    assert manager.run_auto_discovery(eps=0.2, min_samples=2) == []


def test_run_auto_discovery_skips_near_duplicate_of_existing_auto_collection(db, manager):
    budget = np.array([0.9, 0.1], dtype=np.float32)
    pitch = np.array([0.88, 0.12], dtype=np.float32)
    embeddings = _normalize(np.vstack([budget, pitch]))
    _upsert(db, "budget.pdf", "Project Zephyr budget", embeddings[0])
    _upsert(db, "pitch.pdf", "Project Zephyr pitch", embeddings[1])

    first_run = manager.run_auto_discovery(eps=0.2, min_samples=2)
    assert len(first_run) == 1

    second_run = manager.run_auto_discovery(eps=0.2, min_samples=2)

    assert second_run == []
    assert len(manager.list_collections()) == 1


def test_run_auto_discovery_ignores_manual_collections_when_deduping(db, manager):
    # A manual collection with the exact same files as what discovery would
    # propose must NOT suppress the auto-generated one -- only prior
    # auto-generated collections count toward the dedup check.
    budget = np.array([0.9, 0.1], dtype=np.float32)
    pitch = np.array([0.88, 0.12], dtype=np.float32)
    embeddings = _normalize(np.vstack([budget, pitch]))
    _upsert(db, "budget.pdf", "Project Zephyr budget", embeddings[0])
    _upsert(db, "pitch.pdf", "Project Zephyr pitch", embeddings[1])

    manager.create_collection("My manual collection", file_paths=["budget.pdf", "pitch.pdf"])

    created = manager.run_auto_discovery(eps=0.2, min_samples=2)

    assert len(created) == 1
    assert created[0].auto_generated is True
