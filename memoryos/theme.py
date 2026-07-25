"""Light/Dark/System theme handling. DARK uses Qt's Fusion style + a small
hand-built dark QPalette, plus (Sprint 7) a QSS stylesheet layered on top for
shape/spacing/hover-state polish -- the palette remains the color-token
source of truth; QSS never redefines base colors, only adds presentation.
LIGHT (and SYSTEM resolving to light) restore the app's real original
style/palette, captured once at startup (see memoryos/ui/app.py) rather than
reconstructed here.
"""

from collections.abc import Callable
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class Theme(str, Enum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


def _default_color_scheme_provider() -> Qt.ColorScheme:
    return QApplication.instance().styleHints().colorScheme()


def resolve_effective_theme(
    theme: Theme,
    color_scheme_provider: Callable[[], Qt.ColorScheme] = _default_color_scheme_provider,
) -> Theme:
    """SYSTEM resolves to LIGHT or DARK based on the OS; LIGHT/DARK pass
    through unchanged. Falls back to LIGHT if the OS scheme is unknown."""
    if theme != Theme.SYSTEM:
        return theme
    scheme = color_scheme_provider()
    return Theme.DARK if scheme == Qt.ColorScheme.Dark else Theme.LIGHT


def _dark_palette() -> QPalette:
    # NYXUS AI rebrand: deep-navy/gold tokens, matching dark.qss's literals --
    # keeps native dialogs (QMessageBox/QInputDialog/QFileDialog) visually
    # consistent with the redesigned custom panels instead of showing the
    # old flat gray. ToolTipBase previously stayed pure white in dark mode
    # (a latent bug never actually noticed) -- now correctly dark too.
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(11, 15, 23))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(242, 239, 233))
    palette.setColor(QPalette.ColorRole.Base, QColor(8, 11, 20))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(28, 37, 65))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(11, 19, 43))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(242, 239, 233))
    palette.setColor(QPalette.ColorRole.Text, QColor(242, 239, 233))
    palette.setColor(QPalette.ColorRole.Button, QColor(11, 19, 43))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(242, 239, 233))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(201, 119, 129))
    palette.setColor(QPalette.ColorRole.Link, QColor(212, 175, 55))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(212, 175, 55))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(11, 19, 43))
    return palette


def apply_theme(
    app: QApplication,
    theme: Theme,
    original_palette: QPalette,
    original_style_name: str,
    color_scheme_provider: Callable[[], Qt.ColorScheme] = _default_color_scheme_provider,
) -> None:
    effective = resolve_effective_theme(theme, color_scheme_provider)
    if effective == Theme.DARK:
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
    else:
        app.setStyle(original_style_name)
        app.setPalette(original_palette)

    # Deferred import: memoryos.ui.styles imports Theme from this module, so
    # importing it at module load time here would be circular.
    from memoryos.ui.styles import load_stylesheet

    app.setStyleSheet(load_stylesheet(effective))
