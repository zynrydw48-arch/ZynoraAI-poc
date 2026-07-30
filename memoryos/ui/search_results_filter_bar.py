"""V2: a premium tab-style filter bar shown above ResultsView's results list
once a search actually has results. UI + placeholder signal only -- no real
filtering logic yet; see the widget's filter_selected signal, which a future
sprint can connect to without touching this file again."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

TAB_LABELS = ["All", "Images", "Email", "Web", "Files", "Notes", "More..."]

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
        self._buttons["All"].setChecked(True)

    def _on_tab_clicked(self, label: str) -> None:
        print(f"Filtering for: {label}")
        self.filter_selected.emit(label)

    def reset(self) -> None:
        self._buttons["All"].setChecked(True)
