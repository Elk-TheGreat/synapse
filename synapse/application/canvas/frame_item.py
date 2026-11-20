"""A group or annotation frame drawn behind nodes."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget

from ...graph.model import Frame
from ..theme import get_theme


class FrameItem(QGraphicsObject):
    def __init__(self, frame: Frame, *, theme_name: str = "dark") -> None:
        super().__init__()
        self.frame = frame
        self.theme_name = theme_name
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(-5)
        self.setPos(frame.x, frame.y)
        self.width = float(frame.width)
        self.height = float(frame.height)
        self._drag_origin = QPointF()
        self._resizing = False
        self._resize_origin = QPointF()
        self._resize_start = (0.0, 0.0)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)

    def resize_handle_rect(self) -> QRectF:
        return QRectF(self.width - 14, self.height - 14, 14, 14)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        theme = get_theme(self.theme_name)
        colour = QColor(self.frame.color)
        painter.setRenderHint(QPainter.Antialiasing, True)
        fill = QColor(colour)
        fill.setAlpha(18 if theme.name == "dark" else 12)
        painter.setBrush(QBrush(fill))
        border = QColor(colour)
        border.setAlpha(150 if not self.isSelected() else 230)
        painter.setPen(QPen(border, 1.4, Qt.DashLine if self.frame.kind == "annotation" else Qt.SolidLine))
        painter.drawRoundedRect(self.boundingRect(), 8, 8)
        font = QFont()
        font.setPointSizeF(9)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(colour))
        painter.drawText(QRectF(12, 6, self.width - 24, 18), Qt.AlignLeft | Qt.AlignVCenter, self.frame.title)
        if self.isSelected():
            painter.setPen(QPen(QColor(theme.muted), 1))
            for offset in (0, 4, 8):
                painter.drawLine(
                    QPointF(self.width - 4 - offset, self.height - 4),
                    QPointF(self.width - 4, self.height - 4 - offset),
                )

    def mousePressEvent(self, event) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "begin_edit"):
            scene.begin_edit()
        if event.button() == Qt.LeftButton and self.resize_handle_rect().contains(event.pos()):
            self._resizing = True
            self._resize_origin = event.scenePos()
            self._resize_start = (self.width, self.height)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_origin
            self.prepareGeometryChange()
            self.width = max(120.0, self._resize_start[0] + delta.x())
            self.height = max(80.0, self._resize_start[1] + delta.y())
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if self._resizing:
            self._resizing = False
            if scene is not None and hasattr(scene, "commit_edit"):
                scene.commit_edit("Resize frame")
        elif scene is not None and hasattr(scene, "commit_edit"):
            scene.commit_edit("Move frame")

    def sync_to_model(self) -> None:
        self.frame.x = float(self.pos().x())
        self.frame.y = float(self.pos().y())
        self.frame.width = float(self.width)
        self.frame.height = float(self.height)

    def contains_node(self, node_item) -> bool:
        centre = node_item.mapToScene(node_item.boundingRect().center())
        return self.boundingRect().contains(self.mapFromScene(centre))
