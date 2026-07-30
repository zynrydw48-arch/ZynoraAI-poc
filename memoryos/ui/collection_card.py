"""AI Project Collections (Week 2, Phase 2): one card per Collection --
name, description/topic keywords, a file-count badge, a scrollable preview
list of its files (each removable), and rename/delete actions. Renders a
Collection and exposes signals for the actions it can trigger; the actual
QInputDialog/QMessageBox confirmations and Database/CollectionManager calls
live in MainWindow, same division of responsibility ResultCard already
uses for its own file actions."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from memoryos.database.db import Collection
from memoryos.theme import Theme
from memoryos.ui.icons import get_icon
from memoryos.ui.motion import attach_hover_glow

_MAX_FILES_SHOWN = 8


class CollectionCard(QWidget):
    rename_requested = Signal(str)  # collection_id
    delete_requested = Signal(str)  # collection_id
    remove_file_requested = Signal(str, str)  # collection_id, file_path

    def __init__(self, collection: Collection, theme: Theme, parent=None):
        super().__init__(parent)
        self.setObjectName("resultCard")
        # Plain QWidget subclasses don't paint QSS background-color/border by
        # default (unlike a bare QWidget() instance) -- this opts back in.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._collection_id = collection.id
        self._file_row_widgets: list[tuple[QWidget, QPushButton]] = []
        self._build_ui(collection)
        self.set_theme(theme)

    def _build_ui(self, collection: Collection) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        self._folder_icon_label = QLabel()
        header_row.addWidget(self._folder_icon_label)
        self.name_label = QLabel(collection.name)
        self.name_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        header_row.addWidget(self.name_label, 1)

        count = len(collection.file_paths)
        badge = QLabel(f"{count} file{'s' if count != 1 else ''}")
        badge.setObjectName("mutedLabel")
        header_row.addWidget(badge)
        layout.addLayout(header_row)

        description = collection.description or (
            "AI-suggested collection" if collection.auto_generated else ""
        )
        if description:
            description_label = QLabel(description)
            description_label.setObjectName("mutedLabel")
            description_label.setWordWrap(True)
            layout.addWidget(description_label)

        for path in collection.file_paths[:_MAX_FILES_SHOWN]:
            layout.addLayout(self._build_file_row(path))
        remaining = count - _MAX_FILES_SHOWN
        if remaining > 0:
            more_label = QLabel(f"+ {remaining} more")
            more_label.setObjectName("mutedLabel")
            layout.addWidget(more_label)

        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        self._rename_button = self._make_icon_button("edit", "Rename collection")
        self._rename_button.clicked.connect(
            lambda: self.rename_requested.emit(self._collection_id)
        )
        self._delete_button = self._make_icon_button("delete", "Delete collection", danger=True)
        self._delete_button.clicked.connect(
            lambda: self.delete_requested.emit(self._collection_id)
        )
        actions_row.addWidget(self._rename_button)
        actions_row.addWidget(self._delete_button)
        layout.addLayout(actions_row)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        attach_hover_glow(self)

    def _build_file_row(self, path: str) -> QHBoxLayout:
        row = QHBoxLayout()
        name_label = QLabel(Path(path).name)
        name_label.setToolTip(path)
        remove_button = QPushButton()
        remove_button.setObjectName("iconButton")
        remove_button.setToolTip("Remove from collection")
        remove_button.setProperty("iconName", "dismiss")
        remove_button.setIconSize(QSize(14, 14))
        remove_button.clicked.connect(
            lambda: self.remove_file_requested.emit(self._collection_id, path)
        )
        row.addWidget(name_label, 1)
        row.addWidget(remove_button)
        self._file_row_widgets.append((name_label, remove_button))
        return row

    def _make_icon_button(self, icon_name: str, tooltip: str, danger: bool = False) -> QPushButton:
        button = QPushButton()
        button.setObjectName("dangerIconButton" if danger else "iconButton")
        button.setToolTip(tooltip)
        button.setProperty("iconName", icon_name)
        button.setIconSize(QSize(18, 18))
        return button

    def set_theme(self, theme: Theme) -> None:
        self._folder_icon_label.setPixmap(get_icon("folder", theme).pixmap(18, 18))
        for button in (self._rename_button, self._delete_button):
            button.setIcon(get_icon(button.property("iconName"), theme))
        for _, remove_button in self._file_row_widgets:
            remove_button.setIcon(get_icon("dismiss", theme))
