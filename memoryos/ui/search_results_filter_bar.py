"""V2: a premium tab-style filter bar shown above ResultsView's results list
once a search actually has results. UI + placeholder signal only -- no real
filtering logic yet; see the widget's filter_selected signal, which a future
sprint can connect to without touching this file again."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QComboBox, QHBoxLayout, QPushButton, QWidget

from memoryos.database.db import Collection

TAB_LABELS = ["All", "Images", "Email", "Web", "Files", "Notes", "More..."]

# AI Project Collections (Week 2, Phase 2): sentinel userData for the combo
# box's "no collection filter" entry -- empty string, never a real
# collection_id (those are UUIDs from memoryos.database.db.create_collection).
_ALL_COLLECTIONS_LABEL = "All Collections"
NO_COLLECTION_FILTER = ""

# Client-side categorization only -- purely a re-render over SearchHits
# already fetched by the (untouched) search engine, not a statement about
# what this app can index/extract. "Web"/"Notes" extensions aren't
# currently indexable at all, so those tabs will legitimately show the
# empty state for every corpus this app can actually build today.
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp"}
EMAIL_EXTENSIONS = {".eml", ".msg"}
WEB_EXTENSIONS = {".html", ".htm", ".url"}
FILE_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".txt", ".csv"}
NOTE_EXTENSIONS = {".md", ".markdown", ".norg", ".org"}


def categorize_extension(extension: str) -> str:
    """Maps a file extension (with or without a leading dot) to one of
    TAB_LABELS (excluding "All"), case-insensitively. Anything not in the
    named buckets falls into "More..."."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext in IMAGE_EXTENSIONS:
        return "Images"
    if ext in EMAIL_EXTENSIONS:
        return "Email"
    if ext in WEB_EXTENSIONS:
        return "Web"
    if ext in FILE_EXTENSIONS:
        return "Files"
    if ext in NOTE_EXTENSIONS:
        return "Notes"
    return "More..."


class SearchResultsFilterBar(QWidget):
    filter_selected = Signal(str)
    # collection_id, or NO_COLLECTION_FILTER ("") for "All Collections"
    collection_filter_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("filterBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for label in TAB_LABELS:
            button = QPushButton(label)
            button.setObjectName("filterTab")
            button.setCheckable(True)
            button.clicked.connect(lambda checked, l=label: self._on_tab_clicked(l))
            self._button_group.addButton(button)
            self._buttons[label] = button
            layout.addWidget(button)

        layout.addStretch(1)

        # AI Project Collections (Week 2, Phase 2): a separate, independent
        # filter that ANDs with whichever category tab is active (see
        # ResultsView._render_filtered) -- deliberately does NOT reset on
        # reset()/every new search the way the category tabs do, since
        # "only show me files in Project Zephyr" reads as a standing scope
        # choice the user wants to keep across several different queries,
        # not a per-search view toggle.
        self._collection_combo = QComboBox()
        self._collection_combo.setObjectName("collectionFilterCombo")
        self._collection_combo.addItem(_ALL_COLLECTIONS_LABEL, NO_COLLECTION_FILTER)
        self._collection_combo.currentIndexChanged.connect(self._on_collection_combo_changed)
        layout.addWidget(self._collection_combo)

        self._buttons["All"].setChecked(True)

    def _on_tab_clicked(self, label: str) -> None:
        self.filter_selected.emit(label)

    def _on_collection_combo_changed(self, index: int) -> None:
        collection_id = self._collection_combo.itemData(index) or NO_COLLECTION_FILTER
        self.collection_filter_selected.emit(collection_id)

    def set_collections(self, collections: list[Collection]) -> None:
        """(Re)populates the collection dropdown -- called by MainWindow
        whenever a collection is created/renamed/deleted/discovered, so the
        list never goes stale. Preserves the current selection by id when
        possible; if the previously-selected collection no longer exists
        (e.g. it was just deleted), falls back to "All Collections" and
        emits that change so ResultsView's filter resets along with it."""
        previously_selected = self._collection_combo.currentData() or NO_COLLECTION_FILTER
        self._collection_combo.blockSignals(True)
        self._collection_combo.clear()
        self._collection_combo.addItem(_ALL_COLLECTIONS_LABEL, NO_COLLECTION_FILTER)
        restored_index = 0
        for i, collection in enumerate(collections, start=1):
            self._collection_combo.addItem(collection.name, collection.id)
            if collection.id == previously_selected:
                restored_index = i
        self._collection_combo.setCurrentIndex(restored_index)
        self._collection_combo.blockSignals(False)

        if restored_index == 0 and previously_selected != NO_COLLECTION_FILTER:
            self.collection_filter_selected.emit(NO_COLLECTION_FILTER)

    def reset(self) -> None:
        self._buttons["All"].setChecked(True)
