"""AI Project Collections (Week 2, Phase 2): ResultsView's collection
filter -- ANDs with the existing category tab filter, using a per-path
membership map supplied once via set_collection_membership() rather than
looked up per card."""

import sys

from PySide6.QtWidgets import QApplication

from memoryos.database.db import Collection
from memoryos.search.engine import SearchHit
from memoryos.theme import Theme
from memoryos.ui.results_view import ResultsView

_app = QApplication.instance() or QApplication(sys.argv)


def _collection(**overrides) -> Collection:
    defaults = dict(
        id="c1",
        name="Project Zephyr",
        description="",
        auto_generated=False,
        created_at=1.0,
        updated_at=1.0,
        file_paths=[],
    )
    defaults.update(overrides)
    return Collection(**defaults)


def _hit(path: str, filename: str, extension: str = ".pdf") -> SearchHit:
    return SearchHit(
        rank=1,
        filename=filename,
        path=path,
        similarity=0.9,
        reasons=[],
        file_type="pdf",
        metadata={},
    )


def test_collection_filter_narrows_results_to_membership():
    view = ResultsView()
    hits = [_hit("/a.pdf", "a.pdf"), _hit("/b.pdf", "b.pdf")]
    view.set_results(hits, Theme.LIGHT, "query")

    collection = _collection(id="c1", file_paths=["/a.pdf"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection]})

    view._filter_bar._collection_combo.setCurrentIndex(1)  # "Project Zephyr"

    assert [c.filename_label.text() for c in view._cards] == ["a.pdf"]


def test_collection_filter_ands_with_category_tab():
    view = ResultsView()
    hits = [
        SearchHit(rank=1, filename="a.pdf", path="/a.pdf", similarity=0.9, reasons=[], file_type="pdf", metadata={}),
        SearchHit(rank=2, filename="a.jpg", path="/a.jpg", similarity=0.9, reasons=[], file_type="image", metadata={}),
    ]
    view.set_results(hits, Theme.LIGHT, "query")

    collection = _collection(id="c1", file_paths=["/a.pdf", "/a.jpg"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection], "/a.jpg": [collection]})
    view._filter_bar._collection_combo.setCurrentIndex(1)

    # Both files are in the collection, but the "Images" category tab
    # should still narrow it down to just a.jpg.
    view._filter_bar._buttons["Images"].click()

    assert [c.filename_label.text() for c in view._cards] == ["a.jpg"]


def test_no_collection_selected_shows_all_results():
    view = ResultsView()
    hits = [_hit("/a.pdf", "a.pdf"), _hit("/b.pdf", "b.pdf")]
    view.set_results(hits, Theme.LIGHT, "query")

    collection = _collection(id="c1", file_paths=["/a.pdf"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection]})

    assert len(view._cards) == 2


def test_collection_filter_persists_across_a_new_search():
    view = ResultsView()
    collection = _collection(id="c1", file_paths=["/a.pdf"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection]})

    view.set_results([_hit("/a.pdf", "a.pdf"), _hit("/b.pdf", "b.pdf")], Theme.LIGHT, "first query")
    view._filter_bar._collection_combo.setCurrentIndex(1)
    assert [c.filename_label.text() for c in view._cards] == ["a.pdf"]

    # A brand-new search resets the category tab (existing behavior) but the
    # collection scope should still apply -- see SearchResultsFilterBar's
    # own comment on why this is deliberate.
    view.set_results([_hit("/a.pdf", "a.pdf"), _hit("/c.pdf", "c.pdf")], Theme.LIGHT, "second query")

    assert [c.filename_label.text() for c in view._cards] == ["a.pdf"]


def test_empty_state_message_mentions_collection_name_when_that_is_the_reason():
    view = ResultsView()
    collection = _collection(id="c1", name="Project Zephyr", file_paths=[])
    view.set_collections([collection])
    view.set_collection_membership({})  # nothing belongs to it

    view.set_results([_hit("/a.pdf", "a.pdf")], Theme.LIGHT, "query")
    view._filter_bar._collection_combo.setCurrentIndex(1)

    assert view._filter_empty_state.isVisibleTo(view)
    assert "Project Zephyr" in view._filter_empty_state._message_label.text()


def test_deleting_the_selected_collection_resets_filter_to_all():
    view = ResultsView()
    collection = _collection(id="c1", file_paths=["/a.pdf"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection]})
    view.set_results([_hit("/a.pdf", "a.pdf"), _hit("/b.pdf", "b.pdf")], Theme.LIGHT, "query")
    view._filter_bar._collection_combo.setCurrentIndex(1)
    assert len(view._cards) == 1

    # Collection was deleted -- MainWindow calls set_collections() again
    # without it, which should reset the combo (and thus the filter) back
    # to "All Collections".
    view.set_collections([])

    assert len(view._cards) == 2


def test_result_card_receives_its_collections_for_badges():
    view = ResultsView()
    collection = _collection(id="c1", name="Project Zephyr", file_paths=["/a.pdf"])
    view.set_collections([collection])
    view.set_collection_membership({"/a.pdf": [collection]})

    view.set_results([_hit("/a.pdf", "a.pdf")], Theme.LIGHT, "query")

    assert view._cards[0]._collections == [collection]
