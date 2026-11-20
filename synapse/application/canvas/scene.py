"""The graph scene: node/edge/frame items, editing and undo."""

from __future__ import annotations

import json
import uuid
from typing import Iterable

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QUndoCommand, QUndoStack
from PySide6.QtWidgets import QApplication, QGraphicsScene, QMenu

from ...debugger.values import value_preview
from ...graph.model import Frame, Graph, GraphError, new_id
from ..theme import get_theme
from .edge_item import EdgeItem
from .frame_item import FrameItem
from .node_item import NodeItem, PortItem

MIME_NODE = "application/x-synapse-node"


class _SnapshotCommand(QUndoCommand):
    """Undo by restoring a whole-graph JSON snapshot.

    Graphs are small enough (a few hundred nodes at most) that snapshots are
    cheap, and they make every edit - moves, parameter changes, wiring,
    grouping - undoable through one code path instead of a command per action.
    """

    def __init__(self, scene: "GraphScene", before: dict, after: dict, text: str) -> None:
        super().__init__(text)
        self.scene = scene
        self.before = before
        self.after = after
        self._skip_first_redo = True

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self.scene.apply_snapshot(self.after, self.text())

    def undo(self) -> None:
        self.scene.apply_snapshot(self.before, self.text())


class GraphScene(QGraphicsScene):
    changed = Signal()
    selection_changed = Signal()
    message = Signal(str)
    graph_replaced = Signal(object)
    request_convert_to_function = Signal(list)
    request_add_function = Signal()

    def __init__(self, graph: Graph, *, theme_name: str = "dark", parent=None) -> None:
        super().__init__(parent)
        self.graph = graph
        self.theme_name = theme_name
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: dict[str, EdgeItem] = {}
        self.frame_items: dict[str, FrameItem] = {}
        self.breakpoints: set[str] = set()
        self.undo_stack = QUndoStack(self)
        self._before: dict | None = None
        self._rebuilding = False
        self.setBackgroundBrush(QColor(get_theme(theme_name).canvas))
        self.selectionChanged.connect(self._emit_selection_changed)
        self.rebuild()

    # -- construction ---------------------------------------------------
    def _emit_selection_changed(self) -> None:
        self.selection_changed.emit()

    @property
    def registry(self):
        return self.graph.registry

    def _definition(self, type_id: str):
        definition = self.registry.get(type_id)
        return definition

    def rebuild(self) -> None:
        selected = {item.node.id for item in self.selectedItems() if isinstance(item, NodeItem)}
        self._rebuilding = True
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        self.frame_items.clear()

        for frame in self.graph.frames:
            item = FrameItem(frame, theme_name=self.theme_name)
            self.addItem(item)
            self.frame_items[frame.id] = item

        for node in self.graph.nodes.values():
            definition = self._definition(node.type)
            item = NodeItem(node, definition, theme_name=self.theme_name)
            minimum = item.minimum_height()
            if node.height < minimum:
                node.height = minimum
                item.height = minimum
                item.layout_ports()
            self.addItem(item)
            self.node_items[node.id] = item
            if node.id in self.breakpoints:
                item.set_breakpoint(True)

        for edge in self.graph.edges:
            source = self.node_items.get(edge.source)
            target = self.node_items.get(edge.target)
            if source is None or target is None:
                continue
            edge_item = EdgeItem(edge, source, target, theme_name=self.theme_name)
            self.addItem(edge_item)
            self.edge_items[edge.id] = edge_item
            source_port = source.output_ports.get(edge.source_port)
            target_port = target.input_ports.get(edge.target_port)
            if source_port:
                source_port.connected = True
            if target_port:
                target_port.connected = True

        for node_id in selected:
            item = self.node_items.get(node_id)
            if item is not None:
                item.setSelected(True)
        self._rebuilding = False
        self.update()

    def refresh_node(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is None:
            return
        definition = self._definition(item.node.type)
        self.removeItem(item)
        new_item = NodeItem(item.node, definition, theme_name=self.theme_name)
        self.addItem(new_item)
        self.node_items[node_id] = new_item
        for port in new_item.input_ports.values():
            port.connected = any(
                e.target == node_id and e.target_port == port.port_name for e in self.graph.edges
            )
        for port in new_item.output_ports.values():
            port.connected = any(
                e.source == node_id and e.source_port == port.port_name for e in self.graph.edges
            )
        for edge_item in self.edge_items.values():
            edge_item.update_path()
        new_item.setSelected(True)

    # -- undo -----------------------------------------------------------
    def begin_edit(self) -> None:
        if self._before is None:
            self._before = self.graph.to_dict()

    def commit_edit(self, text: str) -> None:
        before = self._before
        self._before = None
        if before is None:
            return
        self._sync_positions()
        after = self.graph.to_dict()
        if before == after:
            return
        self.undo_stack.push(_SnapshotCommand(self, before, after, text))
        self.changed.emit()

    def discard_edit(self) -> None:
        self._before = None

    def _sync_positions(self) -> None:
        for item in self.node_items.values():
            item.sync_to_model()
        for frame in self.frame_items.values():
            frame.sync_to_model()

    def apply_snapshot(self, snapshot: dict, text: str) -> None:
        graph = Graph.from_dict(snapshot, registry=self.registry)
        self.graph = graph
        self.rebuild()
        self.graph_replaced.emit(graph)
        self.changed.emit()
        self.message.emit(f"{text}")

    def undo(self) -> None:
        self.undo_stack.undo()

    def redo(self) -> None:
        self.undo_stack.redo()

    # -- editing --------------------------------------------------------
    def add_node(self, type_id: str, position: QPointF | tuple[float, float], params: dict | None = None) -> NodeItem | None:
        pos = (position.x(), position.y()) if isinstance(position, QPointF) else position
        definition = self.registry.get(type_id)
        if definition is None:
            self.message.emit(f"Unknown node type '{type_id}'")
            return None
        self.begin_edit()
        try:
            node = self.graph.add_node(type_id, params, pos)
        except GraphError as exc:
            self.discard_edit()
            self.message.emit(str(exc))
            return None
        self.rebuild()
        self.commit_edit(f"Add {definition.name}")
        item = self.node_items.get(node.id)
        if item is not None:
            self.clearSelection()
            item.setSelected(True)
        return item

    def delete_selection(self) -> None:
        nodes = [item.node.id for item in self.selectedItems() if isinstance(item, NodeItem)]
        edge_ids = [item.edge.id for item in self.selectedItems() if isinstance(item, EdgeItem)]
        frame_ids = [item.frame.id for item in self.selectedItems() if isinstance(item, FrameItem)]
        if not (nodes or edge_ids or frame_ids):
            return
        self.begin_edit()
        if nodes:
            self.graph.remove_nodes(nodes)
            for node_id in nodes:
                self.breakpoints.discard(node_id)
        for edge_id in edge_ids:
            self.graph.disconnect(edge_id)
        if frame_ids:
            self.graph.frames = [f for f in self.graph.frames if f.id not in frame_ids]
        self.rebuild()
        self.commit_edit("Delete selection")

    def duplicate_selection(self) -> None:
        nodes = [item.node for item in self.selectedItems() if isinstance(item, NodeItem)]
        if not nodes:
            return
        self.begin_edit()
        id_map = {}
        for node in nodes:
            new = self.graph.add_node(
                node.type,
                dict(node.params),
                (node.x + 32, node.y + 32),
                label=node.label,
            )
            new.width, new.height = node.width, node.height
            id_map[node.id] = new.id
        for edge in list(self.graph.edges):
            if edge.source in id_map and edge.target in id_map:
                try:
                    self.graph.connect(
                        id_map[edge.source], edge.source_port, id_map[edge.target], edge.target_port
                    )
                except GraphError:
                    pass
        self.rebuild()
        self.clearSelection()
        for node_id in id_map.values():
            item = self.node_items.get(node_id)
            if item:
                item.setSelected(True)
        self.commit_edit(f"Duplicate {len(nodes)} node(s)")

    def connect_ports(self, source_item: NodeItem, source_port: str, target_item: NodeItem, target_port: str) -> bool:
        self.begin_edit()
        try:
            self.graph.connect(source_item.node.id, source_port, target_item.node.id, target_port, replace=True)
        except GraphError as exc:
            self.discard_edit()
            self.message.emit(f"Cannot connect: {exc}")
            return False
        self.rebuild()
        self.commit_edit("Connect nodes")
        return True

    def disconnect_edge(self, edge_id: str) -> None:
        self.begin_edit()
        if self.graph.disconnect(edge_id):
            self.rebuild()
            self.commit_edit("Disconnect")
        else:
            self.discard_edit()

    def set_param(self, node_id: str, name: str, value, *, text: str = "Change parameter", rebuild: bool = False) -> None:
        item = self.node_items.get(node_id)
        if item is None:
            return
        if item.node.params.get(name) == value:
            return
        self.begin_edit()
        item.node.params[name] = value
        if rebuild:
            self.refresh_node(node_id)
        else:
            item.update()
        self.commit_edit(text)

    def set_node_field(self, node_id: str, field: str, value, text: str = "Edit node") -> None:
        item = self.node_items.get(node_id)
        if item is None or getattr(item.node, field, None) == value:
            return
        self.begin_edit()
        setattr(item.node, field, value)
        item.update()
        self.commit_edit(text)

    def set_node_flag(self, node_id: str, flag: str, value) -> None:
        item = self.node_items.get(node_id)
        if item is None or getattr(item.node, flag) == value:
            return
        self.begin_edit()
        setattr(item.node, flag, value)
        item.update()
        self.commit_edit("Toggle node state")

    def toggle_breakpoint(self, node_id: str) -> bool:
        item = self.node_items.get(node_id)
        if item is None:
            return False
        if node_id in self.breakpoints:
            self.breakpoints.discard(node_id)
            item.set_breakpoint(False)
            return False
        self.breakpoints.add(node_id)
        item.set_breakpoint(True)
        return True

    # -- grouping -------------------------------------------------------
    def group_selection(self, *, annotation: bool = False) -> None:
        items = [item for item in self.selectedItems() if isinstance(item, NodeItem)]
        self.begin_edit()
        if items:
            rect = items[0].sceneBoundingRect()
            for item in items[1:]:
                rect = rect.united(item.sceneBoundingRect())
            rect = rect.adjusted(-28, -46, 28, 24)
        else:
            rect = QRectF(0, 0, 360, 260)
        frame = Frame(
            id=new_id("f_"),
            title="Annotation" if annotation else "Group",
            x=rect.x(),
            y=rect.y(),
            width=max(160.0, rect.width()),
            height=max(100.0, rect.height()),
            color="#f59e0b" if annotation else "#38bdf8",
            node_ids=[item.node.id for item in items],
            kind="annotation" if annotation else "frame",
        )
        self.graph.frames.append(frame)
        self.rebuild()
        self.commit_edit("Add annotation" if annotation else "Group nodes")

    def auto_layout(self) -> None:
        graph = self.graph
        if not graph.nodes:
            return
        indegree = {node_id: 0 for node_id in graph.nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in graph.nodes}
        for edge in graph.edges:
            if edge.source in graph.nodes and edge.target in graph.nodes:
                outgoing[edge.source].append(edge.target)
                indegree[edge.target] += 1
        depth = {node_id: 0 for node_id in graph.nodes}
        queue = [node_id for node_id, deg in indegree.items() if deg == 0]
        order = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for target in outgoing[current]:
                depth[target] = max(depth[target], depth[current] + 1)
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        # nodes on cycles (should not happen) keep depth 0
        columns: dict[int, list[str]] = {}
        for node_id in graph.nodes:
            columns.setdefault(depth[node_id], []).append(node_id)
        self.begin_edit()
        for column, node_ids in columns.items():
            for row, node_id in enumerate(sorted(node_ids)):
                node = graph.nodes[node_id]
                node.x = 80 + column * 290
                node.y = 80 + row * 170
        self.rebuild()
        self.commit_edit("Automatic layout")

    def align_selection(self, mode: str) -> None:
        items = [item for item in self.selectedItems() if isinstance(item, NodeItem)]
        if len(items) < 2:
            return
        self.begin_edit()
        if mode == "left":
            x = min(item.pos().x() for item in items)
            for item in items:
                item.setPos(x, item.pos().y())
        elif mode == "top":
            y = min(item.pos().y() for item in items)
            for item in items:
                item.setPos(item.pos().x(), y)
        elif mode == "hdistribute":
            items.sort(key=lambda i: i.pos().x())
            source = items[0].pos().x()
            step = (items[-1].pos().x() - source) / max(1, len(items) - 1)
            for index, item in enumerate(items):
                item.setPos(source + index * step, item.pos().y())
        elif mode == "vdistribute":
            items.sort(key=lambda i: i.pos().y())
            source = items[0].pos().y()
            step = (items[-1].pos().y() - source) / max(1, len(items) - 1)
            for index, item in enumerate(items):
                item.setPos(item.pos().x(), source + index * step)
        self.commit_edit("Align nodes")

    # -- clipboard ------------------------------------------------------
    def copy_selection(self) -> None:
        nodes = [item.node for item in self.selectedItems() if isinstance(item, NodeItem)]
        if not nodes:
            return
        ids = {node.id for node in nodes}
        payload = {
            "nodes": [node.to_dict() for node in nodes],
            "edges": [
                edge.to_dict()
                for edge in self.graph.edges
                if edge.source in ids and edge.target in ids
            ],
        }
        QApplication.clipboard().setText(json.dumps(payload))
        self.message.emit(f"Copied {len(nodes)} node(s)")

    def paste(self, position: QPointF | None = None) -> None:
        text = QApplication.clipboard().text()
        if not text:
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or "nodes" not in payload:
            return
        nodes = payload.get("nodes") or []
        if not nodes:
            return
        base_x = min(float(n.get("position", [0, 0])[0]) for n in nodes)
        base_y = min(float(n.get("position", [0, 0])[1]) for n in nodes)
        anchor = position or QPointF(base_x + 40, base_y + 40)
        id_map: dict[str, str] = {}
        self.begin_edit()
        for data in nodes:
            type_id = data.get("type")
            if not type_id or self.registry.get(type_id) is None:
                continue
            pos = data.get("position") or [0, 0]
            node = self.graph.add_node(
                type_id,
                dict(data.get("params") or {}),
                (anchor.x() + float(pos[0]) - base_x, anchor.y() + float(pos[1]) - base_y),
                label=data.get("label"),
            )
            size = data.get("size") or [node.width, node.height]
            node.width = max(150.0, float(size[0]))
            node.height = max(60.0, float(size[1]))
            id_map[str(data.get("id"))] = node.id
        for edge in payload.get("edges") or []:
            source = id_map.get(str(edge.get("source")))
            target = id_map.get(str(edge.get("target")))
            if source and target:
                try:
                    self.graph.connect(source, edge["source_port"], target, edge["target_port"])
                except (GraphError, KeyError):
                    pass
        self.rebuild()
        self.clearSelection()
        for node_id in id_map.values():
            item = self.node_items.get(node_id)
            if item:
                item.setSelected(True)
        self.commit_edit(f"Paste {len(id_map)} node(s)")

    # -- execution visuals ----------------------------------------------
    def clear_run_state(self) -> None:
        for item in self.node_items.values():
            item.clear_run_state()
        for edge in self.edge_items.values():
            edge.clear_run_state()

    def set_active_node(self, node_id: str | None, active_edge_ids: Iterable[str] = ()) -> None:
        for edge in self.edge_items.values():
            if edge.run_status == "active":
                edge.run_status = ""
        for item in self.node_items.values():
            if item.run_status == "running":
                item.run_status = ""
                item.update()
        if node_id and node_id in self.node_items:
            item = self.node_items[node_id]
            item.run_status = "running"
            item.update()
        for edge_id in active_edge_ids:
            edge = self.edge_items.get(edge_id)
            if edge:
                edge.run_status = "active"
                edge.update()

    def apply_run_result(self, result) -> None:
        self.clear_run_state()
        outputs_by_node = {}
        for node_id, node_result in result.nodes.items():
            item = self.node_items.get(node_id)
            if item is None:
                continue
            status = "cached" if node_result.cached and node_result.status == "ok" else node_result.status
            item.set_run_status(status, node_result.outputs)
            outputs_by_node[node_id] = node_result
        for edge in self.graph.edges:
            edge_item = self.edge_items.get(edge.id)
            source_result = outputs_by_node.get(edge.source)
            if edge_item is None:
                continue
            source_ok = source_result is not None and source_result.status == "ok"
            if source_ok and edge.source_port in source_result.outputs:
                value = source_result.outputs[edge.source_port]
                edge_item.set_run_state("ok", value_preview(value))
            elif source_result is not None and source_result.status == "error":
                edge_item.set_run_state("error")
        # error nodes get flagged even when they have no outgoing edges
        for node_id, node_result in result.nodes.items():
            item = self.node_items.get(node_id)
            if item is not None and node_result.status == "error":
                item.set_run_status("error")

    def select_node(self, node_id: str) -> None:
        item = self.node_items.get(node_id)
        if item is None:
            return
        self.clearSelection()
        item.setSelected(True)
        for view in self.views():
            view.ensureVisible(item, 60, 60)

    # -- menu -----------------------------------------------------------
    def context_menu(self, scene_pos: QPointF) -> QMenu:
        menu = QMenu()
        item = self.itemAt(scene_pos, None)
        node_item = self._node_for(item)
        edge_item = item if isinstance(item, EdgeItem) else None
        if node_item is not None:
            menu.addAction("Duplicate", self.duplicate_selection)
            menu.addAction("Delete", self.delete_selection)
            action = menu.addAction("Toggle breakpoint", lambda: self.toggle_breakpoint(node_item.node.id))
            menu.addSeparator()
            menu.addAction(
                "Disabled" if node_item.node.disabled else "Enabled",
                lambda: self.set_node_flag(node_item.node.id, "disabled", not node_item.node.disabled),
            )
            menu.addAction("Convert selection to function…", lambda: self.request_convert_to_function.emit(self.selected_node_ids()))
            menu.addAction("Add function…", lambda: self.request_add_function.emit())
            menu.addSeparator()
            menu.addAction("Copy", self.copy_selection)
            return menu
        if edge_item is not None:
            menu.addAction("Delete wire", lambda: self.disconnect_edge(edge_item.edge.id))
            return menu
        add_menu = menu.addMenu("Add node")
        categories: dict[str, list] = {}
        for definition in self.registry.all():
            categories.setdefault(definition.category, []).append(definition)
        for category in sorted(categories):
            submenu = add_menu.addMenu(category)
            for definition in sorted(categories[category], key=lambda d: d.name):
                submenu.addAction(definition.name, lambda d=definition: self.add_node(d.type_id, scene_pos))
        menu.addSeparator()
        paste = menu.addAction("Paste", lambda: self.paste(scene_pos))
        paste.setEnabled(bool(QApplication.clipboard().text()))
        menu.addAction("Add annotation", lambda: self.group_selection(annotation=True))
        menu.addAction("Auto layout", self.auto_layout)
        menu.addSeparator()
        menu.addAction("Select all", self.select_all_nodes)
        return menu

    def _node_for(self, item):
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        return item if isinstance(item, NodeItem) else None

    def selected_node_ids(self) -> list[str]:
        return [item.node.id for item in self.selectedItems() if isinstance(item, NodeItem)]

    def select_all_nodes(self) -> None:
        for item in self.node_items.values():
            item.setSelected(True)

    # -- painting -------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        theme = get_theme(self.theme_name)
        painter.fillRect(rect, QColor(theme.canvas))
        step = 24
        left = int(rect.left()) - (int(rect.left()) % step)
        top = int(rect.top()) - (int(rect.top()) % step)
        pen_minor = QPen(QColor(theme.grid), 1)
        pen_major = QPen(QColor(theme.grid_major), 1)
        painter.setPen(pen_minor)
        for x in range(left, int(rect.right()), step):
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(top, int(rect.bottom()), step):
            painter.drawLine(rect.left(), y, rect.right(), y)
        painter.setPen(pen_major)
        for x in range(left, int(rect.right()), step * 5):
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(top, int(rect.bottom()), step * 5):
            painter.drawLine(rect.left(), y, rect.right(), y)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if not self.graph.nodes:
            painter.setPen(QColor(get_theme(self.theme_name).muted))
            font = QFont()
            font.setPointSizeF(13)
            painter.setFont(font)
            painter.drawText(
                QRectF(-260, -20, 520, 40),
                Qt.AlignCenter,
                "Drag a node from the library or double-click the canvas",
            )
