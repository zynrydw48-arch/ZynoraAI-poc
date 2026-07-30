"""AddToCollectionDialog: constructed and interacted with directly, never
via exec() -- that's a real blocking modal call in PySide6 (see
tests/test_result_card.py's context-menu test for why that matters)."""

import sys

from PySide6.QtWidgets import QApplication, QDialog

from memoryos.database.db import Collection
from memoryos.ui.add_to_collection_dialog import AddToCollectionDialog

_app = QApplication.instance() or QApplication(sys.argv)


def _collection(**overrides) -> Collection:
    defaults = dict(
        id="c1",
        name="Project Zephyr",
        description="",
        auto_generated=False,
        created_at=1.0,
        updated_at=1.0,
        file_paths=[],
    )
    defaults.update(overrides)
    return Collection(**defaults)


def test_no_existing_collections_shows_name_field_directly_no_combo():
    dialog = AddToCollectionDialog([])
    # isVisibleTo(dialog), not isVisible() -- the dialog itself is never
    # shown in these tests (no exec()/show()), so plain isVisible() always
    # reads False regardless of each widget's own explicit state; see
    # tests/test_main_window.py's established use of the same pattern.
    assert not dialog._combo.isVisibleTo(dialog)
    assert dialog._new_name_edit.isVisibleTo(dialog)


def test_existing_collections_shows_combo_not_name_field_initially():
    dialog = AddToCollectionDialog([_collection()])
    assert dialog._combo.isVisibleTo(dialog)
    assert not dialog._new_name_edit.isVisibleTo(dialog)


def test_selecting_new_collection_in_combo_reveals_name_field():
    dialog = AddToCollectionDialog([_collection()])
    new_index = dialog._combo.count() - 1  # "+ New collection..." is always last
    dialog._combo.setCurrentIndex(new_index)

    assert dialog._new_name_edit.isVisibleTo(dialog)


def test_picking_an_existing_collection_and_clicking_add_returns_its_id():
    dialog = AddToCollectionDialog([_collection(id="abc"), _collection(id="def", name="Other")])
    dialog._combo.setCurrentIndex(0)  # first real collection, not "+ New..."

    dialog._on_add_clicked()

    assert dialog.existing_collection_id() == "abc"
    assert dialog.new_collection_name() is None
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_typing_a_new_name_and_clicking_add_returns_the_name():
    dialog = AddToCollectionDialog([])
    dialog._new_name_edit.setText("  Trip to Rome  ")

    dialog._on_add_clicked()

    assert dialog.new_collection_name() == "Trip to Rome"
    assert dialog.existing_collection_id() is None
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_empty_new_name_does_not_accept_the_dialog():
    dialog = AddToCollectionDialog([])
    dialog._new_name_edit.setText("   ")

    dialog._on_add_clicked()

    assert dialog.new_collection_name() is None
    assert dialog.result() != QDialog.DialogCode.Accepted


def test_cancel_button_rejects_the_dialog():
    dialog = AddToCollectionDialog([_collection()])

    cancel_button = next(
        b for b in dialog.findChildren(type(dialog._add_button)) if b.text() == "Cancel"
    )
    cancel_button.click()

    assert dialog.result() == QDialog.DialogCode.Rejected
