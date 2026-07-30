"""Luxury Visual & Motion Polish (Week 2 final phase): small, reusable
animation/effect helpers shared by ResultCard, CollectionCard, ResultsView,
and CollectionsView -- same "shared collaborator, not copy-paste" principle
already used for the injected EmbeddingProvider.

Scope notes (see the approved plan): Qt Widgets/QSS has no backdrop-blur or
box-shadow, and no true 3D perspective transform. Drop shadows here are real
QGraphicsDropShadowEffect instances applied in Python, hover "tilt" is a
cursor-tracked radial-gradient glow (2.5D, not an actual perspective skew),
and nothing here runs a continuous animation while idle -- everything is
triggered by an actual state change (hover, expand/collapse, entrance,
discovery-in-progress)."""

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPauseAnimation,
    QPointF,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
    Property,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QWidget

_DEFAULT_ACCENT = QColor(0xD4, 0xAF, 0x37)


def apply_drop_shadow(
    widget: QWidget,
    *,
    blur_radius: int = 24,
    color: QColor | None = None,
    offset: tuple[int, int] = (0, 6),
) -> QGraphicsDropShadowEffect:
    """Real drop shadow (QSS has no box-shadow) -- reserved for the small,
    fixed-count chrome widgets the spec names (search bar, primary buttons,
    the recent-search panel), never for per-item cards in a scrollable list,
    since Qt only allows one QGraphicsEffect per widget and a permanent
    shadow on every visible card would both conflict with the entrance fade
    effect and scale badly with result-set size."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur_radius)
    effect.setColor(color if color is not None else QColor(0, 0, 0, 160))
    effect.setOffset(*offset)
    widget.setGraphicsEffect(effect)
    return effect


def animate_height(
    widget: QWidget,
    target_height: int,
    parent,
    *,
    duration_ms: int = 220,
    easing: QEasingCurve.Type = QEasingCurve.Type.OutExpo,
    on_finished=None,
) -> QPropertyAnimation:
    """Animates widget.maximumHeight from its current value to
    target_height. Caller is responsible for widget.setVisible(True) before
    growing, and for passing on_finished=lambda: widget.setVisible(False)
    when collapsing to 0 -- this is also what re-expands the ResultCard
    Summary drawer a second time once loading text is replaced by the
    (taller) final bullets.

    Re-triggering while a previous call's animation is still running stops
    it first (kept alive via a Python attribute on the widget, not
    DeleteWhenStopped, so it's always safe to call .stop() on)."""
    existing: QPropertyAnimation | None = getattr(widget, "_motion_height_animation", None)
    if existing is not None and existing.state() == QAbstractAnimation.State.Running:
        existing.stop()

    animation = QPropertyAnimation(widget, b"maximumHeight", parent)
    animation.setDuration(duration_ms)
    animation.setStartValue(widget.maximumHeight())
    animation.setEndValue(target_height)
    animation.setEasingCurve(easing)
    if on_finished is not None:
        animation.finished.connect(on_finished)
    widget._motion_height_animation = animation
    animation.start(QPropertyAnimation.DeletionPolicy.KeepWhenStopped)
    return animation


def stagger_entrance(
    widgets: list[QWidget],
    parent,
    *,
    stagger_ms: int = 30,
    max_stagger_widgets: int = 8,
    duration_ms: int = 220,
) -> QParallelAnimationGroup:
    """Per-widget staggered opacity fade-in (QGraphicsOpacityEffect, cleared
    once finished -- same idiom as the whole-container fade this replaces).
    Delay is capped at max_stagger_widgets * stagger_ms so a long result
    list doesn't take seconds to fully reveal.

    Deliberately opacity-only, not a combined fade+rise: a first pass
    animated each widget's own `geometry` property directly for the rise,
    but a live visual check showed the cards ending up stacked/overlapping
    -- animating `geometry` on a widget still managed by a live QVBoxLayout
    fights the layout's own geometry assignment the moment it reasserts
    positions (any deferred initial layout pass, any sibling change, any
    resize), which is common, not a rare edge case. Opacity is not
    layout-managed, so it has no such conflict."""
    group = QParallelAnimationGroup(parent)

    for index, widget in enumerate(widgets):
        delay_ms = min(index, max_stagger_widgets) * stagger_ms

        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        fade = QPropertyAnimation(effect, b"opacity", parent)
        fade.setDuration(duration_ms)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.finished.connect(lambda w=widget: w.setGraphicsEffect(None))

        sequence = QSequentialAnimationGroup(parent)
        sequence.addAnimation(QPauseAnimation(delay_ms, parent))
        sequence.addAnimation(fade)

        group.addAnimation(sequence)

    group.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)
    return group


class HoverGlowOverlay(QWidget):
    """Cursor-tracked radial-gradient highlight over a card -- the "3D
    tilt" ask scoped down to something QWidget can actually do cheaply: no
    perspective transform, just a soft glow that follows the mouse.

    Qt delivers mouse-move events to whichever child widget is directly
    under the cursor (a label, an icon button), not to the card itself, so
    watching only the card would miss almost the entire hover area -- this
    installs the same event filter on the card AND every descendant found
    at construction time (ResultCard/CollectionCard call attach_hover_glow
    as the last line of _build_ui, once every child already exists).
    Marked WA_TransparentForMouseEvents so the overlay itself never
    intercepts clicks meant for the card's own buttons underneath it."""

    def __init__(self, card: QWidget, accent: QColor):
        super().__init__(card)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._card = card
        self._accent = QColor(accent)
        self._highlight_pos: QPointF | None = None
        # Moving between two child widgets inside the same card (e.g. one
        # icon button to the label beside it) fires a Leave on one and an
        # Enter on the other -- a depth counter (rather than treating any
        # single Leave as "the cursor left the card") is what keeps the glow
        # from flickering off during those in-card transitions.
        self._hover_depth = 0
        self.setGeometry(card.rect())
        self.hide()
        self._watch(card)
        for child in card.findChildren(QWidget):
            if child is not self:
                self._watch(child)

    def _watch(self, widget: QWidget) -> None:
        widget.setMouseTracking(True)
        widget.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        event_type = event.type()
        if obj is self._card and event_type == QEvent.Type.Resize:
            self.setGeometry(self._card.rect())
        elif event_type == QEvent.Type.MouseMove:
            local_pos = obj.mapTo(self._card, event.position().toPoint())
            self._highlight_pos = QPointF(local_pos)
            if not self.isVisible():
                self.show()
                self.raise_()
            self.update()
        elif event_type == QEvent.Type.Enter:
            self._hover_depth += 1
            self.show()
            self.raise_()
        elif event_type == QEvent.Type.Leave:
            self._hover_depth = max(0, self._hover_depth - 1)
            if self._hover_depth == 0:
                self._highlight_pos = None
                self.hide()
        return False

    def paintEvent(self, event) -> None:
        if self._highlight_pos is None:
            return
        radius = max(self.width(), self.height(), 1) * 0.65
        glow = QColor(self._accent)
        glow.setAlpha(60)
        transparent = QColor(self._accent)
        transparent.setAlpha(0)
        gradient = QRadialGradient(self._highlight_pos, radius)
        gradient.setColorAt(0.0, glow)
        gradient.setColorAt(1.0, transparent)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), gradient)


def attach_hover_glow(card: QWidget, *, accent: QColor | None = None) -> HoverGlowOverlay:
    return HoverGlowOverlay(card, accent if accent is not None else _DEFAULT_ACCENT)


class SweepOverlay(QWidget):
    """Champagne-gold scanning sweep shown over CollectionsView's container
    while Discover Projects is running -- a looping diagonal gradient band
    driven by a Qt Property so QPropertyAnimation can animate it by name."""

    def __init__(self, container: QWidget, accent: QColor):
        super().__init__(container)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._container = container
        self._accent = QColor(accent)
        self._sweep_x = 0.0
        self._active = False
        self.setGeometry(container.rect())
        self.hide()
        container.installEventFilter(self)

        self._animation = QPropertyAnimation(self, b"sweepX", self)
        self._animation.setDuration(1200)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setLoopCount(-1)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._container and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._container.rect())
        return False

    def _get_sweep_x(self) -> float:
        return self._sweep_x

    def _set_sweep_x(self, value: float) -> None:
        self._sweep_x = value
        self.update()

    sweepX = Property(float, _get_sweep_x, _set_sweep_x)

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        self._active = True
        self.setGeometry(self._container.rect())
        self.show()
        self.raise_()
        self._animation.stop()
        self._animation.start()

    def stop(self) -> None:
        self._active = False
        self._animation.stop()
        self.hide()

    def paintEvent(self, event) -> None:
        width = self.width() or 1
        band_width = max(width * 0.18, 1)
        center_x = self._sweep_x * (width + band_width) - band_width / 2
        transparent = QColor(self._accent)
        transparent.setAlpha(0)
        glow = QColor(self._accent)
        glow.setAlpha(90)
        gradient = QLinearGradient(center_x - band_width, 0, center_x + band_width, 0)
        gradient.setColorAt(0.0, transparent)
        gradient.setColorAt(0.5, glow)
        gradient.setColorAt(1.0, transparent)
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)


def attach_discovery_sweep(container: QWidget, *, accent: QColor | None = None) -> SweepOverlay:
    return SweepOverlay(container, accent if accent is not None else _DEFAULT_ACCENT)
