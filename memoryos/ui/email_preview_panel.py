"""Email Search Integration Phase 2: a modal preview panel opened from a
ResultCard's "Preview" action for an email hit (.eml/.msg) -- surfaces the
full Subject/From/To/Cc/Date/body-preview/attachments already carried on
SearchHit.metadata (see memoryos/search/engine.py) without needing to open
the file in an external mail client. Built fresh each time it's shown, so
it always reflects the current theme -- no set_theme() update path needed
the way persistent widgets like ResultCard have."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from memoryos.theme import Theme
from memoryos.ui.icons import get_icon

_ATTACHMENT_ICON_SIZE = 16


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


class EmailPreviewPanel(QDialog):
    def __init__(self, metadata: dict, filename: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Email Preview")
        self.setMinimumWidth(480)
        self._build_ui(metadata, filename, theme)

    def _build_ui(self, metadata: dict, filename: str, theme: Theme) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        subject_row = QHBoxLayout()
        subject_icon_label = QLabel()
        subject_icon_label.setPixmap(get_icon("mail", theme).pixmap(20, 20))
        subject_label = QLabel(metadata.get("email_subject") or filename)
        subject_label.setObjectName("sectionTitle")
        subject_label.setWordWrap(True)
        subject_row.addWidget(subject_icon_label)
        subject_row.addWidget(subject_label, 1)
        layout.addLayout(subject_row)

        header_panel = QWidget()
        header_panel.setObjectName("sectionPanel")
        header_layout = QVBoxLayout(header_panel)
        header_layout.setContentsMargins(16, 14, 16, 14)
        header_layout.setSpacing(6)

        for label_text, key in (
            ("From", "email_sender"),
            ("To", "email_recipients"),
            ("Cc", "email_cc"),
            ("Date", "email_date"),
        ):
            value = metadata.get(key)
            if not value:
                continue
            row = QLabel(f"{label_text}: {value}")
            row.setObjectName("mutedLabel")
            row.setWordWrap(True)
            header_layout.addWidget(row)

        layout.addWidget(header_panel)

        body_preview = metadata.get("email_body_preview", "")
        if body_preview:
            body_label = QLabel(body_preview)
            body_label.setWordWrap(True)
            body_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

            body_scroll = QScrollArea()
            body_scroll.setObjectName("emailBodyScroll")
            body_scroll.setWidgetResizable(True)
            body_scroll.setWidget(body_label)
            body_scroll.setMinimumHeight(150)
            layout.addWidget(body_scroll, 1)

        attachments = metadata.get("email_attachments", [])
        if attachments:
            attachments_title = QLabel(
                f"{len(attachments)} attachment{'s' if len(attachments) != 1 else ''}"
            )
            attachments_title.setObjectName("mutedLabel")
            layout.addWidget(attachments_title)

            attach_icon = get_icon("attach", theme)
            for attachment in attachments:
                row = QHBoxLayout()
                icon_label = QLabel()
                icon_label.setPixmap(attach_icon.pixmap(_ATTACHMENT_ICON_SIZE, _ATTACHMENT_ICON_SIZE))
                name_label = QLabel(attachment.get("filename", "(unnamed attachment)"))
                name_label.setWordWrap(True)
                size_label = QLabel(_format_size(attachment.get("size_bytes", 0)))
                size_label.setObjectName("mutedLabel")
                row.addWidget(icon_label)
                row.addWidget(name_label, 1)
                row.addWidget(size_label)
                layout.addLayout(row)

        close_button = QPushButton("Close")
        close_button.setObjectName("primaryButton")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
