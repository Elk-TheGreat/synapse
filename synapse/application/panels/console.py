"""Execution console: log, timeline, variable inspector and problems."""

from __future__ import annotations

import html
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...debugger.values import format_value, value_preview

LEVEL_COLOURS = {
    "info": "#8b97a8",
    "ok": "#34d399",
    "warn": "#fbbf24",
    "error": "#f87171",
    "debug": "#38bdf8",
    "muted": "#5f6f82",
}
STATUS_COLOURS = {
    "ok": "#34d399",
    "error": "#f87171",
    "skipped": "#94a3b8",
    "cancelled": "#fbbf24",
    "pending": "#8b97a8",
}


class ExecutionConsole(QWidget):
    node_selected = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.last_result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(10, 6, 10, 4)
        self.status = QLabel("Ready")
        self.status.setObjectName("sectionLabel")
        header.addWidget(self.status)
        header.addStretch(1)
        self.duration = QLabel("")
        self.duration.setObjectName("subheading")
        header.addWidget(self.duration)
        clear = QPushButton("Clear")
        clear.setObjectName("ghost")
        clear.clicked.connect(self.clear)
        header.addWidget(clear)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)

        self.output = QPlainTextEdit()
        self.output.setObjectName("console")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(4000)
        self.output.setPlaceholderText("Run the graph to see execution output.")
        self.tabs.addTab(self.output, "Output")

        self.timeline = QTableWidget(0, 5)
        self.timeline.setHorizontalHeaderLabels(["Node", "Type", "Status", "Time", "Cached"])
        self.timeline.verticalHeader().setVisible(False)
        self.timeline.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.timeline.setSelectionMode(QAbstractItemView.SingleSelection)
        self.timeline.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.timeline.setAlternatingRowColors(True)
        self.timeline.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.timeline.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.timeline.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.timeline.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.timeline.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.timeline.cellDoubleClicked.connect(self._timeline_clicked)
        details = QWidget()
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.timeline)
        self.node_detail = QPlainTextEdit()
        self.node_detail.setObjectName("console")
        self.node_detail.setReadOnly(True)
        self.node_detail.setPlaceholderText("Select a node result to inspect its inputs and outputs.")
        splitter.addWidget(self.node_detail)
        splitter.setSizes([220, 140])
        details_layout.addWidget(splitter)
        self.tabs.addTab(details, "Timeline")

        self.variables = QTreeWidget()
        self.variables.setHeaderLabels(["Name", "Value"])
        self.variables.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.variables.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.variables.setAlternatingRowColors(True)
        self.variables.itemDoubleClicked.connect(self._variable_clicked)
        self.tabs.addTab(self.variables, "Variables")

        self.problems = QListWidget()
        self.problems.itemDoubleClicked.connect(self._problem_clicked)
        self.tabs.addTab(self.problems, "Problems")

    # -- logging --------------------------------------------------------
    def log(self, message: str, level: str = "info", *, node: str = "", timestamp: bool = True) -> None:
        colour = LEVEL_COLOURS.get(level, LEVEL_COLOURS["info"])
        prefix = time.strftime("%H:%M:%S") if timestamp else ""
        prefix_html = f'<span style="color:#5f6f82">{prefix}</span> ' if prefix else ""
        node_html = f'<span style="color:#60a5fa">[{html.escape(node)}]</span> ' if node else ""
        body = html.escape(str(message)).replace("\n", "<br>")
        self.output.appendHtml(f'{prefix_html}{node_html}<span style="color:{colour}">{body}</span>')
        if level == "error":
            item = QListWidgetItem(f"{node + ': ' if node else ''}{message}")
            item.setForeground(QColor("#f87171"))
            item.setData(Qt.UserRole, node)
            self.problems.addItem(item)
            self.tabs.setTabText(3, f"Problems ({self.problems.count()})")

    def clear(self) -> None:
        self.output.clear()
        self.problems.clear()
        self.timeline.setRowCount(0)
        self.variables.clear()
        self.node_detail.clear()
        self.status.setText("Ready")
        self.duration.setText("")
        self.tabs.setTabText(3, "Problems")
        self.clear_requested.emit()

    def set_status(self, text: str, detail: str = "") -> None:
        self.status.setText(text)
        self.duration.setText(detail)

    # -- events ---------------------------------------------------------
    def handle_event(self, event) -> None:
        kind = event.kind
        if kind == "log":
            self.log(event.message, event.level, node=event.node_name)
        elif kind == "graph_start":
            self.set_status("Running…", "")
            self.log(f"Run started · {event.data.get('nodes', 0)} nodes scheduled", "debug")
        elif kind == "graph_error":
            self.log(event.message, "error")
        elif kind == "graph_finish":
            text = event.message or "run finished"
            level = "error" if ("error" in text or "cancelled" in text or "timeout" in text) else "ok"
            self.log(text, level)
        elif kind == "node_start":
            self.log(f"→ {event.node_name}", "muted", node=event.node_id)
        elif kind == "node_finish":
            if event.data.get("cached"):
                self.log(f"↺ {event.node_name} (cached)", "debug", node=event.node_id)
            else:
                self.log(f"✓ {event.node_name} · {event.duration * 1000:.1f} ms", "ok", node=event.node_id)
        elif kind == "node_error":
            self.log(event.message, "error", node=event.node_id)
        elif kind == "node_skipped":
            self.log(f"⏭ {event.node_name}: {event.message}", "warn", node=event.node_id)
        elif kind == "debug_pause":
            self.log(f"⏸ Paused before {event.node_name}", "warn", node=event.node_id)

    def show_started(self, graph_name: str, debug: bool = False) -> None:
        self.problems.clear()
        self.tabs.setTabText(3, "Problems")
        self.timeline.setRowCount(0)
        self.variables.clear()
        self.set_status(f"Running {graph_name}{' (debug)' if debug else ''}…", "")
        self.log(f"── {graph_name} ──", "debug")

    def show_result(self, result) -> None:
        self.last_result = result
        self.timeline.setRowCount(0)
        self.variables.clear()
        for row, node_id in enumerate(result.order):
            node_result = result.nodes.get(node_id)
            if node_result is None:
                continue
            self.timeline.insertRow(row)
            name_item = QTableWidgetItem(node_result.node_name)
            name_item.setData(Qt.UserRole, node_id)
            if node_result.error:
                name_item.setToolTip(node_result.error)
            self.timeline.setItem(row, 0, name_item)
            self.timeline.setItem(row, 1, QTableWidgetItem(node_result.node_type))
            status_item = QTableWidgetItem("cached" if node_result.cached and node_result.ok else node_result.status)
            status_item.setForeground(QColor(STATUS_COLOURS.get(node_result.status, "#8b97a8")))
            self.timeline.setItem(row, 2, status_item)
            self.timeline.setItem(row, 3, QTableWidgetItem(f"{node_result.duration * 1000:.1f} ms"))
            self.timeline.setItem(row, 4, QTableWidgetItem("yes" if node_result.cached else ""))
        outputs_root = QTreeWidgetItem(["Graph outputs", ""])
        font = outputs_root.font(0)
        font.setBold(True)
        outputs_root.setFont(0, font)
        self.variables.addTopLevelItem(outputs_root)
        if result.outputs:
            for name, value in result.outputs.items():
                item = QTreeWidgetItem([name, value_preview(value)])
                item.setToolTip(1, format_value(value))
                outputs_root.addChild(item)
        else:
            outputs_root.addChild(QTreeWidgetItem(["(none)", ""]))
        outputs_root.setExpanded(True)
        for node_id in result.order:
            node_result = result.nodes.get(node_id)
            if node_result is None:
                continue
            parent = QTreeWidgetItem([f"{node_result.node_name}", node_result.status])
            parent.setData(0, Qt.UserRole, node_id)
            if node_result.error:
                parent.setForeground(1, QColor("#f87171"))
            for name, value in node_result.outputs.items():
                child = QTreeWidgetItem([name, value_preview(value)])
                child.setToolTip(1, format_value(value))
                parent.addChild(child)
            if node_result.inputs:
                inputs_item = QTreeWidgetItem(["inputs", ""])
                for name, value in node_result.inputs.items():
                    child = QTreeWidgetItem([name, value_preview(value)])
                    child.setToolTip(1, format_value(value))
                    inputs_item.addChild(child)
                parent.addChild(inputs_item)
            self.variables.addTopLevelItem(parent)
        if result.errors:
            for error in result.errors:
                self.log(str(error), "error", node=getattr(error, "node_id", "") or "")
                item = QListWidgetItem(str(error))
                item.setForeground(QColor("#f87171"))
                item.setData(Qt.UserRole, getattr(error, "node_id", "") or "")
                self.problems.addItem(item)
            self.tabs.setTabText(3, f"Problems ({self.problems.count()})")
        for warning in result.validation_errors:
            self.log(warning, "error")
        level = "ok" if result.ok else ("error" if result.status != "cancelled" else "warn")
        self.log(result.summary(), level)
        self.set_status(result.summary(), f"{len(result.nodes)} nodes")
        self.tabs.setTabText(0, "Output")

    # -- interaction ----------------------------------------------------
    def _timeline_clicked(self, row: int, column: int) -> None:
        item = self.timeline.item(row, 0)
        if item is None:
            return
        node_id = item.data(Qt.UserRole)
        self._show_node_detail(node_id)
        if node_id:
            self.node_selected.emit(node_id)

    def _show_node_detail(self, node_id: str) -> None:
        if self.last_result is None:
            return
        node_result = self.last_result.nodes.get(node_id)
        if node_result is None:
            return
        lines = [f"{node_result.node_name}  ({node_result.node_type})", f"status: {node_result.status}", ""]
        if node_result.error:
            lines += ["error:", node_result.error, ""]
        lines.append("inputs:")
        for name, value in node_result.inputs.items():
            lines.append(f"  {name} = {format_value(value, 1200)}")
        lines.append("")
        lines.append("outputs:")
        for name, value in node_result.outputs.items():
            lines.append(f"  {name} = {format_value(value, 1200)}")
        self.node_detail.setPlainText("\n".join(lines))

    def _problem_clicked(self, item: QListWidgetItem) -> None:
        node_id = item.data(Qt.UserRole)
        if node_id:
            self.node_selected.emit(node_id)

    def _variable_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        node_id = item.data(0, Qt.UserRole)
        if node_id:
            self.node_selected.emit(node_id)
