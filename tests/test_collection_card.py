import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from memoryos.database.db import Collection
from memoryos.theme import Theme
from memoryos.ui.collection_card import CollectionCard

_app = QApplication.instance() or QApplication(sys.argv)


def _collection(**overrides) -> Collection:
    defaults = dict(
        id="c1",
        name="Project Delta",
        description="Q3 planning",
        auto_generated=False,
        created_at=1.0,
        updated_at=1.0,
        file_paths=["/docs/budget.xlsx", "/docs/pitch.pptx"],
    )
    defaults.update(overrides)
    return Collection(**defaults)


def _all_text(widget) -> str:
    return " ".join(w.text() for w in widget.findChildren(QLabel))


def test_shows_name_description_and_file_count():
    card = CollectionCard(_collection(), Theme.LIGHT)
    assert card.name_label.text() == "Project Delta"
    text = _all_text(card)
    assert "Q3 planning" in text
    assert "2 files" in text
    assert "budget.xlsx" in text
    assert "pitch.pptx" in text


def test_singular_file_count_label():
    card = CollectionCard(_collection(file_paths=["/a.pdf"]), Theme.LIGHT)
    assert "1 file" in _all_text(card)
    assert "1 files" not in _all_text(card)


def test_auto_generated_without_description_shows_fallback_text():
    card = CollectionCard(
        _collection(description="", auto_generated=True), Theme.LIGHT
    )
    assert "AI-suggested" in _all_text(card)


def test_manual_collection_without_description_shows_no_fallback_text():
    card = CollectionCard(_collection(description="", auto_generated=False), Theme.LIGHT)
    assert "AI-suggested" not in _all_text(card)


def test_rename_button_emits_collection_id():
    card = CollectionCard(_collection(id="abc123"), Theme.LIGHT)
    received = []
    card.rename_requested.connect(received.append)

    card._rename_button.click()

    assert received == ["abc123"]


def test_delete_button_emits_collection_id():
    card = CollectionCard(_collection(id="abc123"), Theme.LIGHT)
    received = []
    card.delete_requested.connect(received.append)

    card._delete_button.click()

    assert received == ["abc123"]


def test_remove_file_button_emits_collection_id_and_path():
    card = CollectionCard(
        _collection(id="abc123", file_paths=["/a.pdf", "/b.pdf"]), Theme.LIGHT
    )
    received = []
    card.remove_file_requested.connect(lambda cid, path: received.append((cid, path)))

    _, remove_button = card._file_row_widgets[0]
    remove_button.click()

    assert received == [("abc123", "/a.pdf")]


def test_more_than_max_shown_files_gets_a_remainder_label():
    paths = [f"/file{i}.pdf" for i in range(12)]
    card = CollectionCard(_collection(file_paths=paths), Theme.LIGHT)
    text = _all_text(card)
    assert "+ 4 more" in text
    assert len(card._file_row_widgets) == 8
