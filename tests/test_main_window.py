"""Bug-fix regression tests: Rename/Delete refreshing results must NOT record
a new Search History entry, while a normal user-initiated search (including
re-running one from the history panel) still must.

Uses a fake, instant EmbeddingProvider so these tests don't need to load the
real ML models -- MainWindow never calls anything on ocr_engine/vision_pipeline
until indexing starts, which these tests never trigger, so those are passed
as None.
"""

import sys

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from memoryos import file_actions
from memoryos.database.db import Database, FileRecord
from memoryos.indexing import IndexStats
from memoryos.theme import Theme
from memoryos.ui.main_window import MainWindow

_app = QApplication.instance() or QApplication(sys.argv)

EMBED_DIM = 8


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

    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")

    embedding = np.ones(EMBED_DIM, dtype=np.float32)
    embedding /= np.linalg.norm(embedding)
    database.upsert_file(
        FileRecord(
            id="id-1",
            path=str(file_path),
            filename="note.txt",
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


@pytest.fixture
def window_with_mixed_files(tmp_path):
    """One Files-category file (.txt) and one Images-category file (.jpg) --
    both match any query via FakeEmbeddingProvider's fixed encoding, so this
    fixture is for filter-tab tests, not ranking/relevance ones."""
    db_path = tmp_path / "mixed.sqlite3"
    database = Database(db_path)

    embedding = np.ones(EMBED_DIM, dtype=np.float32)
    embedding /= np.linalg.norm(embedding)

    note_path = tmp_path / "note.txt"
    note_path.write_text("hello", encoding="utf-8")
    database.upsert_file(
        FileRecord(
            id="id-note",
            path=str(note_path),
            filename="note.txt",
            extension=".txt",
            file_type="text",
            semantic_text="a note",
            metadata={},
            mtime=1.0,
            indexed_at=1.0,
        ),
        embedding,
    )

    photo_path = tmp_path / "photo.jpg"
    photo_path.write_bytes(b"fake-jpg-bytes")
    database.upsert_file(
        FileRecord(
            id="id-photo",
            path=str(photo_path),
            filename="photo.jpg",
            extension=".jpg",
            file_type="image",
            semantic_text="a photo",
            metadata={},
            mtime=1.0,
            indexed_at=1.0,
        ),
        embedding,
    )

    win = MainWindow(FakeEmbeddingProvider(), None, None, database, db_path)
    yield win
    database.close()


@pytest.fixture
def empty_window(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    database = Database(db_path)
    win = MainWindow(FakeEmbeddingProvider(), None, None, database, db_path)
    yield win
    database.close()


def test_normal_search_records_history(window):
    window._search_line_edit.setText("a note")
    window._on_search()

    assert len(window._database.get_recent_searches()) == 1
    assert len(window._results_view._cards) == 1
    assert window._results_stack.currentWidget() is window._results_view


def test_populated_search_shows_filter_bar(window):
    window._search_line_edit.setText("a note")
    window._on_search()

    assert window._results_view._filter_bar.isVisibleTo(window._results_view)


def test_zero_result_search_hides_filter_bar(window):
    # The fake embedding provider always encodes to the same fixed vector,
    # so it can't produce a genuine zero-similarity query here -- calling
    # set_results([], ...) directly exercises the same hide-on-empty path
    # ResultsView.set_results() takes for a real zero-result search.
    window._search_line_edit.setText("a note")
    window._on_search()
    assert window._results_view._filter_bar.isVisibleTo(window._results_view)

    window._results_view.set_results([], window._effective_theme())

    assert not window._results_view._filter_bar.isVisibleTo(window._results_view)


def test_filter_tab_shows_only_matching_category(window_with_mixed_files):
    window = window_with_mixed_files
    window._search_line_edit.setText("anything")
    window._on_search()
    assert len(window._results_view._cards) == 2  # both match, FakeEmbeddingProvider

    window._results_view._filter_bar._buttons["Images"].click()

    assert [c.filename_label.text() for c in window._results_view._cards] == ["photo.jpg"]
    assert not window._results_view._filter_empty_state.isVisibleTo(window._results_view)
    assert window._results_view._scroll_area.isVisibleTo(window._results_view)


def test_filter_tab_with_no_matches_shows_empty_state_message(window_with_mixed_files):
    window = window_with_mixed_files
    window._search_line_edit.setText("white dog")
    window._on_search()

    window._results_view._filter_bar._buttons["Notes"].click()

    assert window._results_view._cards == []
    assert window._results_view._filter_empty_state.isVisibleTo(window._results_view)
    assert not window._results_view._scroll_area.isVisibleTo(window._results_view)
    assert (
        window._results_view._filter_empty_state._message_label.text()
        == "We couldn't find any notes matching 'white dog'"
    )


def test_switching_back_to_all_restores_every_card(window_with_mixed_files):
    window = window_with_mixed_files
    window._search_line_edit.setText("anything")
    window._on_search()

    window._results_view._filter_bar._buttons["Images"].click()
    assert len(window._results_view._cards) == 1

    window._results_view._filter_bar._buttons["All"].click()

    assert len(window._results_view._cards) == 2


def test_new_search_resets_an_active_filter_back_to_all(window_with_mixed_files):
    window = window_with_mixed_files
    window._search_line_edit.setText("anything")
    window._on_search()
    window._results_view._filter_bar._buttons["Images"].click()
    assert len(window._results_view._cards) == 1

    window._search_line_edit.setText("something else")
    window._on_search()

    assert window._results_view._active_filter == "All"
    assert len(window._results_view._cards) == 2


def test_history_entry_click_still_records_a_new_entry(window):
    window._search_line_edit.setText("a note")
    window._on_search()
    assert len(window._database.get_recent_searches()) == 1

    window._on_history_entry_selected("a note")
    assert len(window._database.get_recent_searches()) == 2


def test_rename_refresh_does_not_record_history(window, monkeypatch):
    window._search_line_edit.setText("a note")
    window._on_search()
    assert len(window._database.get_recent_searches()) == 1

    hit_path = window._last_hits[0].path
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("renamed.txt", True))

    window._on_rename_file(hit_path)

    assert len(window._database.get_recent_searches()) == 1  # unchanged
    assert len(window._results_view._cards) == 1
    assert window._results_view._cards[0].filename_label.text() == "renamed.txt"


def test_delete_refresh_does_not_record_history(window, monkeypatch):
    window._search_line_edit.setText("a note")
    window._on_search()
    assert len(window._database.get_recent_searches()) == 1

    hit_path = window._last_hits[0].path
    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(file_actions.send2trash, "send2trash", lambda p: None)

    window._on_delete_file(hit_path)

    assert len(window._database.get_recent_searches()) == 1  # unchanged
    assert len(window._results_view._cards) == 0
    # The deleted file was the only indexed file -- results area should have
    # flipped back to the empty state, not be left showing a blank ResultsView.
    assert window._results_stack.currentWidget() is window._empty_state


def test_selecting_theme_persists_setting_without_affecting_search(window):
    try:
        window._on_theme_selected(Theme.DARK)
        assert window._database.get_setting("theme") == "dark"

        window._search_line_edit.setText("a note")
        window._on_search()
        assert len(window._database.get_recent_searches()) == 1
        assert len(window._results_view._cards) == 1
    finally:
        # Reset the shared QApplication's palette so this doesn't leak a dark
        # theme into other tests -- QApplication is a per-process singleton.
        window._on_theme_selected(Theme.LIGHT)


def test_empty_state_shown_when_nothing_indexed(empty_window):
    assert empty_window._results_stack.currentWidget() is empty_window._empty_state


def test_results_view_shown_once_a_file_is_indexed(empty_window, tmp_path):
    file_path = tmp_path / "later.txt"
    file_path.write_text("hello", encoding="utf-8")
    embedding = np.ones(EMBED_DIM, dtype=np.float32)
    embedding /= np.linalg.norm(embedding)
    empty_window._database.upsert_file(
        FileRecord(
            id="id-2",
            path=str(file_path),
            filename="later.txt",
            extension=".txt",
            file_type="text",
            semantic_text="a note",
            metadata={},
            mtime=1.0,
            indexed_at=1.0,
        ),
        embedding,
    )

    # Mirrors what _on_worker_finished does after a real indexing run.
    empty_window._refresh_results_visibility()

    assert empty_window._results_stack.currentWidget() is empty_window._results_view


def test_empty_state_browse_button_wired_to_on_browse(empty_window, monkeypatch, tmp_path):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))

    empty_window._empty_state._browse_button.click()

    assert empty_window._folder_line_edit.text() == str(tmp_path)


def test_populated_window_shows_results_view_not_empty_state(window):
    assert window._results_stack.currentWidget() is window._results_view


class _FakeWorker:
    """Stands in for IndexingWorker in _teardown_worker tests -- only needs
    a wait() the crash-fix regression test can assert was called."""

    def __init__(self):
        self.wait_called = False

    def wait(self, *args, **kwargs):
        self.wait_called = True


def test_teardown_worker_waits_for_thread_before_dropping_reference(window):
    # Bug-fix regression: dropping the last Python reference to a QThread
    # without confirming its underlying OS thread has fully finished is the
    # classic PySide "QThread: Destroyed while thread is still running"
    # crash -- _teardown_worker must call wait() first.
    fake_worker = _FakeWorker()
    window._worker = fake_worker

    window._teardown_worker()

    assert fake_worker.wait_called
    assert window._worker is None


def test_worker_finished_shows_toast_and_resets_to_idle_main_screen(window):
    window._progress_bar.setVisible(True)
    window._status_label.setText("Indexing... 3/5")

    window._on_worker_finished(IndexStats(indexed=5, unchanged_skipped=1, pruned=0, errors=[]))

    # Note: isVisible() alone always reads False here since the test never
    # calls window.show() -- isVisibleTo() checks the explicit show/hide
    # state along the parent chain instead of actual on-screen visibility.
    assert window._toast_label.isVisibleTo(window)
    assert "5" in window._toast_label.text()
    assert not window._progress_bar.isVisibleTo(window)
    assert window._status_label.text() == "Ready."


def test_worker_finished_toast_mentions_errors_when_present(window):
    window._on_worker_finished(
        IndexStats(indexed=3, unchanged_skipped=0, pruned=0, errors=[("bad.jpg", "boom")])
    )

    assert "1 error" in window._toast_label.text()


def test_about_action_shows_version_and_attribution(window, monkeypatch):
    from memoryos.__version__ import __version__

    calls = []
    monkeypatch.setattr(
        QMessageBox, "about", lambda parent, title, text: calls.append((title, text))
    )

    window._on_about()

    assert len(calls) == 1
    title, text = calls[0]
    assert title == "About NYXUS AI"
    assert __version__ in text
    assert "Fluent UI System Icons" in text
