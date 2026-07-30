"""Email Search Integration Phase 2: the modal preview panel opened from a
ResultCard's Preview action (see tests/test_result_card.py for that wiring)."""

import sys

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from memoryos.theme import Theme
from memoryos.ui.email_preview_panel import EmailPreviewPanel, _format_size

_app = QApplication.instance() or QApplication(sys.argv)


def _labels_text(dialog) -> str:
    return " ".join(label.text() for label in dialog.findChildren(QLabel))


def test_full_metadata_renders_all_header_fields_and_body():
    metadata = {
        "email_subject": "Q3 Coffee Export Contract",
        "email_sender": "supplier@example.com",
        "email_recipients": "buyer@example.com",
        "email_cc": "manager@example.com",
        "email_date": "Tue, 15 Jul 2025 09:30:00 +0000",
        "email_body_preview": "Please find attached the signed contract.",
        "email_attachments": [
            {"filename": "contract.pdf", "content_type": "application/pdf", "size_bytes": 2048}
        ],
    }
    dialog = EmailPreviewPanel(metadata, "contract.eml", Theme.LIGHT)

    text = _labels_text(dialog)
    assert "Q3 Coffee Export Contract" in text
    assert "supplier@example.com" in text
    assert "buyer@example.com" in text
    assert "manager@example.com" in text
    assert "Tue, 15 Jul 2025 09:30:00 +0000" in text
    assert "Please find attached the signed contract." in text
    assert "contract.pdf" in text
    assert "1 attachment" in text
    assert "2.0 KB" in text


def test_falls_back_to_filename_when_subject_missing():
    dialog = EmailPreviewPanel({}, "unnamed.eml", Theme.LIGHT)
    text = _labels_text(dialog)
    assert "unnamed.eml" in text


def test_missing_optional_fields_do_not_render_empty_rows():
    metadata = {"email_subject": "Just a subject", "email_sender": "a@b.com"}
    dialog = EmailPreviewPanel(metadata, "x.eml", Theme.LIGHT)

    text = _labels_text(dialog)
    assert "Just a subject" in text
    assert "a@b.com" in text
    assert "None" not in text  # missing To/Cc/Date must not render as "To: None"


def test_no_attachments_shows_no_attachment_count():
    metadata = {"email_subject": "Quarterly planning sync"}
    dialog = EmailPreviewPanel(metadata, "x.eml", Theme.LIGHT)
    text = _labels_text(dialog)
    assert "attachment" not in text


def test_close_button_accepts_dialog():
    dialog = EmailPreviewPanel({"email_subject": "X"}, "x.eml", Theme.LIGHT)
    close_button = next(
        b for b in dialog.findChildren(QPushButton) if b.text() == "Close"
    )
    accepted = []
    dialog.accepted.connect(lambda: accepted.append(True))

    close_button.click()

    assert accepted == [True]


@pytest.mark.parametrize(
    "size_bytes,expected",
    [
        (500, "500 B"),
        (2048, "2.0 KB"),
        (1024 * 1024 * 3, "3.0 MB"),
    ],
)
def test_format_size(size_bytes, expected):
    assert _format_size(size_bytes) == expected
