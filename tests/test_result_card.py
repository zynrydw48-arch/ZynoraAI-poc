"""Email Search Integration Phase 2: ResultCard's email-aware rendering
(Subject/Sender/Date/Attachments) and its Preview action, additive to the
filename/path every card already shows for every file type."""

import sys
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QLabel

from memoryos.database.db import Collection
from memoryos.search.engine import SearchHit
from memoryos.theme import Theme
from memoryos.ui.email_preview_panel import EmailPreviewPanel
from memoryos.ui.result_card import ResultCard

_app = QApplication.instance() or QApplication(sys.argv)

_WAIT_TIMEOUT_S = 5.0


class _FakeEmbeddingProvider:
    """Same hash-seeded deterministic-pseudo-random-vector fake as
    tests/test_summary_worker.py -- these tests only check that ResultCard
    wires the button/section/worker together, not ranking quality (that's
    tests/test_summarizer.py's job)."""

    @property
    def dimension(self) -> int:
        return 8

    @property
    def model_name(self) -> str:
        return "fake"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            rng = np.random.default_rng(abs(hash(text)) % (2**32))
            vector = rng.random(self.dimension).astype(np.float32)
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.vstack(vectors)


def _wait_until(predicate) -> None:
    deadline = time.time() + _WAIT_TIMEOUT_S
    while not predicate() and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)


def _email_hit(**overrides) -> SearchHit:
    # Matches the real shape memoryos/indexing.py's build_semantic_text_and_metadata
    # actually produces: extractor-specific fields nested under
    # metadata["structural"], not flattened onto metadata directly (see
    # memoryos/extractors/email_extractor.py).
    defaults = dict(
        rank=1,
        filename="contract.eml",
        path="/mail/contract.eml",
        similarity=0.9,
        reasons=["Document text matches: contract"],
        file_type="email",
        metadata={
            "text_snippet": "Subject: Q3 Coffee Export Contract...",
            "colors": [],
            "tags": [],
            "ocr_text": "",
            "caption": "",
            "structural": {
                "email_subject": "Q3 Coffee Export Contract",
                "email_sender": "supplier@example.com",
                "email_recipients": "buyer@example.com",
                "email_date": "Tue, 15 Jul 2025 09:30:00 +0000",
                "email_attachments": [
                    {
                        "filename": "contract.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": 2048,
                    }
                ],
                "email_body_preview": "Please find attached the signed contract.",
            },
        },
    )
    defaults.update(overrides)
    return SearchHit(**defaults)


def _file_hit(**overrides) -> SearchHit:
    defaults = dict(
        rank=1,
        filename="report.pdf",
        path="/docs/report.pdf",
        similarity=0.8,
        reasons=[],
        file_type="pdf",
        metadata={"text_snippet": "quarterly report"},
    )
    defaults.update(overrides)
    return SearchHit(**defaults)


def test_email_hit_filename_label_still_shows_actual_filename():
    card = ResultCard(_email_hit(), Theme.LIGHT)
    assert card.filename_label.text() == "contract.eml"


def test_email_hit_shows_subject_sender_date_and_attachment_count():
    card = ResultCard(_email_hit(), Theme.LIGHT)
    all_text = " ".join(
        w.text() for w in card.findChildren(QLabel) if hasattr(w, "text")
    )
    assert "Q3 Coffee Export Contract" in all_text
    assert "supplier@example.com" in all_text
    assert "Tue, 15 Jul 2025 09:30:00 +0000" in all_text
    assert "1 attachment" in all_text


def test_email_hit_with_no_attachments_shows_no_attachment_count():
    base = _email_hit()
    metadata = {**base.metadata, "structural": {**base.metadata["structural"], "email_attachments": []}}
    hit = _email_hit(metadata=metadata)
    card = ResultCard(hit, Theme.LIGHT)
    all_text = " ".join(w.text() for w in card.findChildren(QLabel) if hasattr(w, "text"))
    assert "attachment" not in all_text


def test_email_hit_has_preview_button_non_email_hit_does_not():
    email_card = ResultCard(_email_hit(), Theme.LIGHT)
    file_card = ResultCard(_file_hit(), Theme.LIGHT)

    assert email_card._preview_button is not None
    assert file_card._preview_button is None


def test_clicking_preview_button_opens_email_preview_panel(monkeypatch):
    opened = []
    monkeypatch.setattr(
        EmailPreviewPanel, "exec", lambda self: opened.append(self) or None
    )

    card = ResultCard(_email_hit(), Theme.LIGHT)
    card._preview_button.click()

    assert len(opened) == 1
    assert opened[0].windowTitle() == "Email Preview"


def test_non_email_hit_reasons_and_path_still_render():
    hit = _file_hit(reasons=["Document text matches: quarterly"])
    card = ResultCard(hit, Theme.LIGHT)
    all_text = " ".join(w.text() for w in card.findChildren(QLabel) if hasattr(w, "text"))
    assert "report.pdf" in all_text
    assert "Document text matches: quarterly" in all_text


# --- AI Project Collections (Week 2, Phase 2): badge chips + "Add to
# Collection..." ------------------------------------------------------


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


def test_no_collections_shows_no_badge():
    card = ResultCard(_file_hit(), Theme.LIGHT, collections=[])
    all_text = " ".join(w.text() for w in card.findChildren(QLabel) if hasattr(w, "text"))
    assert "\U0001F4C1" not in all_text


def test_collections_render_as_badges():
    card = ResultCard(
        _file_hit(),
        Theme.LIGHT,
        collections=[_collection(name="Project Zephyr"), _collection(name="Q3 Financials")],
    )
    all_text = " ".join(w.text() for w in card.findChildren(QLabel) if hasattr(w, "text"))
    assert "Project Zephyr" in all_text
    assert "Q3 Financials" in all_text
    assert all_text.count("\U0001F4C1") == 2


def test_add_to_collection_context_menu_action_emits_signal():
    # _build_context_menu() is a seam that stops short of the real
    # menu.exec() -- that call is a genuine blocking modal in PySide6 and
    # can't be monkeypatched away like QMessageBox.question/QInputDialog.getText
    # elsewhere in this codebase (attempting to crashed the test process).
    card = ResultCard(_file_hit(path="/docs/report.pdf"), Theme.LIGHT)
    received = []
    card.add_to_collection_requested.connect(received.append)

    menu = card._build_context_menu()
    action = next(a for a in menu.actions() if a.text() == "Add to Collection...")
    action.trigger()

    assert received == ["/docs/report.pdf"]


def test_context_menu_has_all_expected_actions():
    card = ResultCard(_file_hit(), Theme.LIGHT)
    menu = card._build_context_menu()
    labels = [a.text() for a in menu.actions() if a.text()]
    assert labels == [
        "Open",
        "Reveal in Folder",
        "Copy Path",
        "Rename...",
        "Delete",
        "Add to Collection...",
    ]


# --- One-Click Context Summary -----------------------------------------


def test_no_embedding_provider_hides_summarize_button():
    hit = _file_hit(semantic_text="Some real document text goes here now.")
    card = ResultCard(hit, Theme.LIGHT)
    assert card._summary_button is None


def test_image_hit_hides_summarize_button_even_with_provider():
    hit = _file_hit(file_type="image", semantic_text="A photo of a white dog outside.")
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())
    assert card._summary_button is None


def test_empty_semantic_text_hides_summarize_button():
    hit = _file_hit(semantic_text="")
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())
    assert card._summary_button is None


def test_non_image_hit_with_text_and_provider_shows_summarize_button():
    hit = _file_hit(semantic_text="Some real document text goes here now.")
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())
    assert card._summary_button is not None


def test_clicking_summarize_shows_loading_then_bullets():
    text = (
        "This is the first sentence of the document. "
        "This is the second sentence with different words. "
        "This is the third sentence about the topic. "
        "This is the fourth sentence also relevant here. "
        "This is the fifth and final sentence of it all."
    )
    hit = _file_hit(semantic_text=text)
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())

    # ResultCard is never .show()n in this unit test, so isVisible() (which
    # reflects the whole ancestor chain) would always read False regardless
    # of this section's own visibility flag -- isVisibleTo(card) is the
    # correct check here (same fix already applied for AddToCollectionDialog).
    assert not card._summary_section.isVisibleTo(card)
    card._summary_button.click()

    assert card._summary_section.isVisibleTo(card)
    assert card._summary_status_label.text() == "Generating summary..."

    _wait_until(lambda: card._summary_bullets is not None)

    assert card._summary_bullets is not None
    assert len(card._summary_bullets) == 3
    assert card._summary_status_label.text().count("•") == 3


def test_clicking_summarize_again_toggles_instead_of_regenerating():
    text = (
        "This is the first sentence of the document. "
        "This is the second sentence with different words. "
        "This is the third sentence about the topic. "
    )
    hit = _file_hit(semantic_text=text)
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())

    card._summary_button.click()
    _wait_until(lambda: card._summary_bullets is not None)
    bullets_after_first_click = card._summary_bullets

    card._summary_button.click()
    # Collapse is now animated (~220ms maximumHeight shrink) -- setVisible(False)
    # only fires on the animation's finished signal, so this needs the same
    # processEvents()-polling wait already used for the SummaryWorker QThread
    # above, not an immediate synchronous assertion.
    _wait_until(lambda: not card._summary_section.isVisibleTo(card))
    assert not card._summary_section.isVisibleTo(card)
    assert card._summary_bullets is bullets_after_first_click

    card._summary_button.click()
    assert card._summary_section.isVisibleTo(card)
    assert card._summary_bullets is bullets_after_first_click


def test_email_hit_summarizes_body_preview_not_metadata_text():
    card = ResultCard(_email_hit(), Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())
    assert card._summary_text == "Please find attached the signed contract."


def test_prepare_for_removal_waits_for_in_flight_worker():
    text = (
        "This is the first sentence of the document. "
        "This is the second sentence with different words. "
        "This is the third sentence about the topic. "
        "This is the fourth sentence also relevant here. "
    )
    hit = _file_hit(semantic_text=text)
    card = ResultCard(hit, Theme.LIGHT, embedding_provider=_FakeEmbeddingProvider())

    card._summary_button.click()
    assert card._summary_worker is not None

    card.prepare_for_removal()

    assert card._summary_worker is None
