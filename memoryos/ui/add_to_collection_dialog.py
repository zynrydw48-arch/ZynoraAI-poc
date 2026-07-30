"""AI Project Collections (Week 2, Phase 2): the dialog reached from
ResultCard's "Add to Collection..." context-menu action -- lets the user
add a file to an existing collection or create a new one and add it in the
same step. This is the only way a manually-created collection ever gets
files added to it after creation, since there's no separate file browser
widget in this app -- files are only individually visible in search
results.

After exec() returns QDialog.Accepted, exactly one of
existing_collection_id()/new_collection_name() is non-None -- MainWindow
uses that to decide whether to call CollectionManager.add_files() directly
or create_collection() first."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from memoryos.database.db import Collection

_NEW_COLLECTION_SENTINEL = "__new__"
_NEW_COLLECTION_LABEL = "+ New collection..."


class AddToCollectionDialog(QDialog):
    def __init__(self, collections: list[Collection], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add to Collection")
        self.setMinimumWidth(360)
        self._collections = collections
        self._result_existing_id: str | None = None
        self._result_new_name: str | None = None
        # Tracks the user's choice directly rather than inferring it from
        # widget .isVisible() -- that reflects whether the *dialog itself*
        # has been shown yet (False for the whole widget tree before
        # exec()/show()), not just this one field's own visible/hidden
        # state, so it's the wrong thing to branch application logic on.
        self._creating_new = not bool(collections)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Add this file to:"))

        has_existing = bool(self._collections)
        self._combo = QComboBox()
        self._combo.setVisible(has_existing)
        for collection in self._collections:
            self._combo.addItem(collection.name, collection.id)
        self._combo.addItem(_NEW_COLLECTION_LABEL, _NEW_COLLECTION_SENTINEL)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        layout.addWidget(self._combo)

        self._new_name_edit = QLineEdit()
        self._new_name_edit.setPlaceholderText("New collection name")
        # No existing collections at all -- skip straight to naming a new
        # one instead of showing a combo box with only "+ New collection..."
        # in it.
        self._new_name_edit.setVisible(not has_existing)
        layout.addWidget(self._new_name_edit)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        self._add_button = QPushButton("Add")
        self._add_button.setObjectName("primaryButton")
        self._add_button.clicked.connect(self._on_add_clicked)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self._add_button)
        layout.addLayout(button_row)

    def _on_combo_changed(self, index: int) -> None:
        is_new = self._combo.itemData(index) == _NEW_COLLECTION_SENTINEL
        self._creating_new = is_new
        self._new_name_edit.setVisible(is_new)

    def _on_add_clicked(self) -> None:
        if not self._creating_new:
            self._result_existing_id = self._combo.currentData()
        else:
            name = self._new_name_edit.text().strip()
            if not name:
                return
            self._result_new_name = name
        self.accept()

    def existing_collection_id(self) -> str | None:
        return self._result_existing_id

    def new_collection_name(self) -> str | None:
        return self._result_new_name
