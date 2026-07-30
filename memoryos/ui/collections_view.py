"""AI Project Collections (Week 2, Phase 2): the "Virtual Folders" view --
a scrollable list of CollectionCards, a "+ New Collection" button, and the
"Discover Projects" auto-discovery trigger. Owned by MainWindow, which feeds
it collections via refresh() and reacts to its signals by calling into
CollectionManager/CollectionDiscoveryWorker -- this widget has no direct
knowledge of either, matching ResultsView/SearchHistoryPanel's existing
division of responsibility."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from memoryos.database.db import Collection
from memoryos.theme import Theme
from memoryos.ui.collection_card import CollectionCard
from memoryos.ui.icons import get_icon
from memoryos.ui.motion import attach_discovery_sweep


class CollectionsView(QWidget):
    discover_requested = Signal()
    create_requested = Signal()
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    remove_file_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: list[CollectionCard] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        title_label = QLabel("Collections")
        title_label.setObjectName("sectionTitle")
        header_row.addWidget(title_label)
        header_row.addStretch(1)

        self._new_collection_button = QPushButton(" New Collection")
        self._new_collection_button.clicked.connect(self.create_requested.emit)
        header_row.addWidget(self._new_collection_button)

        self._discover_button = QPushButton(" ✨ Discover Projects")
        self._discover_button.setObjectName("primaryButton")
        self._discover_button.clicked.connect(self.discover_requested.emit)
        header_row.addWidget(self._discover_button)
        layout.addLayout(header_row)

        self._status_label = QLabel()
        self._status_label.setObjectName("mutedLabel")
        self._status_label.setVisible(False)
        layout.addWidget(self._status_label)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(12)
        self._container_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setWidget(self._container)
        layout.addWidget(self._scroll_area, 1)

        # Champagne-gold "scanning" sweep shown over the container for the
        # duration of a Discover Projects run -- see set_discovering() below.
        self._discovery_sweep = attach_discovery_sweep(self._container)

        # Shown instead of the (empty) scroll area when there are no
        # collections at all yet -- either nothing's been created manually
        # or Discover Projects hasn't found anything (yet).
        self._empty_label = QLabel(
            "No collections yet. Click ✨ Discover Projects to auto-detect "
            "related files, or create one manually."
        )
        self._empty_label.setObjectName("mutedLabel")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        self.set_theme(Theme.LIGHT)

    def refresh(self, collections: list[Collection], theme: Theme) -> None:
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()

        for collection in collections:
            card = CollectionCard(collection, theme)
            card.rename_requested.connect(self.rename_requested)
            card.delete_requested.connect(self.delete_requested)
            card.remove_file_requested.connect(self.remove_file_requested)
            self._container_layout.insertWidget(self._container_layout.count() - 1, card)
            self._cards.append(card)

        has_collections = bool(collections)
        self._scroll_area.setVisible(has_collections)
        self._empty_label.setVisible(not has_collections)

    def set_discovering(self, active: bool) -> None:
        """Disables Discover Projects (and New Collection, to avoid mutating
        collections while a discovery run is about to write new ones) for
        the duration of the background worker, with a status line so a
        multi-second scan over a large corpus doesn't look like nothing is
        happening."""
        self._discover_button.setEnabled(not active)
        self._new_collection_button.setEnabled(not active)
        self._status_label.setVisible(active)
        if active:
            self._status_label.setText("Scanning indexed files for related projects...")
            self._discovery_sweep.start()
        else:
            self._discovery_sweep.stop()

    def set_theme(self, theme: Theme) -> None:
        self._new_collection_button.setIcon(get_icon("folder", theme))
        for card in self._cards:
            card.set_theme(theme)
