"""Node and port graphics items."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject, QStyleOptionGraphicsItem, QWidget

from ...debugger.values import value_preview
from ...graph.model import NodeInstance
from ...typesystem import DataType
from ..theme import get_theme

PORT_RADIUS = 5.5
HEADER_HEIGHT = 34.0
ROW_HEIGHT = 22.0
PADDING_BOTTOM = 12.0


class PortItem(QGraphicsItem):
    """A connection point on a node."""

    def __init__(self, node: "NodeItem", name: str, data_type, *, output: bool, index: int) -> None:
        super().__init__(node)
        self.node = node
        self.port_name = name
        self.data_type = data_type
        self.is_output = output
        self.index = index
        self.hovered = False
        self.connected = False
        self.setAcceptHoverEvents(True)
        self.setZValue(3)
        self.setCursor(Qt.CrossCursor)
        self.setToolTip(f"{name}: {DataType(data_type).value if isinstance(data_type, str) else getattr(data_type, 'value', data_type)}")

    def boundingRect(self) -> QRectF:
        r = PORT_RADIUS + 4
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        theme = get_theme(self.node.theme_name)
        colour = QColor(self.node.type_colour)
        if self.connected:
            brush = QBrush(colour)
        else:
            brush = QBrush(QColor(theme.canvas))
        pen = QPen(colour if not self.hovered else QColor("#ffffff"), 2.4 if self.hovered else 1.6)
        painter.setBrush(brush)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(0, 0), PORT_RADIUS, PORT_RADIUS)

    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def centre_scene(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class NodeItem(QGraphicsObject):
    """Visual representation of one :class:`NodeInstance`."""

    def __init__(self, node: NodeInstance, definition, *, theme_name: str = "dark") -> None:
        super().__init__()
        self.node = node
        self.definition = definition
        self.theme_name = theme_name
        self.width = float(node.width)
        self.height = float(node.height)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
            | QGraphicsItem.ItemSendsScenePositionChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setPos(node.x, node.y)
        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {}
        self.breakpoint = False
        self.run_status = ""
        self.run_values: dict[str, str] = {}
        self._resizing = False
        self._resize_origin = QPointF()
        self._resize_start = (0.0, 0.0)
        self._drag_start = QPointF()
        self._drag_origin = QPointF()
        self.hovered = False
        self._build_ports()
        self.layout_ports()

    # -- geometry -------------------------------------------------------
    def _build_ports(self) -> None:
        if self.definition is None:
            return
        for index, spec in enumerate(self.definition.inputs):
            port = PortItem(self, spec.name, spec.data_type, output=False, index=index)
            self.input_ports[spec.name] = port
        for index, spec in enumerate(self.definition.outputs):
            port = PortItem(self, spec.name, spec.data_type, output=True, index=index)
            self.output_ports[spec.name] = port

    def _rows(self) -> int:
        if self.definition is None:
            return 1
        return max(len(self.definition.inputs), len(self.definition.outputs), 1)

    def _port_rows_height(self) -> float:
        return max(1, self._rows()) * ROW_HEIGHT

    def _params_height(self) -> float:
        if self.definition is None:
            return 0.0
        summary = self.param_summary_lines(2)
        return len(summary) * 15.0 + (6.0 if summary else 0.0)

    def minimum_height(self) -> float:
        return HEADER_HEIGHT + self._port_rows_height() + self._params_height() + PADDING_BOTTOM

    def layout_ports(self) -> None:
        top = HEADER_HEIGHT + 10 + ROW_HEIGHT / 2
        for index, port in enumerate(self.input_ports.values()):
            port.setPos(0, top + index * ROW_HEIGHT)
            port.index = index
        for index, port in enumerate(self.output_ports.values()):
            port.setPos(self.width, top + index * ROW_HEIGHT)
            port.index = index

    def port_position(self, name: str, output: bool) -> QPointF | None:
        port = (self.output_ports if output else self.input_ports).get(name)
        return port.centre_scene() if port else None

    def boundingRect(self) -> QRectF:
        return QRectF(-1, -1, self.width + 2, self.height + 2)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width, self.height), 9, 9)
        return path

    def resize_handle_rect(self) -> QRectF:
        return QRectF(self.width - 14, self.height - 14, 14, 14)

    @property
    def type_colour(self) -> str:
        from ..theme import category_color

        if self.definition is None:
            return "#7c8aa0"
        return category_color(self.definition.category)

    @property
    def title(self) -> str:
        if self.node.label:
            return self.node.label
        if self.definition is None:
            return self.node.type
        return self.definition.name

    def param_summary_lines(self, limit: int = 2) -> list[str]:
        if self.definition is None:
            return []
        lines = []
        for spec in self.definition.params.values():
            value = self.node.params.get(spec.name, spec.default)
            if value in (None, "", {}, []):
                continue
            text = str(value).replace("\n", " ")
            if len(text) > 28:
                text = text[:27] + "…"
            lines.append(f"{spec.label}: {text}")
            if len(lines) >= limit:
                break
        return lines

    # -- painting -------------------------------------------------------
    def paint(self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        theme = get_theme(self.theme_name)
        rect = QRectF(0, 0, self.width, self.height)
        painter.setRenderHint(QPainter.Antialiasing, True)

        body = QColor(theme.surface)
        if self.node.disabled:
            body.setAlpha(150)
        painter.setBrush(QBrush(body))
        border = QColor(theme.border)
        if self.isSelected():
            border = QColor(theme_safe_accent())
        elif self.hovered:
            border = QColor("#3a4757")
        painter.setPen(QPen(border, 2.0 if self.isSelected() else 1.0))
        painter.drawRoundedRect(rect, 9, 9)

        # header strip
        path = QPainterPath()
        path.addRoundedRect(rect, 9, 9)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(QRectF(0, 0, self.width, HEADER_HEIGHT), QColor(self.type_colour).darker(360))
        painter.fillRect(QRectF(0, 0, 4, HEADER_HEIGHT), QColor(self.type_colour))
        painter.restore()

        painter.setPen(QColor(theme.text))
        font = QFont()
        font.setPointSizeF(9.5)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.drawText(
            QRectF(12, 4, self.width - 24, 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.title,
        )
        font.setPointSizeF(7.5)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        painter.setPen(QColor(theme.muted))
        category = self.definition.category if self.definition else "Unknown"
        painter.drawText(
            QRectF(12, 18, self.width - 24, 13),
            Qt.AlignLeft | Qt.AlignVCenter,
            category,
        )

        if self.breakpoint:
            painter.setBrush(QColor("#ef4444"))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(self.width - 12, 12), 4, 4)

        font.setPointSizeF(8.0)
        painter.setFont(font)
        for port in self.input_ports.values():
            self._draw_port_label(painter, port, theme, left=True)
        for port in self.output_ports.values():
            self._draw_port_label(painter, port, theme, left=False)

        # parameter summary
        lines = self.param_summary_lines(3)
        if lines:
            font.setPointSizeF(7.6)
            painter.setFont(font)
            painter.setPen(QColor(theme.muted))
            top = HEADER_HEIGHT + self._port_rows_height() + 4
            for index, line in enumerate(lines):
                painter.drawText(
                    QRectF(12, top + index * 15, self.width - 24, 14),
                    Qt.AlignLeft | Qt.AlignVCenter,
                    line,
                )

        # execution status
        if self.run_status:
            colour = {
                "ok": QColor("#34d399"),
                "error": QColor("#f87171"),
                "skipped": QColor("#94a3b8"),
                "running": QColor("#fbbf24"),
                "cached": QColor("#38bdf8"),
            }.get(self.run_status, QColor("#94a3b8"))
            painter.setPen(Qt.NoPen)
            painter.setBrush(colour)
            painter.drawRoundedRect(QRectF(0, self.height - 3, self.width, 3), 2, 2)

        # resize grip
        painter.setPen(QPen(QColor(theme.border), 1.2))
        for offset in (0, 4, 8):
            painter.drawLine(
                QPointF(self.width - 4 - offset, self.height - 4),
                QPointF(self.width - 4, self.height - 4 - offset),
            )

    def _draw_port_label(self, painter: QPainter, port: PortItem, theme, *, left: bool) -> None:
        painter.setPen(QColor(theme.text if port.connected else theme.muted))
        rect = (
            QRectF(9, port.pos().y() - 8, self.width / 2 - 12, 16)
            if left
            else QRectF(self.width / 2 + 2, port.pos().y() - 8, self.width / 2 - 12, 16)
        )
        alignment = (Qt.AlignLeft if left else Qt.AlignRight) | Qt.AlignVCenter
        painter.drawText(rect, alignment, port.port_name)

    # -- interaction ----------------------------------------------------
    def hoverEnterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

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
        self._drag_start = event.scenePos()
        self._drag_origin = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            delta = event.scenePos() - self._resize_origin
            self.prepareGeometryChange()
            self.width = max(150.0, self._resize_start[0] + delta.x())
            self.height = max(self.minimum_height(), self._resize_start[1] + delta.y())
            self.layout_ports()
            self.update()
            self.notify_edges()
            return
        super().mouseMoveEvent(event)
        self.notify_edges()

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if self._resizing:
            self._resizing = False
            self.width = round(self.width, 1)
            self.height = round(self.height, 1)
            if scene is not None and hasattr(scene, "commit_edit"):
                scene.commit_edit("Resize node")
            return
        moved = self.pos() != self._drag_origin
        if moved:
            self.setPos(round(self.pos().x() / 8) * 8, round(self.pos().y() / 8) * 8)
            if scene is not None and hasattr(scene, "commit_edit"):
                scene.commit_edit("Move node")
        elif scene is not None and hasattr(scene, "discard_edit"):
            scene.discard_edit()
        self.notify_edges()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.notify_edges()
        return super().itemChange(change, value)

    def notify_edges(self) -> None:
        scene = self.scene()
        if scene is not None and hasattr(scene, "update_edges_for"):
            scene.update_edges_for(self.node.id)

    # -- model sync -----------------------------------------------------
    def sync_to_model(self) -> None:
        self.node.x = float(self.pos().x())
        self.node.y = float(self.pos().y())
        self.node.width = float(self.width)
        self.node.height = float(self.height)

    def set_run_status(self, status: str, outputs: dict | None = None) -> None:
        self.run_status = status
        self.run_values = {}
        for name, value in (outputs or {}).items():
            self.run_values[name] = value_preview(value)
        self.update()

    def set_breakpoint(self, active: bool) -> None:
        self.breakpoint = active
        self.update()

    def clear_run_state(self) -> None:
        self.run_status = ""
        self.run_values = {}
        self.update()


def theme_safe_accent() -> str:
    from ..theme import active_accent

    return active_accent()
