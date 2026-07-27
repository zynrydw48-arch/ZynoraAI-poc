from email.message import EmailMessage
from pathlib import Path

import pytest

from memoryos.extractors.docx_extractor import extract_docx
from memoryos.extractors.email_extractor import _build_result_from_msg_object, extract_email
from memoryos.extractors.pdf_extractor import extract_pdf
from memoryos.extractors.pptx_extractor import extract_pptx
from memoryos.extractors.xlsx_extractor import extract_xlsx
from memoryos.ocr.tesseract_engine import TesseractOcrEngine

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_FILES_2 = PROJECT_ROOT / "all test data" / "test files 2"
TEST_FILES_3 = PROJECT_ROOT / "all test data" / "test files 3"


@pytest.fixture(scope="module")
def ocr_engine():
    return TesseractOcrEngine()


def test_extract_pdf_gets_text_and_page_count(ocr_engine):
    result = extract_pdf(TEST_FILES_2 / "world-map.pdf", ocr_engine)
    assert result.structural_metadata["page_count"] == 1
    assert "Greenland" in result.text or "Brazil" in result.text


def test_extract_pdf_caps_embedded_images(ocr_engine):
    result = extract_pdf(TEST_FILES_2 / "first aid.pdf", ocr_engine)
    assert result.structural_metadata["page_count"] == 4
    assert len(result.embedded_images) <= 5
    assert result.text.strip() != ""


def test_extract_pptx_gets_text_and_slide_count():
    result = extract_pptx(TEST_FILES_3 / "70YEARS ISRAEL.PPTX")
    assert result.structural_metadata["slide_count"] > 0
    assert "ישראל" in result.text
    assert len(result.embedded_images) <= 5


def test_extract_docx_roundtrip(tmp_path):
    from docx import Document

    doc = Document()
    doc.add_paragraph("Quarterly financial report for the coffee division")
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Region"
    table.rows[0].cells[1].text = "Revenue"
    docx_path = tmp_path / "smoketest.docx"
    doc.save(docx_path)

    result = extract_docx(docx_path)
    assert "Quarterly financial report" in result.text
    assert "Region" in result.text
    assert "Revenue" in result.text
    assert result.structural_metadata["paragraph_count"] == 1


def test_extract_xlsx_roundtrip(tmp_path):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws["A1"] = "Product"
    ws["B1"] = "Green coffee beans"
    xlsx_path = tmp_path / "smoketest.xlsx"
    wb.save(xlsx_path)

    result = extract_xlsx(xlsx_path)
    assert "Green coffee beans" in result.text
    assert result.structural_metadata["sheet_names"] == ["Sales"]


# --- Email Search Integration Phase 1: .eml (stdlib email package) ---------


def test_extract_eml_roundtrip_plain_text_body(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Quarterly Report"
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Date"] = "Mon, 1 Jan 2024 10:00:00 +0000"
    msg.set_content("Please find attached the quarterly report on coffee sales.")

    eml_path = tmp_path / "report.eml"
    eml_path.write_bytes(bytes(msg))

    result = extract_email(eml_path)

    assert "Quarterly Report" in result.text
    assert "coffee sales" in result.text
    meta = result.structural_metadata
    assert meta["email_subject"] == "Quarterly Report"
    assert "alice@example.com" in meta["email_sender"]
    assert "bob@example.com" in meta["email_recipients"]
    assert meta["email_date"]


def test_extract_eml_html_only_body_is_stripped_to_plain_text(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Newsletter"
    msg["From"] = "news@example.com"
    msg.set_content(
        "<html><body><p>Hello <b>world</b>, check our <i>new</i> product.</p></body></html>",
        subtype="html",
    )

    eml_path = tmp_path / "newsletter.eml"
    eml_path.write_bytes(bytes(msg))

    result = extract_email(eml_path)

    assert "Hello" in result.text
    assert "world" in result.text
    assert "new" in result.text
    assert "<p>" not in result.text
    assert "<b>" not in result.text


def test_extract_eml_records_attachment_metadata_without_extracting_content(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Invoice"
    msg["From"] = "billing@example.com"
    msg.set_content("Please see the attached invoice.")
    attachment_bytes = b"%PDF-fake-invoice-bytes"
    msg.add_attachment(
        attachment_bytes, maintype="application", subtype="pdf", filename="invoice.pdf"
    )

    eml_path = tmp_path / "invoice.eml"
    eml_path.write_bytes(bytes(msg))

    result = extract_email(eml_path)

    attachments = result.structural_metadata["email_attachments"]
    assert len(attachments) == 1
    assert attachments[0]["filename"] == "invoice.pdf"
    assert attachments[0]["content_type"] == "application/pdf"
    assert attachments[0]["size_bytes"] == len(attachment_bytes)


def test_extract_eml_image_attachment_becomes_embedded_image(tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Photo"
    msg["From"] = "carol@example.com"
    msg.set_content("Check out this photo.")
    image_bytes = b"fake-png-bytes"
    msg.add_attachment(image_bytes, maintype="image", subtype="png", filename="photo.png")

    eml_path = tmp_path / "photo.eml"
    eml_path.write_bytes(bytes(msg))

    result = extract_email(eml_path)

    assert result.embedded_images == [image_bytes]
    non_image_attachments = [
        a for a in result.structural_metadata["email_attachments"] if a["filename"] == "photo.png"
    ]
    assert non_image_attachments[0]["content_type"] == "image/png"


# --- Email Search Integration Phase 1: .msg (extract-msg library) ---------
#
# Real .msg files are OLE compound-file binaries with no simple way to
# synthesize one by hand for a test fixture. These tests exercise this
# module's own field-mapping logic (_build_result_from_msg_object) against a
# lightweight fake object matching extract_msg.Message's public attribute
# surface, rather than testing extract_msg's own binary-format parsing --
# that's trusted third-party behavior, same division of responsibility as
# not re-testing PyMuPDF's PDF parsing in test_extract_pdf_gets_text_and_page_count.


class _FakeMsgAttachment:
    def __init__(self, filename: str, mimetype: str, data: bytes):
        self._filename = filename
        self.mimetype = mimetype
        self.data = data
        self.longFilename = filename
        self.shortFilename = filename

    def getFilename(self) -> str:
        return self._filename


class _FakeMsgObject:
    def __init__(
        self,
        subject="",
        sender="",
        to="",
        cc="",
        date=None,
        body="",
        htmlBody=None,
        attachments=None,
    ):
        self.subject = subject
        self.sender = sender
        self.to = to
        self.cc = cc
        self.date = date
        self.body = body
        self.htmlBody = htmlBody
        self.attachments = attachments or []


def test_extract_msg_field_mapping_via_fake_object():
    fake = _FakeMsgObject(
        subject="Project Update",
        sender="carol@example.com",
        to="dave@example.com",
        cc="eve@example.com",
        date="2024-01-01 10:00:00",
        body="Here is this week's update.",
        attachments=[_FakeMsgAttachment("notes.txt", "text/plain", b"some notes")],
    )

    result = _build_result_from_msg_object(fake)

    assert "Project Update" in result.text
    assert "carol@example.com" in result.text
    assert "Here is this week's update." in result.text
    meta = result.structural_metadata
    assert meta["email_subject"] == "Project Update"
    assert meta["email_sender"] == "carol@example.com"
    assert meta["email_recipients"] == "dave@example.com"
    assert meta["email_cc"] == "eve@example.com"
    assert meta["email_attachments"] == [
        {"filename": "notes.txt", "content_type": "text/plain", "size_bytes": len(b"some notes")}
    ]


def test_extract_msg_falls_back_to_html_body_when_plain_body_missing():
    fake = _FakeMsgObject(subject="X", body="", htmlBody="<p>Hello <b>world</b></p>")

    result = _build_result_from_msg_object(fake)

    assert "Hello" in result.text
    assert "world" in result.text
    assert "<p>" not in result.text


def test_extract_msg_image_attachment_becomes_embedded_image():
    fake = _FakeMsgObject(
        subject="Photo",
        attachments=[_FakeMsgAttachment("pic.jpg", "image/jpeg", b"fake-jpeg-bytes")],
    )

    result = _build_result_from_msg_object(fake)

    assert result.embedded_images == [b"fake-jpeg-bytes"]


def test_extract_msg_guesses_content_type_from_extension_when_mimetype_missing():
    fake = _FakeMsgObject(
        subject="Photo",
        attachments=[_FakeMsgAttachment("pic.png", mimetype=None, data=b"fake-png-bytes")],
    )

    result = _build_result_from_msg_object(fake)

    assert result.structural_metadata["email_attachments"][0]["content_type"] == "image/png"
    assert result.embedded_images == [b"fake-png-bytes"]
