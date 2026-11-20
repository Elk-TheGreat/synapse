"""Properties inspector for the selected node or the graph itself."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...debugger.values import format_value
from ...nodes.base import ParamSpec
from ..theme import category_color


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("separator")
    line.setFrameShape(QFrame.HLine)
    return line


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionLabel")
    return label


class NodeInspector(QWidget):
    param_changed = Signal(str, str, object)
    label_changed = Signal(str, str)
    notes_changed = Signal(str, str)
    flag_changed = Signal(str, str, bool)
    breakpoint_requested = Signal(str)
    delete_requested = Signal(list)
    convert_requested = Signal(list)
    graph_meta_changed = Signal(str, str)
    edit_function_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.node = None
        self.definition = None
        self.graph = None
        self._pending = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._flush_pending)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(self.scroll)
        self.body = QWidget()
        self.form = QVBoxLayout(self.body)
        self.form.setContentsMargins(12, 12, 12, 12)
        self.form.setSpacing(10)
        self.scroll.setWidget(self.body)

    # -- public API -----------------------------------------------------
    def show_empty(self, graph=None) -> None:
        self.node = None
        self.definition = None
        self.graph = graph
        self._clear()
        if graph is None:
            self.form.addWidget(_section("Inspector"))
            label = QLabel("Select a node to inspect it.")
            label.setObjectName("subheading")
            label.setWordWrap(True)
            self.form.addWidget(label)
            self.form.addStretch(1)
            return
        self.form.addWidget(_section("Graph"))
        title = QLabel(graph.name)
        title.setObjectName("heading")
        self.form.addWidget(title)
        meta = QLabel(f"{len(graph.nodes)} nodes · {len(graph.edges)} connections · {len(graph.frames)} frames")
        meta.setObjectName("subheading")
        self.form.addWidget(meta)

        self.form.addWidget(_separator())
        self.form.addWidget(_section("Metadata"))
        name = QLineEdit(graph.name)
        name.editingFinished.connect(lambda: self.graph_meta_changed.emit(name.text().strip() or "Untitled", description.toPlainText()))
        self.form.addWidget(name)
        description = QPlainTextEdit(graph.description)
        description.setPlaceholderText("What does this graph do?")
        description.setFixedHeight(84)
        description.textChanged.connect(self._schedule_graph_meta)
        self.form.addWidget(description)

        if graph.inputs or graph.outputs:
            self.form.addWidget(_separator())
            self.form.addWidget(_section("Graph interface"))
            for port in graph.inputs:
                self.form.addWidget(QLabel(f"in · {port.name}  ({port.spec})"))
            for port in graph.outputs:
                self.form.addWidget(QLabel(f"out · {port.name}  ({port.spec})"))

        self.form.addWidget(_separator())
        self.form.addWidget(_section("Variables"))
        if graph.variables:
            for name_, spec in graph.variables.items():
                self.form.addWidget(QLabel(f"{name_} : {spec.get('type', 'any')}"))
        else:
            hint = QLabel("No graph variables declared. Variables set by nodes are stored at runtime.")
            hint.setObjectName("subheading")
            hint.setWordWrap(True)
            self.form.addWidget(hint)
        self.form.addStretch(1)

    def show_node(self, node, definition, graph=None) -> None:
        self.node = node
        self.definition = definition
        self.graph = graph
        self._clear()
        if definition is None:
            self.form.addWidget(QLabel(f"Missing node type: {node.type}"))
            return
        header = QHBoxLayout()
        title = QLabel(node.label or definition.name)
        title.setObjectName("heading")
        header.addWidget(title)
        header.addStretch(1)
        category = QLabel(definition.category)
        category.setStyleSheet(
            f"color:{category_color(definition.category)}; border:1px solid {category_color(definition.category)};"
            "border-radius:4px; padding:2px 7px; font-size:10px;"
        )
        header.addWidget(category)
        self.form.addLayout(header)

        type_label = QLabel(f"{definition.type_id} · v{definition.version}" + (" · plugin" if definition.source == "plugin" else ""))
        type_label.setObjectName("subheading")
        type_label.setWordWrap(True)
        self.form.addWidget(type_label)
        if definition.description:
            description = QLabel(definition.description)
            description.setWordWrap(True)
            self.form.addWidget(description)

        if definition.type_id.startswith("fn."):
            button = QPushButton("Edit function…")
            button.setObjectName("ghost")
            button.clicked.connect(lambda: self.edit_function_requested.emit(definition.function_id or ""))
            self.form.addWidget(button)

        self.form.addWidget(_separator())
        self.form.addWidget(_section("Identity"))
        label_edit = QLineEdit(node.label or "")
        label_edit.setPlaceholderText(definition.name)
        label_edit.editingFinished.connect(lambda: self.label_changed.emit(node.id, label_edit.text().strip()))
        self.form.addWidget(label_edit)

        if definition.params:
            self.form.addWidget(_separator())
            self.form.addWidget(_section("Parameters"))
            form = QFormLayout()
            form.setLabelAlignment(Qt.AlignLeft)
            form.setHorizontalSpacing(10)
            form.setVerticalSpacing(8)
            for spec in definition.params.values():
                form.addRow(spec.label, self._editor(node, spec))
            self.form.addLayout(form)

        ports = _PortList(node, definition)
        self.form.addWidget(_separator())
        self.form.addWidget(_section("Ports"))
        self.form.addWidget(ports)

        self.form.addWidget(_separator())
        self.form.addWidget(_section("Notes"))
        notes = QPlainTextEdit(node.notes)
        notes.setPlaceholderText("Notes stay with this node inside the project.")
        notes.setFixedHeight(64)
        notes.textChanged.connect(lambda: self.notes_changed.emit(node.id, notes.toPlainText()))
        self.form.addWidget(notes)

        self.form.addWidget(_separator())
        self.form.addWidget(_section("Debug"))
        debug_row = QHBoxLayout()
        breakpoint = QPushButton("Breakpoint")
        breakpoint.setCheckable(True)
        breakpoint.clicked.connect(lambda: self.breakpoint_requested.emit(node.id))
        debug_row.addWidget(breakpoint)
        enabled = QCheckBox("Enabled")
        enabled.setChecked(not node.disabled)
        enabled.toggled.connect(lambda checked: self.flag_changed.emit(node.id, "disabled", not checked))
        debug_row.addWidget(enabled)
        self.form.addLayout(debug_row)

        actions = QHBoxLayout()
        convert = QPushButton("Convert to function…")
        convert.setObjectName("ghost")
        convert.clicked.connect(lambda: self.convert_requested.emit([node.id]))
        actions.addWidget(convert)
        delete = QPushButton("Delete")
        delete.setObjectName("danger")
        delete.clicked.connect(lambda: self.delete_requested.emit([node.id]))
        actions.addWidget(delete)
        self.form.addLayout(actions)
        self.form.addStretch(1)

    # -- editors --------------------------------------------------------
    def _editor(self, node, spec: ParamSpec) -> QWidget:
        value = node.params.get(spec.name, spec.default)
        node_id = node.id
        if spec.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.toggled.connect(lambda checked: self._emit(node_id, spec.name, checked))
            return widget
        if spec.kind == "choice":
            widget = QComboBox()
            choices = list(spec.choices) or [str(value)]
            widget.addItems(choices)
            if str(value) in choices:
                widget.setCurrentText(str(value))
            widget.currentTextChanged.connect(lambda text: self._emit(node_id, spec.name, text))
            return widget
        if spec.kind == "int":
            widget = QSpinBox()
            widget.setRange(int(spec.minimum if spec.minimum is not None else -1_000_000_000),
                            int(spec.maximum if spec.maximum is not None else 1_000_000_000))
            try:
                widget.setValue(int(value))
            except (TypeError, ValueError):
                widget.setValue(int(spec.default or 0))
            widget.valueChanged.connect(lambda number: self._emit(node_id, spec.name, number))
            return widget
        if spec.kind == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(4)
            widget.setRange(spec.minimum if spec.minimum is not None else -1e9,
                            spec.maximum if spec.maximum is not None else 1e9)
            try:
                widget.setValue(float(value))
            except (TypeError, ValueError):
                widget.setValue(float(spec.default or 0.0))
            widget.valueChanged.connect(lambda number: self._emit(node_id, spec.name, number))
            return widget
        if spec.kind in ("multiline", "code", "json"):
            widget = QPlainTextEdit()
            if spec.kind == "json":
                widget.setPlainText(json.dumps(value, indent=2) if not isinstance(value, str) else value)
            else:
                widget.setPlainText("" if value is None else str(value))
            widget.setFixedHeight(76 if spec.kind == "json" else (120 if spec.kind == "code" else 68))
            font = QFont("JetBrains Mono, Menlo, monospace")
            font.setPointSizeF(9.2)
            widget.setFont(font)
            widget.setProperty("paramName", spec.name)
            if spec.kind == "json":
                widget.setPlaceholderText("Valid JSON, e.g. {\"key\": 1}")
                widget.textChanged.connect(lambda w=widget: self._schedule_json(node_id, spec, w))
            else:
                widget.textChanged.connect(lambda w=widget: self._schedule(node_id, spec.name, w.toPlainText()))
            return widget
        if spec.kind == "file":
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            edit = QLineEdit("" if value is None else str(value))
            edit.editingFinished.connect(lambda: self._emit(node_id, spec.name, edit.text()))
            row.addWidget(edit, 1)
            browse = QPushButton("…")
            browse.setFixedWidth(30)
            browse.clicked.connect(lambda: self._browse(edit, node_id, spec.name))
            row.addWidget(browse)
            return container
        widget = QLineEdit("" if value is None else str(value))
        if spec.secret:
            widget.setEchoMode(QLineEdit.Password)
            widget.setPlaceholderText("Value from environment")
        widget.editingFinished.connect(lambda: self._emit(node_id, spec.name, widget.text(), spec))
        return widget

    def _browse(self, edit: QLineEdit, node_id: str, name: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose file")
        if path:
            edit.setText(path)
            self._emit(node_id, name, path)

    def _emit(self, node_id: str, name: str, value, spec: ParamSpec | None = None) -> None:
        if spec is not None and spec.kind in ("int", "float") and isinstance(value, str):
            try:
                value = spec.coerce(value)
            except ValueError:
                return
        self.param_changed.emit(node_id, name, value)

    def _schedule(self, node_id: str, name: str, value) -> None:
        self._pending = {"kind": "plain", "node": node_id, "name": name, "value": value}
        self._timer.start()

    def _schedule_json(self, node_id: str, spec: ParamSpec, widget: QPlainTextEdit) -> None:
        text = widget.toPlainText()
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            widget.setToolTip(f"Invalid JSON: {exc}")
            widget.setStyleSheet("border: 1px solid #ef4444;")
            return
        widget.setToolTip("")
        widget.setStyleSheet("")
        self._pending = {"kind": "plain", "node": node_id, "name": spec.name, "value": value}
        self._timer.start()

    def _schedule_graph_meta(self) -> None:
        if self.graph is None or self.node is not None:
            return
        self._pending = {"kind": "graph"}
        self._timer.start()

    def _flush_pending(self) -> None:
        pending = self._pending
        self._pending = {}
        if pending.get("kind") == "plain":
            self.param_changed.emit(pending["node"], pending["name"], pending["value"])

    def _clear(self) -> None:
        # QScrollArea takes ownership of the new body and deletes the old one.
        self.body = QWidget()
        self.form = QVBoxLayout(self.body)
        self.form.setContentsMargins(12, 12, 12, 12)
        self.form.setSpacing(10)
        self.scroll.setWidget(self.body)


class _PortList(QWidget):
    def __init__(self, node, definition) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for spec in definition.inputs:
            layout.addWidget(self._row("in", spec, node, output=False))
        for spec in definition.outputs:
            layout.addWidget(self._row("out", spec, node, output=True))
        if not definition.inputs and not definition.outputs:
            layout.addWidget(QLabel("No ports"))

    def _row(self, direction: str, spec, node, *, output: bool) -> QLabel:
        data_type = spec.data_type
        text = f"{direction} · {spec.name} : {spec.spec}" if hasattr(spec, "spec") else f"{direction} · {spec.name}"
        label = QLabel(text)
        font = QFont("JetBrains Mono, Menlo, monospace")
        font.setPointSizeF(8.8)
        label.setFont(font)
        if spec.default is not None:
            label.setToolTip(f"default: {format_value(spec.default, 200)}")
        return label
