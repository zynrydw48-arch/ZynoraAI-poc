"""Sprint 3: a small, self-contained panel showing recent searches. Owned by
MainWindow, which feeds it entries via refresh() and reacts to
entry_selected/clear_requested by calling into Database and the existing
search path -- this widget has no direct knowledge of either.

Sprint 7: restyled (icon header, card-style panel, empty placeholder) but the
public interface -- refresh()/entry_selected/clear_requested -- is unchanged,
so MainWindow's wiring to it does not need to change."""

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from memoryos.database.db import SearchHistoryEntry
from memoryos.theme import Theme
from memoryos.ui.icons import get_icon
from memoryos.ui.motion import apply_drop_shadow

_ICON_SIZE = 18  # matches MainWindow's other two section-header icons (Index, Search)


class SearchHistoryPanel(QWidget):
    entry_selected = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionPanel")
        # Plain QWidget subclasses don't paint QSS background-color/border by
        # default (unlike a bare QWidget() instance) -- this opts back in.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        self._header_icon_label = QLabel()
        header_row.addWidget(self._header_icon_label)
        title_label = QLabel("Recent searches")
        title_label.setObjectName("sectionTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)
        self._clear_button = QPushButton("Clear")
        self._clear_button.setObjectName("iconButton")
        self._clear_button.clicked.connect(self.clear_requested.emit)
        header_row.addWidget(self._clear_button)
        layout.addLayout(header_row)

        self._list_widget = QListWidget()
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list_widget)

        self._empty_label = QLabel("No recent searches yet.")
        self._empty_label.setObjectName("mutedLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty_label)

        self._entries: list[SearchHistoryEntry] = []
        self.set_theme(Theme.LIGHT)
        self._update_empty_placeholder()
        apply_drop_shadow(self)

    def refresh(self, entries: list[SearchHistoryEntry]) -> None:
        self._entries = entries
        self._list_widget.clear()
        for entry in entries:
            when = datetime.fromtimestamp(entry.timestamp).strftime("%Y-%m-%d %H:%M")
            label = f"{entry.query}  —  {entry.result_count} results  ({when})"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry.query)
            self._list_widget.addItem(item)
        self._update_empty_placeholder()

    def set_theme(self, theme: Theme) -> None:
        self._header_icon_label.setPixmap(get_icon("history", theme).pixmap(_ICON_SIZE, _ICON_SIZE))
        self._clear_button.setIcon(get_icon("dismiss", theme))

    def _update_empty_placeholder(self) -> None:
        has_entries = bool(self._entries)
        self._list_widget.setVisible(has_entries)
        self._empty_label.setVisible(not has_entries)
        self._clear_button.setEnabled(has_entries)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        query = item.data(Qt.ItemDataRole.UserRole)
        self.entry_selected.emit(query)
