"""Sprint 7: scrollable list of ResultCard widgets, replacing the old
QTableWidget results display. MainWindow calls set_results(hits, theme,
query) with whatever DatabaseSearchEngine already returned -- this widget
has no search logic of its own, only presentation and (V2) client-side
filtering over the already-fetched hits.

AI Project Collections (Week 2, Phase 2): the collection filter (from
SearchResultsFilterBar's dropdown) ANDs with the existing category tab, and
collection membership is supplied once per search/update via
set_collection_membership() -- a dict already computed by MainWindow from
one CollectionManager query, not looked up per card -- both for filtering
and for the badge chips ResultCard renders."""

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QScrollArea, QVBoxLayout, QWidget

from memoryos.database.db import Collection
from memoryos.search.engine import SearchHit
from memoryos.theme import Theme
from memoryos.ui.filter_empty_state import FilterEmptyState
from memoryos.ui.result_card import ResultCard
from memoryos.ui.search_results_filter_bar import (
    NO_COLLECTION_FILTER,
    SearchResultsFilterBar,
    categorize_extension,
)

_FADE_DURATION_MS = 180


class ResultsView(QWidget):
    open_requested = Signal(str)
    reveal_requested = Signal(str)
    copy_requested = Signal(str)
    rename_requested = Signal(str)
    delete_requested = Signal(str)
    filter_selected = Signal(str)
    add_to_collection_requested = Signal(str)  # file path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = Theme.LIGHT
        self._cards: list[ResultCard] = []
        self._fade_animation: QPropertyAnimation | None = None
        self._all_hits: list[SearchHit] = []
        self._current_query = ""
        self._active_filter = "All"
        self._active_collection_id = NO_COLLECTION_FILTER
        self._collection_membership: dict[str, list[Collection]] = {}
        self._collection_names: dict[str, str] = {}

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(12)

        # V2: shown above the results list only once a search actually has
        # results (see set_results() below) -- hidden by default here so it
        # never flashes visible before the first populated search.
        self._filter_bar = SearchResultsFilterBar()
        self._filter_bar.filter_selected.connect(self._on_filter_selected)
        self._filter_bar.collection_filter_selected.connect(self._on_collection_filter_selected)
        self._filter_bar.setVisible(False)
        outer_layout.addWidget(self._filter_bar)

        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(12)
        self._container_layout.addStretch(1)

        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setWidget(self._container)
        outer_layout.addWidget(self._scroll_area)

        # V2: shown instead of the (empty) scroll area when a filter tab
        # other than "All" matches none of the current search's hits.
        self._filter_empty_state = FilterEmptyState()
        self._filter_empty_state.setVisible(False)
        outer_layout.addWidget(self._filter_empty_state)

    def set_results(self, hits: list[SearchHit], theme: Theme, query: str = "") -> None:
        self._theme = theme
        self._all_hits = hits
        self._current_query = query
        self._active_filter = "All"

        # The filter bar only makes sense once there's something to filter --
        # hidden for a zero-result search, and reset to "All" on every new
        # populated search so a stale tab selection from a previous,
        # unrelated search doesn't silently carry over. The collection
        # filter is deliberately NOT reset here -- see
        # SearchResultsFilterBar's own comment on why it persists.
        self._filter_bar.setVisible(bool(hits))
        if hits:
            self._filter_bar.reset()

        self._render_filtered()

    def set_collections(self, collections: list[Collection]) -> None:
        """Feeds the filter bar's dropdown and this view's own id->name
        lookup (for the collection-scoped empty-state message) -- called by
        MainWindow whenever collections are created/renamed/deleted/
        discovered, so neither ever shows stale data."""
        self._filter_bar.set_collections(collections)
        self._collection_names = {c.id: c.name for c in collections}

    def set_collection_membership(self, membership: dict[str, list[Collection]]) -> None:
        self._collection_membership = membership
        self._render_filtered()

    def _on_filter_selected(self, label: str) -> None:
        self._active_filter = label
        self._render_filtered()
        # Preserves the external signal contract from the previous sprint --
        # ResultsView still re-emits this upward even though it now also
        # acts on it internally.
        self.filter_selected.emit(label)

    def _on_collection_filter_selected(self, collection_id: str) -> None:
        self._active_collection_id = collection_id
        self._render_filtered()

    def _render_filtered(self) -> None:
        filtered = self._all_hits
        if self._active_filter != "All":
            filtered = [
                hit
                for hit in filtered
                if categorize_extension(Path(hit.path).suffix) == self._active_filter
            ]

        active_collection_name = None
        if self._active_collection_id:
            active_collection_name = self._collection_names.get(self._active_collection_id)
            filtered = [
                hit
                for hit in filtered
                if any(
                    c.id == self._active_collection_id
                    for c in self._collection_membership.get(hit.path, [])
                )
            ]

        self._render_cards(filtered)

        # Only the "some results overall, but none in this specific
        # category/collection" case shows the new per-filter empty state --
        # a genuine zero-result search is a different, already-existing case
        # (the filter bar itself is hidden then, per set_results() above).
        show_empty_message = bool(self._all_hits) and not filtered
        self._filter_empty_state.setVisible(show_empty_message)
        self._scroll_area.setVisible(not show_empty_message)
        if show_empty_message:
            self._filter_empty_state.set_message(
                self._active_filter, self._current_query, active_collection_name
            )

        self._play_fade_in()

    def _render_cards(self, hits: list[SearchHit]) -> None:
        for card in self._cards:
            card.setParent(None)
        self._cards.clear()

        for hit in hits:
            card = ResultCard(
                hit, self._theme, collections=self._collection_membership.get(hit.path, [])
            )
            card.open_requested.connect(self.open_requested)
            card.reveal_requested.connect(self.reveal_requested)
            card.copy_requested.connect(self.copy_requested)
            card.rename_requested.connect(self.rename_requested)
            card.delete_requested.connect(self.delete_requested)
            card.add_to_collection_requested.connect(self.add_to_collection_requested)
            self._container_layout.insertWidget(self._container_layout.count() - 1, card)
            self._cards.append(card)

    def set_theme(self, theme: Theme) -> None:
        self._theme = theme
        for card in self._cards:
            card.set_theme(theme)
        self._filter_empty_state.set_theme(theme)

    def _play_fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self._container)
        self._container.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(_FADE_DURATION_MS)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        # Clear the effect once fully opaque -- leaving a QGraphicsOpacityEffect
        # attached permanently forces Qt to render this subtree through an
        # offscreen buffer on every repaint, even once opacity is back to 1.0.
        animation.finished.connect(lambda: self._container.setGraphicsEffect(None))
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_animation = animation
