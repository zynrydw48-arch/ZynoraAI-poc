import sys

from PySide6.QtWidgets import QApplication

from memoryos.database.db import Collection
from memoryos.theme import Theme
from memoryos.ui.collections_view import CollectionsView

_app = QApplication.instance() or QApplication(sys.argv)


def _collection(**overrides) -> Collection:
    defaults = dict(
        id="c1",
        name="Project Delta",
        description="",
        auto_generated=False,
        created_at=1.0,
        updated_at=1.0,
        file_paths=["/a.pdf"],
    )
    defaults.update(overrides)
    return Collection(**defaults)


def test_empty_state_shown_when_no_collections():
    view = CollectionsView()
    view.refresh([], Theme.LIGHT)

    assert view._empty_label.isVisibleTo(view)
    assert not view._scroll_area.isVisibleTo(view)


def test_cards_shown_and_empty_state_hidden_when_collections_exist():
    view = CollectionsView()
    view.refresh([_collection()], Theme.LIGHT)

    assert not view._empty_label.isVisibleTo(view)
    assert view._scroll_area.isVisibleTo(view)
    assert len(view._cards) == 1


def test_refresh_replaces_previous_cards():
    view = CollectionsView()
    view.refresh([_collection(id="c1"), _collection(id="c2")], Theme.LIGHT)
    assert len(view._cards) == 2

    view.refresh([_collection(id="c3")], Theme.LIGHT)

    assert len(view._cards) == 1


def test_discover_button_emits_discover_requested():
    view = CollectionsView()
    received = []
    view.discover_requested.connect(lambda: received.append(True))

    view._discover_button.click()

    assert received == [True]


def test_new_collection_button_emits_create_requested():
    view = CollectionsView()
    received = []
    view.create_requested.connect(lambda: received.append(True))

    view._new_collection_button.click()

    assert received == [True]


def test_set_discovering_disables_buttons_and_shows_status():
    view = CollectionsView()

    view.set_discovering(True)
    assert not view._discover_button.isEnabled()
    assert not view._new_collection_button.isEnabled()
    assert view._status_label.isVisibleTo(view)

    view.set_discovering(False)
    assert view._discover_button.isEnabled()
    assert view._new_collection_button.isEnabled()
    assert not view._status_label.isVisibleTo(view)


def test_card_signals_bubble_up_through_the_view():
    view = CollectionsView()
    view.refresh([_collection(id="c1")], Theme.LIGHT)

    renamed = []
    deleted = []
    removed = []
    view.rename_requested.connect(renamed.append)
    view.delete_requested.connect(deleted.append)
    view.remove_file_requested.connect(lambda cid, path: removed.append((cid, path)))

    card = view._cards[0]
    card.rename_requested.emit("c1")
    card.delete_requested.emit("c1")
    card.remove_file_requested.emit("c1", "/a.pdf")

    assert renamed == ["c1"]
    assert deleted == ["c1"]
    assert removed == [("c1", "/a.pdf")]
