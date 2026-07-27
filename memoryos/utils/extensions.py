"""Registry mapping supported file extensions to a file-type label.

Extensions not listed here are unsupported and get skipped by the scanner.
"""

IMAGE = "image"
PDF = "pdf"
PPTX = "pptx"
DOCX = "docx"
XLSX = "xlsx"
EMAIL = "email"

EXTENSION_TO_TYPE = {
    ".jpg": IMAGE,
    ".jpeg": IMAGE,
    ".png": IMAGE,
    ".bmp": IMAGE,
    ".webp": IMAGE,
    ".pdf": PDF,
    ".pptx": PPTX,
    ".docx": DOCX,
    ".xlsx": XLSX,
    ".eml": EMAIL,
    ".msg": EMAIL,
}

# Extensions the spec lists as in-scope but that our chosen libraries can't
# read (legacy binary PowerPoint). Tracked separately so the scanner can
# report them as a distinct, explained skip reason rather than lumping them
# in with genuinely unsupported extensions like .htm.
KNOWN_UNSUPPORTED = {
    ".ppt": "legacy .ppt (binary PowerPoint format) is not supported in this PoC",
}


def classify(extension: str) -> str | None:
    """Return the file-type label for a lowercase extension, or None if unsupported."""
    return EXTENSION_TO_TYPE.get(extension.lower())


def unsupported_reason(extension: str) -> str | None:
    return KNOWN_UNSUPPORTED.get(extension.lower())
