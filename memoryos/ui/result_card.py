"""Sprint 7: one card per search result, replacing a QTableWidget row.
Renders a SearchHit and exposes signals for the same five file actions
Sprint 4 already implemented -- MainWindow connects these to its existing,
unchanged handler methods; this widget knows nothing about Database or
file_actions itself."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from memoryos.background.summary_worker import SummaryWorker
from memoryos.database.db import Collection
from memoryos.embeddings.provider import EmbeddingProvider
from memoryos.search.engine import SearchHit
from memoryos.theme import Theme
from memoryos.ui.email_preview_panel import EmailPreviewPanel
from memoryos.ui.icons import get_icon
from memoryos.utils.extensions import EMAIL, IMAGE

_PATH_ELIDE_MAX_CHARS = 90


class ResultCard(QWidget):
    open_requested = Signal(str)
    reveal_requested = Signal(str)
    copy_requested = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    add_to_collection_requested = Signal(str)  # file path

    def __init__(
        self,
        hit: SearchHit,
        theme: Theme,
        collections: list[Collection] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("resultCard")
        # Plain QWidget subclasses don't paint QSS background-color/border by
        # default (unlike a bare QWidget() instance) -- this opts back in.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._path = hit.path
        self._is_email = hit.file_type == EMAIL
        self._collections = collections or []
        # Extractor-specific structured fields (email_subject, page_count for
        # PDF, etc.) live nested under metadata["structural"] -- see
        # memoryos/indexing.py's build_semantic_text_and_metadata, which is
        # what actually populates this shape -- not flattened onto metadata
        # directly.
        self._email_metadata = hit.metadata.get("structural", {}) if self._is_email else {}
        self._email_filename = hit.filename
        self._preview_button: QPushButton | None = None

        # One-Click Context Summary: an email's body preview reads better as
        # the summary source than its raw semantic_text (which is prefixed
        # with Subject/Sender/Date for search-ranking purposes, not prose).
        # Images are skipped entirely -- their "semantic_text" is already a
        # short caption, not a document with sentences worth extracting from.
        self._embedding_provider = embedding_provider
        if self._is_email:
            self._summary_text = self._email_metadata.get("email_body_preview", "")
        else:
            self._summary_text = hit.semantic_text
        self._can_summarize = (
            embedding_provider is not None
            and hit.file_type != IMAGE
            and bool(self._summary_text.strip())
        )
        self._summary_button: QPushButton | None = None
        self._summary_section: QWidget | None = None
        self._summary_status_label: QLabel | None = None
        self._summary_worker: SummaryWorker | None = None
        self._summary_bullets: list[str] | None = None
        # Tracked explicitly rather than read back via
        # self._summary_section.isVisible() -- isVisible() reflects the
        # whole ancestor chain (always False until the card itself is
        # actually shown), which would make every toggle click show the
        # section instead of alternating (same isVisible() pitfall already
        # hit and fixed for AddToCollectionDialog._creating_new).
        self._summary_expanded = False

        self._build_ui(hit)
        self.set_theme(theme)

        # Sprint 7: right-click stays a secondary path to the same five
        # actions the inline icon buttons already expose (Sprint 4's context
        # menu, preserved rather than dropped now that rows are cards).
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def _build_ui(self, hit: SearchHit) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        self.filename_label = QLabel(hit.filename)
        self.filename_label.setStyleSheet("font-weight: 600; font-size: 14px;")
        similarity_label = QLabel(f"{hit.similarity:.0%} match")
        similarity_label.setObjectName("mutedLabel")
        header_row.addWidget(self.filename_label, 1)
        header_row.addWidget(similarity_label)
        layout.addLayout(header_row)

        path_label = QLabel(self._elided_path(hit.path))
        path_label.setObjectName("mutedLabel")
        path_label.setToolTip(hit.path)
        layout.addWidget(path_label)

        # AI Project Collections (Week 2, Phase 2): one small chip per
        # collection this file belongs to -- additive, same "don't touch
        # filename_label/existing rows" principle as the email summary rows
        # below.
        if self._collections:
            layout.addLayout(self._build_collection_badges_row())

        # Email Search Integration Phase 2: Subject/Sender/Date/Attachments
        # surfaced straight from SearchHit.metadata (see
        # memoryos/search/engine.py) -- additive to the filename/path every
        # card already shows, not a replacement, so rename/delete tests that
        # assert on filename_label's text for non-email files stay correct.
        if self._is_email:
            self._add_email_summary_rows(layout, self._email_metadata)

        if hit.reasons:
            reasons_label = QLabel(" | ".join(hit.reasons))
            reasons_label.setObjectName("mutedLabel")
            reasons_label.setWordWrap(True)
            layout.addWidget(reasons_label)

        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        self._open_button = self._make_icon_button("open", "Open", self.open_requested)
        self._reveal_button = self._make_icon_button(
            "folder_open", "Reveal in Folder", self.reveal_requested
        )
        self._copy_button = self._make_icon_button("copy", "Copy Path", self.copy_requested)
        self._rename_button = self._make_icon_button("edit", "Rename...", self.rename_requested)
        self._delete_button = self._make_icon_button(
            "delete", "Delete", self.delete_requested, danger=True
        )
        buttons = [
            self._open_button,
            self._reveal_button,
            self._copy_button,
            self._rename_button,
            self._delete_button,
        ]
        if self._is_email:
            self._preview_button = QPushButton()
            self._preview_button.setObjectName("iconButton")
            self._preview_button.setToolTip("Preview email")
            self._preview_button.setProperty("iconName", "eye")
            self._preview_button.setIconSize(QSize(18, 18))
            self._preview_button.clicked.connect(self._show_email_preview)
            buttons.append(self._preview_button)
        if self._can_summarize:
            self._summary_button = QPushButton()
            self._summary_button.setObjectName("iconButton")
            self._summary_button.setToolTip("Summarize")
            self._summary_button.setProperty("iconName", "sparkle")
            self._summary_button.setIconSize(QSize(18, 18))
            self._summary_button.clicked.connect(self._on_summarize_clicked)
            buttons.append(self._summary_button)
        for button in buttons:
            actions_row.addWidget(button)
        layout.addLayout(actions_row)

        if self._can_summarize:
            self._summary_section = QWidget()
            summary_layout = QVBoxLayout(self._summary_section)
            summary_layout.setContentsMargins(0, 4, 0, 0)
            summary_layout.setSpacing(4)
            self._summary_status_label = QLabel()
            self._summary_status_label.setObjectName("summaryLabel")
            self._summary_status_label.setWordWrap(True)
            summary_layout.addWidget(self._summary_status_label)
            self._summary_section.setVisible(False)
            layout.addWidget(self._summary_section)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _add_email_summary_rows(self, layout: QVBoxLayout, metadata: dict) -> None:
        subject = metadata.get("email_subject")
        if subject:
            subject_label = QLabel(f"Subject: {subject}")
            subject_label.setWordWrap(True)
            layout.addWidget(subject_label)

        sender = metadata.get("email_sender")
        date = metadata.get("email_date")
        summary_parts = [p for p in (f"From: {sender}" if sender else "", date) if p]
        if summary_parts:
            summary_label = QLabel("  |  ".join(summary_parts))
            summary_label.setObjectName("mutedLabel")
            summary_label.setWordWrap(True)
            layout.addWidget(summary_label)

        attachments = metadata.get("email_attachments", [])
        if attachments:
            count = len(attachments)
            attachments_label = QLabel(f"{count} attachment{'s' if count != 1 else ''}")
            attachments_label.setObjectName("mutedLabel")
            layout.addWidget(attachments_label)

    def _build_collection_badges_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        for collection in self._collections:
            badge = QLabel(f"\U0001F4C1 {collection.name}")  # 📁
            badge.setObjectName("collectionBadge")
            row.addWidget(badge)
        row.addStretch(1)
        return row

    def _show_email_preview(self) -> None:
        dialog = EmailPreviewPanel(self._email_metadata, self._email_filename, self._theme, parent=self)
        dialog.exec()

    def _on_summarize_clicked(self) -> None:
        if self._summary_bullets is not None:
            # Already generated -- a second click just toggles visibility
            # instead of re-running the worker.
            self._summary_expanded = not self._summary_expanded
            self._summary_section.setVisible(self._summary_expanded)
            return
        if self._summary_worker is not None:
            return  # already generating

        self._summary_expanded = True
        self._summary_section.setVisible(True)
        self._summary_status_label.setText("Generating summary...")
        self._summary_worker = SummaryWorker(self._summary_text, self._embedding_provider, self)
        self._summary_worker.finished_summary.connect(self._on_summary_finished)
        self._summary_worker.error.connect(self._on_summary_error)
        self._summary_worker.start()

    def _on_summary_finished(self, bullets: list[str]) -> None:
        self._summary_worker = None
        self._summary_bullets = bullets
        if bullets:
            self._summary_status_label.setText("\n".join(f"• {b}" for b in bullets))
        else:
            self._summary_status_label.setText("Not enough text to summarize.")

    def _on_summary_error(self, message: str) -> None:
        self._summary_worker = None
        self._summary_status_label.setText("Couldn't generate a summary.")

    def prepare_for_removal(self) -> None:
        """Called by ResultsView before dropping this card so an in-flight
        SummaryWorker isn't destroyed mid-run -- same QThread-destroyed-
        while-running crash class MainWindow's _teardown_worker already
        guards against for IndexingWorker (see memoryos/ui/main_window.py)."""
        if self._summary_worker is not None:
            self._summary_worker.wait()
            self._summary_worker = None

    def _make_icon_button(self, icon_name: str, tooltip: str, signal: Signal, danger: bool = False) -> QPushButton:
        button = QPushButton()
        button.setObjectName("dangerIconButton" if danger else "iconButton")
        button.setToolTip(tooltip)
        button.setProperty("iconName", icon_name)
        button.setIconSize(QSize(18, 18))
        button.clicked.connect(lambda: signal.emit(self._path))
        return button

    def _elided_path(self, path: str) -> str:
        metrics = QFontMetrics(self.font())
        avg_char_width = metrics.averageCharWidth() or 6
        return metrics.elidedText(
            path, Qt.TextElideMode.ElideMiddle, _PATH_ELIDE_MAX_CHARS * avg_char_width
        )

    def _build_context_menu(self) -> QMenu:
        """Split out from _show_context_menu so tests can trigger an action
        directly (menu.exec() is a real blocking modal call in PySide6 that
        can't be monkeypatched away like QMessageBox.question/QInputDialog.getText
        elsewhere in this codebase -- calling it in a test either hangs or
        crashes the process)."""
        menu = QMenu(self)
        menu.addAction("Open", lambda: self.open_requested.emit(self._path))
        menu.addAction("Reveal in Folder", lambda: self.reveal_requested.emit(self._path))
        menu.addAction("Copy Path", lambda: self.copy_requested.emit(self._path))
        menu.addAction("Rename...", lambda: self.rename_requested.emit(self._path))
        menu.addAction("Delete", lambda: self.delete_requested.emit(self._path))
        menu.addSeparator()
        menu.addAction(
            "Add to Collection...", lambda: self.add_to_collection_requested.emit(self._path)
        )
        return menu

    def _show_context_menu(self, position) -> None:
        self._build_context_menu().exec(self.mapToGlobal(position))

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        buttons = [
            self._open_button,
            self._reveal_button,
            self._copy_button,
            self._rename_button,
            self._delete_button,
        ]
        if self._preview_button is not None:
            buttons.append(self._preview_button)
        if self._summary_button is not None:
            buttons.append(self._summary_button)
        for button in buttons:
            icon_name = button.property("iconName")
            button.setIcon(get_icon(icon_name, theme))
