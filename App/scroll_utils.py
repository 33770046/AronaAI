import weakref

from PySide6.QtWidgets import QAbstractScrollArea, QScroller, QScrollerProperties


_APPLIED = weakref.WeakSet()


def enable_touch_scroll(scroll_area: QAbstractScrollArea):
    """Enable native touch-pan scrolling on a scroll area.

    Uses Qt's built-in QScroller with the TouchGesture, so a finger drag on a
    touchscreen pans the viewport (with kinetic inertia) while plain mouse
    clicks and wheel scrolling keep working normally. Idempotent per scroll
    area.
    """
    if not isinstance(scroll_area, QAbstractScrollArea):
        return
    viewport = scroll_area.viewport()
    if viewport in _APPLIED:
        return
    _APPLIED.add(viewport)

    QScroller.grabGesture(viewport, QScroller.TouchGesture)

    props = QScrollerProperties()
    props.setScrollMetric(QScrollerProperties.DragStartDistance, 0.03)
    props.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.25)
    props.setScrollMetric(QScrollerProperties.MaximumVelocity, 1.5)
    QScroller.scroller(viewport).setScrollerProperties(props)
