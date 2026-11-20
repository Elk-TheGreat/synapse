"""The interactive canvas view: pan, zoom, wiring and drag & drop."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsView

from ...typesystem import is_compatible
from ..theme import get_theme
from .edge_item import EdgeItem
from .node_item import NodeItem, PortItem
from .scene import MIME_NODE, GraphScene

MIN_ZOOM = 0.15
MAX_ZOOM = 3.0


class _PreviewEdge(QGraphicsPathItem):
    def __init__(self) -> None:
        super().__init__()
        self.setZValue(20)
        self.setPen(QPen(QColor("#fbbf24"), 2, Qt.DashLine))
        self.setBrush(Qt.NoBrush)


class GraphView(QGraphicsView):
    zoom_changed = Signal(float)
    node_double_clicked = Signal(str)

    def __init__(self, scene: GraphScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.graph_scene = scene
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._panning = False
        self._space = False
        self._pan_origin = QPoint()
        self._wire_source: PortItem | None = None
        self._wire_preview: _PreviewEdge | None = None
        self._zoom = 1.0
        self.setSceneRect(-20000, -20000, 40000, 40000)

    # -- zoom -----------------------------------------------------------
    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            return
        self.zoom_by(1.0015 ** delta, event.position().toPoint())
        event.accept()

    def zoom_by(self, factor: float, anchor: QPoint | None = None) -> None:
        target = self._zoom * factor
        if target < MIN_ZOOM or target > MAX_ZOOM:
            return
        self._zoom = target
        if anchor is not None:
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale(factor, factor)
        self.zoom_changed.emit(self._zoom)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom = 1.0
        self.zoom_changed.emit(self._zoom)

    def zoom_to_fit(self) -> None:
        items_rect = self.graph_scene.itemsBoundingRect()
        if items_rect.isEmpty():
            self.reset_zoom()
            return
        items_rect = items_rect.adjusted(-60, -60, 60, 60)
        self.fitInView(items_rect, Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    def zoom_to_selection(self) -> None:
        rect = QRectF()
        for item in self.graph_scene.selectedItems():
            rect = rect.united(item.sceneBoundingRect())
        if rect.isEmpty():
            self.zoom_to_fit()
            return
        self.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.zoom_changed.emit(self._zoom)

    # -- pan ------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space):
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            port = self._port_at(event.position().toPoint())
            if port is not None:
                self._start_wire(port, event.position().toPoint())
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning:
            delta = event.position().toPoint() - self._pan_origin
            self._pan_origin = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if self._wire_source is not None and self._wire_preview is not None:
            start = self._wire_source.centre_scene()
            end = self.mapToScene(event.position().toPoint())
            self._update_preview(start, end)
            event.accept()
            return
        port = self._port_at(event.position().toPoint())
        if port is not None:
            self.viewport().setCursor(Qt.CrossCursor)
        else:
            self.viewport().setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        if self._wire_source is not None:
            source = self._wire_source
            target = self._port_at(event.position().toPoint(), exclude=source)
            self._finish_wire()
            if target is not None:
                self._connect_ports(source, target)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            event.accept()
            return
        if event.key() == Qt.Key_Delete or event.key() == Qt.Key_Backspace:
            self.graph_scene.delete_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    # -- wiring ---------------------------------------------------------
    def _port_at(self, view_pos: QPoint, exclude: PortItem | None = None) -> PortItem | None:
        scene_pos = self.mapToScene(view_pos)
        for item in self.graph_scene.items(scene_pos):
            if isinstance(item, PortItem) and item is not exclude:
                if item.boundingRect().contains(item.mapFromScene(scene_pos)):
                    return item
        return None

    def _start_wire(self, port: PortItem, view_pos: QPoint) -> None:
        self._wire_source = port
        self._wire_preview = _PreviewEdge()
        self.graph_scene.addItem(self._wire_preview)
        self._update_preview(port.centre_scene(), self.mapToScene(view_pos))

    def _update_preview(self, start: QPointF, end: QPointF) -> None:
        if self._wire_preview is None:
            return
        dx = max(40.0, abs(end.x() - start.x()) * 0.5)
        path = QPainterPath(start)
        path.cubicTo(QPointF(start.x() + dx, start.y()), QPointF(end.x() - dx, end.y()), end)
        self._wire_preview.setPath(path)

    def _finish_wire(self) -> None:
        if self._wire_preview is not None:
            self.graph_scene.removeItem(self._wire_preview)
        self._wire_source = None
        self._wire_preview = None

    def _connect_ports(self, first: PortItem, second: PortItem) -> None:
        if first.is_output == second.is_output:
            self.graph_scene.message.emit("Connect an output port to an input port")
            return
        output_port, input_port = (first, second) if first.is_output else (second, first)
        output_node = output_port.node
        input_node = input_port.node
        if output_node is input_node:
            self.graph_scene.message.emit("A node cannot be connected to itself")
            return
        out_spec = next(
            (p for p in output_node.definition.outputs if p.name == output_port.port_name), None
        ) if output_node.definition else None
        in_spec = next(
            (p for p in input_node.definition.inputs if p.name == input_port.port_name), None
        ) if input_node.definition else None
        if out_spec is not None and in_spec is not None and not is_compatible(out_spec.spec, in_spec.spec):
            self.graph_scene.message.emit(
                f"Incompatible types: {out_spec.spec} → {in_spec.spec}"
            )
            return
        self.graph_scene.connect_ports(output_node, output_port.port_name, input_node, input_port.port_name)

    # -- drag & drop ----------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(MIME_NODE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_NODE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat(MIME_NODE):
            type_id = bytes(event.mimeData().data(MIME_NODE)).decode("utf-8")
            pos = self.mapToScene(event.position().toPoint())
            self.graph_scene.add_node(type_id, pos)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # -- context & double click ----------------------------------------
    def contextMenuEvent(self, event) -> None:
        scene_pos = self.mapToScene(event.pos())
        menu = self.graph_scene.context_menu(scene_pos)
        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            item = self.graph_scene.itemAt(self.mapToScene(event.position().toPoint()), self.transform())
            while item is not None and not isinstance(item, NodeItem):
                item = item.parentItem()
            if isinstance(item, NodeItem):
                self.node_double_clicked.emit(item.node.id)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def zoom_level(self) -> float:
        return self._zoom

