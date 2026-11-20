"""Small navigator that shows the whole graph and the current viewport."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import category_color, get_theme
from .scene import GraphScene


class MinimapWidget(QWidget):
    def __init__(self, scene: GraphScene, view, parent=None) -> None:
        super().__init__(parent)
        self.scene = scene
        self.view = view
        self.setFixedHeight(148)
        self.setMinimumWidth(160)
        self.setCursor(Qt.PointingHandCursor)
        self._drag = False

    def _content_rect(self) -> QRectF:
        rect = self.scene.itemsBoundingRect()
        if rect.isEmpty():
            rect = QRectF(-500, -300, 1000, 600)
        return rect.adjusted(-80, -80, 80, 80)

    def _transform(self) -> tuple[float, QPointF]:
        content = self._content_rect()
        scale = min((self.width() - 12) / content.width(), (self.height() - 12) / content.height())
        offset = QPointF(
            6 + (self.width() - 12 - content.width() * scale) / 2 - content.x() * scale,
            6 + (self.height() - 12 - content.height() * scale) / 2 - content.y() * scale,
        )
        return scale, offset

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        theme = get_theme(self.scene.theme_name)
        painter.fillRect(self.rect(), QColor(theme.surface_alt))
        painter.setPen(QPen(QColor(theme.border), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        scale, offset = self._transform()
        for item in self.scene.node_items.values():
            rect = item.sceneBoundingRect()
            painter.setBrush(QColor(category_color(item.definition.category) if item.definition else "#7c8aa0"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(
                QRectF(
                    offset.x() + rect.x() * scale,
                    offset.y() + rect.y() * scale,
                    max(2.0, rect.width() * scale),
                    max(2.0, rect.height() * scale),
                ),
                1.5,
                1.5,
            )
        viewport = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        rect = QRectF(
            offset.x() + viewport.x() * scale,
            offset.y() + viewport.y() * scale,
            viewport.width() * scale,
            viewport.height() * scale,
        )
        painter.setBrush(QColor(90, 200, 250, 24))
        painter.setPen(QPen(QColor("#5ac8fa"), 1.2))
        painter.drawRect(rect)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag = True
            self._centre_on(event.position())

    def mouseMoveEvent(self, event) -> None:
        if self._drag:
            self._centre_on(event.position())

    def mouseReleaseEvent(self, event) -> None:
        self._drag = False

    def _centre_on(self, pos: QPointF) -> None:
        scale, offset = self._transform()
        scene_point = QPointF((pos.x() - offset.x()) / scale, (pos.y() - offset.y()) / scale)
        self.view.centerOn(scene_point)
        self.update()
