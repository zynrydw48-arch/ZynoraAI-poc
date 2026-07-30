"""AI Project Collections (Week 2, Phase 2): MainWindow's wiring between
the UI (CollectionsView, ResultsView's filter/badges, ResultCard's Add to
Collection action) and CollectionManager/CollectionDiscoveryWorker. The
underlying widgets and the clustering algorithm each have their own
dedicated tests (test_collection_card.py, test_collections_view.py,
test_collections_clustering.py, test_collection_discovery_worker.py) --
these focus on whether clicking a thing in MainWindow calls the right
manager method and refreshes the right places.
"""

import sys
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from memoryos.database.db import Database, FileRecord
from memoryos.ui.add_to_collection_dialog import AddToCollectionDialog
from memoryos.ui.main_window import MainWindow

_app = QApplication.instance() or QApplication(sys.argv)

EMBED_DIM = 8
WAIT_TIMEOUT_S = 5.0


class FakeEmbeddingProvider:
    @property
    def dimension(self) -> int:
        return EMBED_DIM

    @property
    def model_name(self) -> str:
        return "fake"

    def encode(self, texts):
        vectors = np.ones((len(texts), EMBED_DIM), dtype=np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors


@pytest.fixture
def window(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    database = Database(db_path)

    for name in ("a.txt", "b.txt"):
        file_path = tmp_path / name
        file_path.write_text("hello", encoding="utf-8")
        embedding = np.ones(EMBED_DIM, dtype=np.float32)
        embedding /= np.linalg.norm(embedding)
        database.upsert_file(
            FileRecord(
                id=f"id-{name}",
                path=str(file_path),
                filename=name,
                extension=".txt",
                file_type="text",
                semantic_text="a note",
                metadata={},
                mtime=1.0,
                indexed_at=1.0,
            ),
            embedding,
        )

    win = MainWindow(FakeEmbeddingProvider(), None, None, database, db_path)
    yield win
    database.close()


def test_nav_button_switches_to_collections_page(window):
    assert window._page_stack.currentWidget() is window._page_stack.widget(0)

    window._collections_nav_button.click()

    assert window._page_stack.currentWidget() is window._page_stack.widget(1)


def test_startup_populates_collections_ui_with_none_yet(window):
    assert window._collections_view._cards == []
    assert window._results_view._filter_bar._collection_combo.count() == 1  # "All Collections" only


def test_create_collection_via_dialog(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Project Delta", True))

    window._on_create_collection()

    collections = window._collection_manager.list_collections()
    assert len(collections) == 1
    assert collections[0].name == "Project Delta"
    assert len(window._collections_view._cards) == 1
    assert window._results_view._filter_bar._collection_combo.count() == 2


def test_create_collection_cancelled_does_nothing(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))

    window._on_create_collection()

    assert window._collection_manager.list_collections() == []


def test_rename_collection_via_dialog(window, monkeypatch):
    collection = window._collection_manager.create_collection("Old Name")
    window._refresh_collections_ui()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("New Name", True))

    window._on_rename_collection(collection.id)

    assert window._collection_manager.get_collection(collection.id).name == "New Name"
    assert window._collections_view._cards[0].name_label.text() == "New Name"


def test_delete_collection_via_confirmation(window, monkeypatch):
    collection = window._collection_manager.create_collection("X")
    window._refresh_collections_ui()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )

    window._on_delete_collection(collection.id)

    assert window._collection_manager.get_collection(collection.id) is None
    assert window._collections_view._cards == []


def test_delete_collection_declined_keeps_it(window, monkeypatch):
    collection = window._collection_manager.create_collection("X")
    window._refresh_collections_ui()
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No
    )

    window._on_delete_collection(collection.id)

    assert window._collection_manager.get_collection(collection.id) is not None


def test_remove_file_from_collection(window):
    collection = window._collection_manager.create_collection("X", file_paths=["a.txt", "b.txt"])
    window._refresh_collections_ui()

    window._on_remove_file_from_collection(collection.id, "a.txt")

    assert window._collection_manager.get_collection(collection.id).file_paths == ["b.txt"]


def test_add_to_collection_creates_new_collection(window, monkeypatch):
    monkeypatch.setattr(AddToCollectionDialog, "exec", lambda self: AddToCollectionDialog.DialogCode.Accepted)
    monkeypatch.setattr(AddToCollectionDialog, "existing_collection_id", lambda self: None)
    monkeypatch.setattr(AddToCollectionDialog, "new_collection_name", lambda self: "Brand New")

    window._on_add_to_collection_requested("a.txt")

    collections = window._collection_manager.list_collections()
    assert len(collections) == 1
    assert collections[0].name == "Brand New"
    assert collections[0].file_paths == ["a.txt"]


def test_add_to_collection_adds_to_existing(window, monkeypatch):
    collection = window._collection_manager.create_collection("Existing")
    monkeypatch.setattr(AddToCollectionDialog, "exec", lambda self: AddToCollectionDialog.DialogCode.Accepted)
    monkeypatch.setattr(AddToCollectionDialog, "existing_collection_id", lambda self: collection.id)
    monkeypatch.setattr(AddToCollectionDialog, "new_collection_name", lambda self: None)

    window._on_add_to_collection_requested("a.txt")

    assert window._collection_manager.get_collection(collection.id).file_paths == ["a.txt"]


def test_add_to_collection_cancelled_does_nothing(window, monkeypatch):
    monkeypatch.setattr(AddToCollectionDialog, "exec", lambda self: AddToCollectionDialog.DialogCode.Rejected)

    window._on_add_to_collection_requested("a.txt")

    assert window._collection_manager.list_collections() == []


def test_discover_projects_disables_button_and_creates_a_collection(window, tmp_path):
    # a.txt/b.txt share the exact same fixed embedding (FakeEmbeddingProvider),
    # so they're guaranteed to cluster at any eps > 0.
    window._on_discover_projects()

    assert not window._collections_view._discover_button.isEnabled()

    deadline = time.time() + WAIT_TIMEOUT_S
    while window._discovery_worker is not None and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)

    assert window._discovery_worker is None
    assert window._collections_view._discover_button.isEnabled()
    collections = window._collection_manager.list_collections()
    assert len(collections) == 1
    assert set(collections[0].file_paths) == {
        str(tmp_path / "a.txt"),
        str(tmp_path / "b.txt"),
    }


def test_discover_projects_blocked_while_already_running(window):
    window._on_discover_projects()
    first_worker = window._discovery_worker

    window._on_discover_projects()  # should be a no-op, not a second worker

    assert window._discovery_worker is first_worker

    deadline = time.time() + WAIT_TIMEOUT_S
    while window._discovery_worker is not None and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)
    assert window._discovery_worker is None
