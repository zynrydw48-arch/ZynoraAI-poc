"""Sprint 7: shown by MainWindow in place of ResultsView whenever the
database has no indexed files yet (len(database) == 0) -- a single welcoming
view per the approved onboarding-depth decision, not a multi-step wizard."""

from PySide6.QtCore import Signal
from PySide6.QtCore import Qt as QtCore_Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from memoryos.theme import Theme
from memoryos.ui.icons import get_icon

_ICON_SIZE = 64


class EmptyState(QWidget):
    browse_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        # Plain QWidget subclasses don't paint QSS background-color/border by
        # default (unlike a bare QWidget() instance) -- this opts back in.
        self.setAttribute(QtCore_Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setAlignment(QtCore_Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        self._icon_label = QLabel()
        self._icon_label.setAlignment(QtCore_Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        title_label = QLabel("Nothing indexed yet")
        title_label.setObjectName("sectionTitle")
        title_label.setAlignment(QtCore_Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        subtitle_label = QLabel(
            "Choose a folder to index, and NYXUS AI will let you find files\n"
            "by describing what you remember about them."
        )
        subtitle_label.setObjectName("mutedLabel")
        subtitle_label.setAlignment(QtCore_Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle_label)

        self._browse_button = QPushButton("Choose a folder to get started")
        self._browse_button.setObjectName("primaryButton")
        self._browse_button.clicked.connect(self.browse_requested)
        layout.addWidget(self._browse_button, alignment=QtCore_Qt.AlignmentFlag.AlignCenter)

        self.set_theme(Theme.LIGHT)

    def set_theme(self, theme: Theme) -> None:
        icon = get_icon("folder", theme)
        self._icon_label.setPixmap(icon.pixmap(_ICON_SIZE, _ICON_SIZE))
