"""Extracts searchable content from local email files.

Two formats, two parsers:
- .eml (RFC 822/2822 plain-text MIME) is parsed with Python's own stdlib
  `email` package -- no extra dependency needed.
- .msg (Outlook's proprietary OLE-compound-file binary format) needs a real
  parser; this uses `extract-msg`, a pure-Python library with no Outlook/COM
  dependency, so indexing still works on a machine without Outlook installed
  -- the same "no external app required" bar every other extractor in this
  package already holds itself to (python-docx/python-pptx/openpyxl don't
  need Office installed either).

Both paths normalize into the same ExtractionResult shape every other
extractor produces: `text` is Subject/From/To/Cc/Date plus the plain-text
body concatenated, so all of it is searchable and embeddable the same way a
PDF's page text is; `structural_metadata` carries the individual fields back
out separately (mirroring how PDF stores page_count) for a future phase's
sender/date-aware ranking or filtering; attachment metadata (filename,
content type, size) is recorded without extracting attachment content --
that's explicitly out of scope for this phase. Inline/attached images are
handed back via `embedded_images`, so they flow through the same vision/OCR
pipeline PDF/PPTX/DOCX/XLSX embedded images already use.
"""

import mimetypes
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

import extract_msg
from lxml import html as lxml_html

from memoryos.extractors.result import ExtractionResult

MAX_EMBEDDED_IMAGES = 5  # matches pdf_extractor.py's cap
MAX_ATTACHMENTS_LISTED = 50  # bounds metadata size on emails with huge attachment counts


def extract_email(path) -> ExtractionResult:
    path = Path(path)
    if path.suffix.lower() == ".msg":
        return _extract_msg(path)
    return _extract_eml(path)


def _html_to_text(html: str) -> str:
    if not html or not html.strip():
        return ""
    try:
        return lxml_html.fromstring(html).text_content().strip()
    except Exception:
        return ""


def _decode_maybe_bytes(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return value or ""


def _build_semantic_text(subject: str, sender: str, to: str, cc: str, date: str, body: str) -> str:
    header_lines = []
    if subject:
        header_lines.append(f"Subject: {subject}")
    if sender:
        header_lines.append(f"From: {sender}")
    if to:
        header_lines.append(f"To: {to}")
    if cc:
        header_lines.append(f"Cc: {cc}")
    if date:
        header_lines.append(f"Date: {date}")
    header_block = "\n".join(header_lines)
    return f"{header_block}\n\n{body}".strip() if header_block else body.strip()


# --- .eml ------------------------------------------------------------------


def _extract_eml(path: Path) -> ExtractionResult:
    with open(path, "rb") as f:
        msg: EmailMessage = BytesParser(policy=policy.default).parse(f)

    subject = str(msg["subject"]) if msg["subject"] else ""
    sender = str(msg["from"]) if msg["from"] else ""
    to = str(msg["to"]) if msg["to"] else ""
    cc = str(msg["cc"]) if msg["cc"] else ""
    date = str(msg["date"]) if msg["date"] else ""

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        body = ""
    elif body_part.get_content_type() == "text/html":
        body = _html_to_text(body_part.get_content())
    else:
        body = body_part.get_content()

    embedded_images: list[bytes] = []
    attachments_metadata = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or "(unnamed attachment)"
        content_type = part.get_content_type()
        try:
            content = part.get_content()
        except Exception:
            content = b""

        if isinstance(content, str):
            size_bytes = len(content.encode("utf-8", errors="ignore"))
        elif isinstance(content, bytes):
            size_bytes = len(content)
        else:
            size_bytes = 0

        if len(attachments_metadata) < MAX_ATTACHMENTS_LISTED:
            attachments_metadata.append(
                {"filename": filename, "content_type": content_type, "size_bytes": size_bytes}
            )

        if (
            content_type.startswith("image/")
            and isinstance(content, bytes)
            and len(embedded_images) < MAX_EMBEDDED_IMAGES
        ):
            embedded_images.append(content)

    return ExtractionResult(
        text=_build_semantic_text(subject, sender, to, cc, date, body),
        embedded_images=embedded_images,
        structural_metadata={
            "email_subject": subject,
            "email_sender": sender,
            "email_recipients": to,
            "email_cc": cc,
            "email_date": date,
            "email_attachments": attachments_metadata,
        },
    )


# --- .msg --------------------------------------------------------------


def _extract_msg(path: Path) -> ExtractionResult:
    msg = extract_msg.Message(str(path))
    try:
        return _build_result_from_msg_object(msg)
    finally:
        msg.close()


def _build_result_from_msg_object(msg) -> ExtractionResult:
    """Split out from _extract_msg so tests can exercise the field-mapping
    logic against a lightweight fake object instead of needing a real .msg
    (OLE compound file) fixture -- extract_msg's own binary-format parsing
    is trusted third-party behavior, not re-tested here."""
    subject = msg.subject or ""
    sender = msg.sender or ""
    to = msg.to or ""
    cc = msg.cc or ""
    date = str(msg.date) if msg.date else ""

    body = msg.body or ""
    if not body:
        body = _html_to_text(_decode_maybe_bytes(getattr(msg, "htmlBody", None)))

    embedded_images: list[bytes] = []
    attachments_metadata = []
    for att in msg.attachments:
        filename = _msg_attachment_filename(att)
        data = att.data if isinstance(att.data, (bytes, bytearray)) else None
        content_type = (
            getattr(att, "mimetype", None)
            or mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )
        size_bytes = len(data) if data is not None else 0

        if len(attachments_metadata) < MAX_ATTACHMENTS_LISTED:
            attachments_metadata.append(
                {"filename": filename, "content_type": content_type, "size_bytes": size_bytes}
            )

        if (
            content_type.startswith("image/")
            and data is not None
            and len(embedded_images) < MAX_EMBEDDED_IMAGES
        ):
            embedded_images.append(bytes(data))

    return ExtractionResult(
        text=_build_semantic_text(subject, sender, to, cc, date, body),
        embedded_images=embedded_images,
        structural_metadata={
            "email_subject": subject,
            "email_sender": sender,
            "email_recipients": to,
            "email_cc": cc,
            "email_date": date,
            "email_attachments": attachments_metadata,
        },
    )


def _msg_attachment_filename(att) -> str:
    try:
        name = att.getFilename()
    except Exception:
        name = None
    if not name:
        name = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None)
    return name or "(unnamed attachment)"
