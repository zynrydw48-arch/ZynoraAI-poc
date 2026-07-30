"""V2: shown inside ResultsView when a specific filter tab (Images/Web/
Files/Notes/More...) has zero matches within the current search's results.
Distinct from the app-level EmptyState (nothing indexed yet at all) --
this is a smaller, message-only sibling: same icon+centered-message visual
language and the same objectName("emptyState") for free QSS reuse, but no
browse button, since "pick a folder" doesn't apply to an already-populated
search that's just filtered down to nothing."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from memoryos.theme import Theme
from memoryos.ui.icons import get_icon

_ICON_SIZE = 48

# "More..." reads as a broken sentence fragment if lowercased literally
# ("we couldn't find any more... matching...") -- every other category
# lowercases directly per the spec's own worked example.
_MESSAGE_CATEGORY_NAMES = {
    "More...": "other files",
}


class FilterEmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        # Plain QWidget subclasses don't paint QSS background-color/border by
        # default (unlike a bare QWidget() instance) -- this opts back in.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._message_label = QLabel()
        self._message_label.setObjectName("mutedLabel")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        self.set_theme(Theme.LIGHT)

    def set_message(self, category: str, query: str, collection_name: str | None = None) -> None:
        display_name = _MESSAGE_CATEGORY_NAMES.get(category, category.lower())
        message = f"We couldn't find any {display_name} matching '{query}'"
        if collection_name:
            message += f" in '{collection_name}'"
        self._message_label.setText(message)

    def set_theme(self, theme: Theme) -> None:
        icon = get_icon("search", theme)
        self._icon_label.setPixmap(icon.pixmap(_ICON_SIZE, _ICON_SIZE))
