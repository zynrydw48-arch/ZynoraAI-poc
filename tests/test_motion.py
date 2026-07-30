"""Luxury Visual & Motion Polish: construction/behavior-safety tests for the
shared memoryos/ui/motion.py helpers -- all headless-safe (no .show() or
real event loop needed), matching this codebase's established pattern of
testing animation/effect seams directly rather than driving a full Qt event
loop when avoidable (see e.g. ResultCard._build_context_menu())."""

import sys
import time

import shiboken6
from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QMouseEvent, QResizeEvent
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from memoryos.ui.motion import (
    HoverGlowOverlay,
    SweepOverlay,
    apply_drop_shadow,
    animate_height,
    attach_discovery_sweep,
    attach_hover_glow,
    stagger_entrance,
)

_app = QApplication.instance() or QApplication(sys.argv)

_WAIT_TIMEOUT_S = 3.0


def _wait_until(predicate) -> None:
    deadline = time.time() + _WAIT_TIMEOUT_S
    while not predicate() and time.time() < deadline:
        _app.processEvents()
        time.sleep(0.01)


def test_apply_drop_shadow_installs_effect_with_given_params():
    widget = QWidget()
    effect = apply_drop_shadow(widget, blur_radius=12, offset=(2, 4))

    assert isinstance(effect, QGraphicsDropShadowEffect)
    assert widget.graphicsEffect() is effect
    assert effect.blurRadius() == 12
    assert effect.xOffset() == 2
    assert effect.yOffset() == 4


def test_animate_height_drives_maximum_height_and_fires_callback():
    widget = QWidget()
    widget.setMaximumHeight(0)
    finished = []

    animate_height(widget, 80, widget, duration_ms=30, on_finished=lambda: finished.append(True))
    _wait_until(lambda: widget.maximumHeight() == 80)

    assert widget.maximumHeight() == 80
    assert finished == [True]


def test_animate_height_retrigger_stops_previous_animation():
    widget = QWidget()
    widget.setMaximumHeight(0)

    animate_height(widget, 200, widget, duration_ms=5000)  # slow, still running
    animate_height(widget, 40, widget, duration_ms=30)  # retarget immediately

    _wait_until(lambda: widget.maximumHeight() == 40)
    assert widget.maximumHeight() == 40


def test_stagger_entrance_builds_one_animation_per_widget_with_capped_delay():
    container = QWidget()
    layout = QVBoxLayout(container)
    children = [QWidget() for _ in range(10)]
    for child in children:
        layout.addWidget(child)
    layout.activate()

    group = stagger_entrance(children, container, stagger_ms=30, max_stagger_widgets=8)

    assert group.animationCount() == len(children)
    # Delay is capped at max_stagger_widgets * stagger_ms -- the 9th and 10th
    # (indices 8, 9) widgets should not get an ever-larger delay.
    delay_at_cap = group.animationAt(8).animationAt(0).duration()
    delay_past_cap = group.animationAt(9).animationAt(0).duration()
    assert delay_at_cap == delay_past_cap == 8 * 30


def test_stagger_entrance_handles_empty_list():
    container = QWidget()
    group = stagger_entrance([], container)
    assert group.animationCount() == 0


def test_hover_glow_tracks_mouse_move_and_clears_on_leave():
    card = QWidget()
    overlay = attach_hover_glow(card)

    assert isinstance(overlay, HoverGlowOverlay)
    assert overlay._highlight_pos is None

    move_event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(15, 20),
        QPointF(15, 20),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    overlay.eventFilter(card, move_event)
    assert overlay._highlight_pos == QPointF(15, 20)

    overlay.eventFilter(card, QEvent(QEvent.Type.Leave))
    assert overlay._highlight_pos is None

    # HoverGlowOverlay installs itself as an event filter on the card AND
    # every descendant it found at construction time -- left to ordinary
    # Python GC, a leftover cross-widget filter registration can still fire
    # during later interpreter/test-session teardown, once this function's
    # own local variables (and their __dict__ attributes) are already gone,
    # producing a spurious "no attribute '_card'" error from Qt's callback.
    # Deleting the whole tree synchronously here avoids that.
    shiboken6.delete(card)


def test_hover_glow_does_not_flicker_off_moving_between_child_widgets():
    # Qt sends Leave to whichever child the cursor moves off of even when
    # the cursor is still over the card overall (e.g. crossing from one
    # icon button to the label beside it) -- the hover-depth counter exists
    # specifically so that transition doesn't clear the glow.
    from PySide6.QtWidgets import QLabel

    card = QWidget()
    child_a = QLabel(card)
    child_b = QLabel(card)
    overlay = attach_hover_glow(card)

    # card/overlay are never .show()n here, so isVisible() (whole ancestor
    # chain) would always read False -- isVisibleTo(card) is the correct
    # check, same fix already established elsewhere in this codebase.
    overlay.eventFilter(child_a, QEvent(QEvent.Type.Enter))
    assert overlay.isVisibleTo(card)

    overlay.eventFilter(child_b, QEvent(QEvent.Type.Enter))  # entered B first
    overlay.eventFilter(child_a, QEvent(QEvent.Type.Leave))  # then left A
    assert overlay.isVisibleTo(card)  # still hovering the card via B

    overlay.eventFilter(child_b, QEvent(QEvent.Type.Leave))
    assert not overlay.isVisibleTo(card)

    shiboken6.delete(card)  # see teardown note in the test above


def test_hover_glow_resizes_with_card():
    card = QWidget()
    card.resize(200, 100)
    overlay = attach_hover_glow(card)

    resize_event = QResizeEvent(QSize(300, 150), QSize(200, 100))
    card.resize(300, 150)
    overlay.eventFilter(card, resize_event)

    assert overlay.geometry() == card.rect()

    shiboken6.delete(card)  # see teardown note in the first hover test above


def test_discovery_sweep_start_stop_toggles_active_state():
    container = QWidget()
    sweep = attach_discovery_sweep(container)

    assert isinstance(sweep, SweepOverlay)
    assert not sweep.is_active

    sweep.start()
    assert sweep.is_active

    sweep.stop()
    assert not sweep.is_active
