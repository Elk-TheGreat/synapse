"""Dockable visual debugger controls and trace viewer."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...debugger.values import format_value, value_preview


class DebuggerPanel(QWidget):
    resume_requested = Signal()
    pause_requested = Signal()
    step_requested = Signal()
    stop_requested = Signal()
    node_selected = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        controls = QHBoxLayout()
        self.continue_button = QPushButton("Continue")
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(self.resume_requested)
        controls.addWidget(self.continue_button)
        self.pause_button = QPushButton("Pause")
        self.pause_button.clicked.connect(self.pause_requested)
        controls.addWidget(self.pause_button)
        self.step_button = QPushButton("Step")
        self.step_button.clicked.connect(self.step_requested)
        controls.addWidget(self.step_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self.stop_requested)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)

        self.state = QLabel("Idle")
        self.state.setObjectName("subheading")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)

        splitter = QSplitter(Qt.Vertical)
        self.trace = QTableWidget(0, 3)
        self.trace.setHorizontalHeaderLabels(["Node", "Status", "ms"])
        self.trace.verticalHeader().setVisible(False)
        self.trace.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trace.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trace.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.trace.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.trace.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.trace.cellClicked.connect(self._trace_clicked)
        splitter.addWidget(self.trace)
        self.detail = QPlainTextEdit()
        self.detail.setObjectName("console")
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Paused node inputs and outputs appear here.")
        splitter.addWidget(self.detail)
        splitter.setSizes([200, 160])
        layout.addWidget(splitter, 1)

        self.set_debugging(False)

    def set_debugging(self, active: bool) -> None:
        self.continue_button.setEnabled(active)
        self.pause_button.setEnabled(active)
        self.step_button.setEnabled(active)
        self.stop_button.setEnabled(active)
        if not active:
            self.state.setText("Idle · add a breakpoint, then press Debug")

    def clear(self) -> None:
        self.trace.setRowCount(0)
        self.detail.clear()
        self.state.setText("Idle")

    def running(self) -> None:
        self.set_debugging(True)
        self.state.setText("Running…")

    def paused(self, node_id: str, node_name: str, inputs: dict) -> None:
        self.set_debugging(True)
        self.state.setText(f"Paused before {node_name} ({node_id})")
        lines = [f"node: {node_name}", f"id: {node_id}", "", "inputs:"]
        for name, value in inputs.items():
            lines.append(f"  {name} = {format_value(value, 2000)}")
        self.detail.setPlainText("\n".join(lines))

    def add_trace(self, entry) -> None:
        row = self.trace.rowCount()
        self.trace.insertRow(row)
        name = QTableWidgetItem(entry.node_name)
        name.setData(Qt.UserRole, entry.node_id)
        self.trace.setItem(row, 0, name)
        status = QTableWidgetItem(entry.status)
        status.setForeground(QColor("#34d399" if entry.status == "ok" else "#f87171" if entry.status == "error" else "#94a3b8"))
        self.trace.setItem(row, 1, status)
        self.trace.setItem(row, 2, QTableWidgetItem(f"{entry.duration * 1000:.1f}"))
        self.trace.scrollToBottom()

    def finished(self, result) -> None:
        self.state.setText(result.summary())
        if result.errors:
            self.detail.setPlainText("\n\n".join(str(e) for e in result.errors))
        self.set_debugging(False)

    def show_values(self, node_name: str, node_id: str, inputs: dict, outputs: dict) -> None:
        lines = [f"node: {node_name}", f"id: {node_id}", "", "inputs:"]
        for name, value in inputs.items():
            lines.append(f"  {name} = {value_preview(value)}")
        lines.append("")
        lines.append("outputs:")
        for name, value in outputs.items():
            lines.append(f"  {name} = {value_preview(value)}")
        self.detail.setPlainText("\n".join(lines))

    def _trace_clicked(self, row: int, column: int) -> None:
        item = self.trace.item(row, 0)
        if item is not None:
            node_id = item.data(Qt.UserRole)
            if node_id:
                self.node_selected.emit(node_id)
