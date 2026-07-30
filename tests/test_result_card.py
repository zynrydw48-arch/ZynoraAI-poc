"""Email Search Integration Phase 2: ResultCard's email-aware rendering
(Subject/Sender/Date/Attachments) and its Preview action, additive to the
filename/path every card already shows for every file type."""

import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from memoryos.database.db import Collection
from memoryos.search.engine import SearchHit
from memoryos.theme import Theme
from memoryos.ui.email_preview_panel import EmailPreviewPanel
from memoryos.ui.result_card import ResultCard

_app = QApplication.instance() or QApplication(sys.argv)


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
