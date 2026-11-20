"""Curved connection wires between node ports."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QStyleOptionGraphicsItem, QWidget

from ...graph.model import Edge
from ..theme import get_theme


class EdgeItem(QGraphicsPathItem):
    """A bezier wire from an output port to an input port."""

    def __init__(self, edge: Edge, source: "NodeItem", target: "NodeItem", *, theme_name: str = "dark") -> None:
        super().__init__()
        self.edge = edge
        self.source = source
        self.target = target
        self.theme_name = theme_name
        self.setZValue(0)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.hovered = False
        self.run_status = ""
        self.value_text = ""
        self.setToolTip(f"{edge.source_port} → {edge.target_port}")
        self.update_path()

    # -- geometry -------------------------------------------------------
    def _endpoints(self) -> tuple[QPointF, QPointF]:
        start = self.source.port_position(self.edge.source_port, True)
        end = self.target.port_position(self.edge.target_port, False)
        if start is None:
            start = self.source.scenePos() + QPointF(self.source.width, 40)
        if end is None:
            end = self.target.scenePos() + QPointF(0, 40)
        return start, end

    def update_path(self) -> None:
        start, end = self._endpoints()
        dx = max(50.0, abs(end.x() - start.x()) * 0.5)
        path = QPainterPath(start)
        path.cubicTo(
            QPointF(start.x() + dx, start.y()),
            QPointF(end.x() - dx, end.y()),
            end,
        )
        self.setPath(path)
        self.prepareGeometryChange()

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(-6, -14, 6, 14)

    # -- painting -------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        theme = get_theme(self.theme_name)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self.run_status == "active":
            colour = QColor("#fbbf24")
            width = 3.0
        elif self.run_status == "error":
            colour = QColor("#f87171")
            width = 2.6
        elif self.run_status == "ok":
            colour = QColor("#34d399")
            width = 2.2
        elif self.isSelected():
            colour = QColor("#ffffff")
            width = 2.4
        elif self.hovered:
            colour = QColor(theme.muted)
            width = 2.6
        else:
            colour = QColor("#46566a")
            width = 1.8
        pen = QPen(colour, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        if self.run_status in ("active", "ok"):
            pen.setStyle(Qt.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.path())

        if self.value_text:
            start, end = self._endpoints()
            mid = self.path().pointAtPercent(0.5)
            font = QFont()
            font.setPointSizeF(7.4)
            painter.setFont(font)
            metrics = painter.fontMetrics()
            width_px = metrics.horizontalAdvance(self.value_text) + 12
            rect = QRectF(mid.x() - width_px / 2, mid.y() - 18, width_px, 16)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(theme.surface)))
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(theme.text))
            painter.drawText(rect, Qt.AlignCenter, self.value_text)

    def shape(self) -> QPainterPath:
        stroker = QPainterPath(self.path())
        from PySide6.QtGui import QPainterPathStroker

        s = QPainterPathStroker()
        s.setWidth(10)
        return s.createStroke(stroker)

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def set_run_state(self, status: str, value_text: str = "") -> None:
        self.run_status = status
        self.value_text = value_text
        self.update()

    def clear_run_state(self) -> None:
        self.run_status = ""
        self.value_text = ""
        self.update()
