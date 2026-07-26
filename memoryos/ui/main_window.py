"""Sprint 2: indexing runs on a background IndexingWorker thread with its own
SQLite connection (see memoryos/database/db.py's WAL mode), so the UI and
search stay responsive throughout. A main-thread QTimer drives a
ResourceMonitor that auto-pauses/resumes the worker; a manual Pause/Resume
button overrides it until the user clicks Resume again."""

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QAction, QActionGroup, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from memoryos import file_actions
from memoryos.__version__ import __version__
from memoryos.background.resource_monitor import PauseReason, ResourceMonitor
from memoryos.background.worker import IndexingWorker
from memoryos.database.db import Database
from memoryos.embeddings.provider import EmbeddingProvider
from memoryos.indexing import DatabaseIndexer, IndexStats
from memoryos.ocr.engine import OcrEngine
from memoryos.scanner.discover import discover_files
from memoryos.search.engine import DatabaseSearchEngine, SearchHit
from memoryos.theme import Theme, apply_theme, resolve_effective_theme
from memoryos.ui.empty_state import EmptyState
from memoryos.ui.icons import get_icon
from memoryos.ui.results_view import ResultsView
from memoryos.ui.search_history_panel import SearchHistoryPanel
from memoryos.vision.pipeline import VisionPipeline

THEME_SETTING_KEY = "theme"
_THEME_MENU_LABELS = {
    Theme.LIGHT: "Light",
    Theme.DARK: "Dark",
    Theme.SYSTEM: "System",
}

RESOURCE_CHECK_INTERVAL_MS = 2000
_PROGRESS_ANIMATION_MS = 150
_TOAST_DURATION_MS = 4000

_PAUSE_REASON_LABELS = {
    PauseReason.USER_REQUESTED: "Paused (by user)",
    PauseReason.BATTERY_SAVER: "Paused: Battery Saver is on",
    PauseReason.FULLSCREEN_APP_DETECTED: "Paused: fullscreen app detected",
    PauseReason.LOW_BATTERY: "Paused: battery low",
    PauseReason.HIGH_CPU: "Paused: CPU usage is high",
    PauseReason.LOW_RAM: "Paused: memory usage is high",
}


class MainWindow(QMainWindow):
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        ocr_engine: OcrEngine,
        vision_pipeline: VisionPipeline,
        database: Database,
        db_path: Path,
        original_palette: QPalette | None = None,
        original_style_name: str | None = None,
    ):
        super().__init__()
        self.setWindowTitle("Zynora AI")
        self.resize(1000, 650)

        self._embedding_provider = embedding_provider
        self._ocr_engine = ocr_engine
        self._vision_pipeline = vision_pipeline
        self._db_path = db_path
        self._database = database  # Sprint 3: needed for search history
        self._search_engine = DatabaseSearchEngine(embedding_provider, database)
        self._selected_folder: Path | None = None

        self._worker: IndexingWorker | None = None
        self._resource_monitor: ResourceMonitor | None = None
        self._resource_timer: QTimer | None = None
        self._manual_pause_active = False
        self._current_pause_reason: PauseReason | None = None
        self._last_hits: list[SearchHit] = []
        self._progress_animation: QPropertyAnimation | None = None

        # Sprint 5: fall back to the current app palette/style if not given
        # (e.g. constructed directly in a test) so theming never crashes.
        app = QApplication.instance()
        self._original_palette = original_palette if original_palette is not None else app.palette()
        self._original_style_name = original_style_name or app.style().objectName()
        self._current_theme = Theme(self._database.get_setting(THEME_SETTING_KEY, Theme.SYSTEM.value))

        self._build_ui()

        apply_theme(app, self._current_theme, self._original_palette, self._original_style_name)
        app.styleHints().colorSchemeChanged.connect(self._on_system_color_scheme_changed)

    def _build_ui(self) -> None:
        self._build_menu_bar()
        effective_theme = self._effective_theme()

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setSpacing(18)

        self._toast_label = QLabel()
        self._toast_label.setObjectName("toastBanner")
        self._toast_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._toast_label.setVisible(False)
        layout.addWidget(self._toast_label)

        index_panel = QWidget()
        index_panel.setObjectName("sectionPanel")
        index_layout = QVBoxLayout(index_panel)
        # Matches ResultCard/SearchHistoryPanel's explicit margins -- every
        # "sectionPanel"-styled container should have identical inner spacing.
        index_layout.setContentsMargins(18, 16, 18, 16)

        index_title_row = QHBoxLayout()
        self._index_title_icon = QLabel()
        self._index_title_icon.setPixmap(get_icon("desktop", effective_theme).pixmap(18, 18))
        index_title_row.addWidget(self._index_title_icon)
        index_title_row.addWidget(self._section_title("Index"))
        index_title_row.addStretch(1)
        index_layout.addLayout(index_title_row)

        folder_row = QHBoxLayout()
        self._folder_line_edit = QLineEdit()
        self._folder_line_edit.setReadOnly(True)
        self._folder_line_edit.setPlaceholderText("No folder selected")
        self._browse_button = QPushButton(" Browse...")
        self._browse_button.setIcon(get_icon("folder", effective_theme))
        self._browse_button.clicked.connect(self._on_browse)
        self._start_button = QPushButton(" Start Indexing")
        self._start_button.setIcon(get_icon("play", effective_theme))
        self._start_button.setObjectName("primaryButton")
        self._start_button.clicked.connect(self._on_start_indexing)
        self._pause_resume_button = QPushButton(" Pause")
        self._pause_resume_button.setIcon(get_icon("pause", effective_theme))
        self._pause_resume_button.setEnabled(False)
        self._pause_resume_button.clicked.connect(self._on_pause_resume_clicked)
        self._cancel_button = QPushButton(" Cancel")
        self._cancel_button.setIcon(get_icon("stop", effective_theme))
        self._cancel_button.setEnabled(False)
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        folder_row.addWidget(QLabel("Folder:"))
        folder_row.addWidget(self._folder_line_edit, 1)
        folder_row.addWidget(self._browse_button)
        folder_row.addWidget(self._start_button)
        folder_row.addWidget(self._pause_resume_button)
        folder_row.addWidget(self._cancel_button)
        index_layout.addLayout(folder_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setVisible(False)
        index_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("Ready.")
        self._status_label.setObjectName("mutedLabel")
        index_layout.addWidget(self._status_label)

        layout.addWidget(index_panel)

        search_panel = QWidget()
        search_panel.setObjectName("sectionPanel")
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(18, 16, 18, 16)

        search_title_row = QHBoxLayout()
        self._search_title_icon = QLabel()
        self._search_title_icon.setPixmap(get_icon("search", effective_theme).pixmap(18, 18))
        search_title_row.addWidget(self._search_title_icon)
        search_title_row.addWidget(self._section_title("Search"))
        search_title_row.addStretch(1)
        search_layout.addLayout(search_title_row)

        search_row = QHBoxLayout()
        self._search_line_edit = QLineEdit()
        self._search_line_edit.setPlaceholderText("Describe the file you remember...")
        self._search_line_edit.returnPressed.connect(self._on_search)
        self._search_button = QPushButton(" Search")
        self._search_button.setIcon(get_icon("search", effective_theme))
        self._search_button.setObjectName("primaryButton")
        self._search_button.clicked.connect(self._on_search)
        search_row.addWidget(self._search_line_edit, 1)
        search_row.addWidget(self._search_button)
        search_layout.addLayout(search_row)

        layout.addWidget(search_panel)

        # Sprint 3 addition, restyled in Sprint 7: recent-searches panel is
        # now a self-contained styled widget with its own "Recent searches"
        # header -- no separate QLabel needed above it any more.
        self._history_panel = SearchHistoryPanel()
        self._history_panel.set_theme(effective_theme)
        self._history_panel.entry_selected.connect(self._on_history_entry_selected)
        self._history_panel.clear_requested.connect(self._on_clear_history_clicked)
        self._history_panel.refresh(self._database.get_recent_searches())
        layout.addWidget(self._history_panel)

        # Sprint 7: EmptyState (nothing indexed yet) and ResultsView (the
        # card-based results list, replacing the old results table) share one
        # stacked area -- _refresh_results_visibility() below picks which one
        # is showing based on len(self._database).
        self._empty_state = EmptyState()
        self._empty_state.set_theme(effective_theme)
        self._empty_state.browse_requested.connect(self._on_browse)

        self._results_view = ResultsView()
        self._results_view.open_requested.connect(self._on_open_file)
        self._results_view.reveal_requested.connect(self._on_reveal_in_folder)
        self._results_view.copy_requested.connect(self._on_copy_path)
        self._results_view.rename_requested.connect(self._on_rename_file)
        self._results_view.delete_requested.connect(self._on_delete_file)

        self._results_stack = QStackedWidget()
        self._results_stack.addWidget(self._empty_state)
        self._results_stack.addWidget(self._results_view)
        layout.addWidget(self._results_stack, 1)
        self._refresh_results_visibility()

        self.setCentralWidget(central)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _effective_theme(self) -> Theme:
        return resolve_effective_theme(self._current_theme)

    def _set_status_style(self, object_name: str) -> None:
        """V2 Sprint 1: color-codes the status label by state (normal/
        paused/error) using the new palette's warning/danger tokens --
        setObjectName() alone doesn't retrigger QSS selector matching on an
        already-shown widget, hence the unpolish/polish pair."""
        self._status_label.setObjectName(object_name)
        self._status_label.style().unpolish(self._status_label)
        self._status_label.style().polish(self._status_label)

    def _refresh_results_visibility(self) -> None:
        has_indexed_files = len(self._database) > 0
        self._results_stack.setCurrentWidget(
            self._results_view if has_indexed_files else self._empty_state
        )

    def _build_menu_bar(self) -> None:
        settings_menu = self.menuBar().addMenu("Settings")
        theme_menu = settings_menu.addMenu("Theme")

        self._theme_action_group = QActionGroup(self)
        self._theme_action_group.setExclusive(True)
        for theme in Theme:
            action = QAction(_THEME_MENU_LABELS[theme], self, checkable=True)
            action.setData(theme)
            action.triggered.connect(lambda checked, t=theme: self._on_theme_selected(t))
            if theme == self._current_theme:
                action.setChecked(True)
            self._theme_action_group.addAction(action)
            theme_menu.addAction(action)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About Zynora AI", self)
        about_action.triggered.connect(self._on_about)
        help_menu.addAction(about_action)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About Zynora AI",
            f"<b>Zynora AI</b> version {__version__}"
            "<p>Semantic search over local files by natural-language "
            "description, not filename.</p>"
            "<p>Icons: <a href=\"https://github.com/microsoft/fluentui-system-icons\">"
            "Fluent UI System Icons</a> (Microsoft, MIT License).</p>",
        )

    def _on_theme_selected(self, theme: Theme) -> None:
        self._current_theme = theme
        self._database.set_setting(THEME_SETTING_KEY, theme.value)
        apply_theme(
            QApplication.instance(), theme, self._original_palette, self._original_style_name
        )
        self._refresh_icons()

    def _on_system_color_scheme_changed(self, _color_scheme) -> None:
        if self._current_theme == Theme.SYSTEM:
            apply_theme(
                QApplication.instance(),
                self._current_theme,
                self._original_palette,
                self._original_style_name,
            )
            self._refresh_icons()

    def _refresh_icons(self) -> None:
        """Sprint 7: get_icon() bakes the theme into the returned QIcon, so
        every icon-bearing widget needs re-fetching after a theme switch --
        the QSS/QPalette side of theming refreshes itself, this doesn't."""
        effective_theme = self._effective_theme()
        self._index_title_icon.setPixmap(get_icon("desktop", effective_theme).pixmap(18, 18))
        self._search_title_icon.setPixmap(get_icon("search", effective_theme).pixmap(18, 18))
        self._browse_button.setIcon(get_icon("folder", effective_theme))
        self._start_button.setIcon(get_icon("play", effective_theme))
        self._pause_resume_button.setIcon(
            get_icon("play" if self._manual_pause_active else "pause", effective_theme)
        )
        self._cancel_button.setIcon(get_icon("stop", effective_theme))
        self._search_button.setIcon(get_icon("search", effective_theme))
        self._history_panel.set_theme(effective_theme)
        self._empty_state.set_theme(effective_theme)
        self._results_view.set_theme(effective_theme)

    def _on_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to index")
        if folder:
            self._selected_folder = Path(folder)
            self._folder_line_edit.setText(folder)

    def _on_start_indexing(self) -> None:
        if self._selected_folder is None:
            self._status_label.setText("Pick a folder first.")
            self._set_status_style("mutedLabel")
            return
        if self._worker is not None:
            return

        report = discover_files([self._selected_folder])
        total = len(report.files)
        self._progress_bar.setRange(0, max(total, 1))
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._manual_pause_active = False
        self._current_pause_reason = None
        self._start_button.setEnabled(False)
        self._browse_button.setEnabled(False)
        self._pause_resume_button.setEnabled(True)
        self._pause_resume_button.setText("Pause")
        self._cancel_button.setEnabled(True)
        self._status_label.setText(f"Indexing... 0/{total}")
        self._set_status_style("mutedLabel")

        embedding_provider = self._embedding_provider
        ocr_engine = self._ocr_engine
        vision_pipeline = self._vision_pipeline
        db_path = self._db_path

        def build_indexer() -> DatabaseIndexer:
            # Called from inside the worker thread's run() -- constructs a
            # fresh SQLite connection there, never sharing the main thread's.
            return DatabaseIndexer(embedding_provider, ocr_engine, vision_pipeline, Database(db_path))

        self._worker = IndexingWorker(build_indexer, report.files)
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.paused.connect(self._on_worker_paused)
        self._worker.resumed.connect(self._on_worker_resumed)
        self._worker.finished_indexing.connect(self._on_worker_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

        self._resource_monitor = ResourceMonitor()
        self._resource_timer = QTimer(self)
        self._resource_timer.timeout.connect(self._check_resources)
        self._resource_timer.start(RESOURCE_CHECK_INTERVAL_MS)

    def _on_pause_resume_clicked(self) -> None:
        if self._worker is None:
            return
        effective_theme = self._effective_theme()
        if self._manual_pause_active:
            self._manual_pause_active = False
            self._worker.request_resume()
            self._pause_resume_button.setText(" Pause")
            self._pause_resume_button.setIcon(get_icon("pause", effective_theme))
        else:
            self._manual_pause_active = True
            self._worker.request_pause(PauseReason.USER_REQUESTED)
            self._pause_resume_button.setText(" Resume")
            self._pause_resume_button.setIcon(get_icon("play", effective_theme))

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None:
            self._worker.request_cancel()
            self._cancel_button.setEnabled(False)
            self._status_label.setText("Cancelling...")
            self._set_status_style("mutedLabel")

    def _check_resources(self) -> None:
        if self._worker is None or self._manual_pause_active:
            return
        reason = self._resource_monitor.decide()
        if reason != PauseReason.NONE:
            self._worker.request_pause(reason)
        else:
            self._worker.request_resume()

    def _on_worker_progress(self, done: int, total: int) -> None:
        self._animate_progress_to(done)
        if self._current_pause_reason is None:
            self._status_label.setText(f"Indexing... {done}/{total}")

    def _animate_progress_to(self, value: int) -> None:
        if self._progress_animation is not None:
            self._progress_animation.stop()
        animation = QPropertyAnimation(self._progress_bar, b"value", self)
        animation.setDuration(_PROGRESS_ANIMATION_MS)
        animation.setStartValue(self._progress_bar.value())
        animation.setEndValue(value)
        animation.start()
        self._progress_animation = animation

    def _on_worker_paused(self, reason: PauseReason) -> None:
        self._current_pause_reason = reason
        label = _PAUSE_REASON_LABELS.get(reason, "Paused")
        self._status_label.setText(
            f"{label} — {self._progress_bar.value()}/{self._progress_bar.maximum()}"
        )
        self._set_status_style("statusLabelWarning")

    def _on_worker_resumed(self) -> None:
        self._current_pause_reason = None
        self._status_label.setText(
            f"Indexing... {self._progress_bar.value()}/{self._progress_bar.maximum()}"
        )
        self._set_status_style("mutedLabel")

    def _on_worker_finished(self, stats: IndexStats) -> None:
        self._teardown_worker()
        self._progress_bar.setVisible(False)
        self._status_label.setText("Ready.")
        self._set_status_style("mutedLabel")
        message = f"Indexing complete — {stats.indexed} file(s) indexed."
        if stats.errors:
            message += f" {len(stats.errors)} error(s)."
        self._show_toast(message)
        # Sprint 7: an indexing run may have taken the database from empty to
        # non-empty (or vice versa, after a prune) -- re-check which of
        # EmptyState/ResultsView should be showing.
        self._refresh_results_visibility()

    def _on_worker_error(self, message: str) -> None:
        self._teardown_worker()
        self._progress_bar.setVisible(False)
        self._status_label.setText(f"Indexing failed: {message}")
        self._set_status_style("statusLabelError")

    def _show_toast(self, message: str) -> None:
        self._toast_label.setText(message)
        self._toast_label.setVisible(True)
        QTimer.singleShot(_TOAST_DURATION_MS, lambda: self._toast_label.setVisible(False))

    def _teardown_worker(self) -> None:
        if self._resource_timer is not None:
            self._resource_timer.stop()
            self._resource_timer = None
        self._resource_monitor = None
        if self._worker is not None:
            # Bug fix: run() has already returned by the time finished_indexing/
            # error fires (both are the last things it does before its finally
            # block), but wait() here removes any race between the OS thread
            # actually finishing and Python dropping the last reference to this
            # QThread -- without it, Qt can destroy a QThread whose underlying
            # thread hasn't fully unwound yet, which crashes the whole process.
            self._worker.wait()
        self._worker = None
        self._current_pause_reason = None
        self._manual_pause_active = False
        self._start_button.setEnabled(True)
        self._browse_button.setEnabled(True)
        self._pause_resume_button.setEnabled(False)
        self._pause_resume_button.setText(" Pause")
        self._pause_resume_button.setIcon(get_icon("pause", self._effective_theme()))
        self._cancel_button.setEnabled(False)

    def _on_search(self) -> None:
        """Public slot for the search box/button -- always records history.
        Kept parameter-free so Qt signal connections (returnPressed/clicked)
        can't accidentally pass a signal argument (e.g. clicked's `checked`
        bool) into a same-named parameter here; see _run_search for the
        history-recording toggle used by internal refreshes."""
        query = self._search_line_edit.text().strip()
        self._run_search(query, record_history=True)

    def _run_search(self, query: str, record_history: bool) -> None:
        if not query:
            return

        hits = self._search_engine.search(query)
        self._last_hits = hits
        self._results_view.set_results(hits, self._effective_theme(), query)
        # A rename/delete-triggered refresh can take the database from
        # non-empty to empty (deleting the last indexed file) -- keep
        # EmptyState/ResultsView in sync with that on every search path.
        self._refresh_results_visibility()

        result_count_text = f"{len(hits)} results." if hits else "No results."
        if self._worker is None:
            self._status_label.setText(result_count_text)
            self._set_status_style("mutedLabel")

        if record_history:
            self._database.record_search_history(query, len(hits))
            self._history_panel.refresh(self._database.get_recent_searches())

    def _on_history_entry_selected(self, query: str) -> None:
        self._search_line_edit.setText(query)
        self._on_search()

    def _on_clear_history_clicked(self) -> None:
        self._database.clear_search_history()
        self._history_panel.refresh(self._database.get_recent_searches())

    def _on_open_file(self, path_str: str) -> None:
        try:
            file_actions.open_file(Path(path_str))
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", str(exc))

    def _on_reveal_in_folder(self, path_str: str) -> None:
        try:
            file_actions.reveal_in_folder(Path(path_str))
        except Exception as exc:
            QMessageBox.warning(self, "Reveal in folder failed", str(exc))

    def _on_copy_path(self, path_str: str) -> None:
        QApplication.clipboard().setText(path_str)

    def _on_rename_file(self, path_str: str) -> None:
        path = Path(path_str)
        new_name, confirmed = QInputDialog.getText(
            self, "Rename file", "New filename:", text=path.name
        )
        if not confirmed or not new_name.strip():
            return

        try:
            new_path = file_actions.rename_file(path, new_name.strip())
            self._database.update_file_path(str(path), str(new_path), new_path.name)
        except Exception as exc:
            QMessageBox.warning(self, "Rename failed", str(exc))
            return

        # Bug fix: refresh the results without recording a new history entry
        # -- this is an internal refresh, not a user-initiated search.
        self._run_search(self._search_line_edit.text().strip(), record_history=False)

    def _on_delete_file(self, path_str: str) -> None:
        path = Path(path_str)
        confirmed = QMessageBox.question(
            self,
            "Delete file",
            f"Move '{path.name}' to the Recycle Bin?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return

        try:
            file_actions.delete_file(path)
            self._database.delete_file_by_path(str(path))
        except Exception as exc:
            QMessageBox.warning(self, "Delete failed", str(exc))
            return

        # Bug fix: refresh the results without recording a new history entry
        # -- this is an internal refresh, not a user-initiated search.
        self._run_search(self._search_line_edit.text().strip(), record_history=False)
