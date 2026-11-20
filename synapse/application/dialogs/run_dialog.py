"""Collect values for a graph's declared inputs before a run."""

from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...typesystem import ConversionError, PortSpec, coerce_value


class RunInputsDialog(QDialog):
    def __init__(self, inputs: list[PortSpec], *, graph_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Run {graph_name}")
        self.resize(440, 260)
        self.inputs = list(inputs)
        self._editors: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        intro = QLabel("Provide a value for each graph input.")
        intro.setObjectName("subheading")
        layout.addWidget(intro)
        form = QFormLayout()
        for port in self.inputs:
            editor = QLineEdit()
            default = port.default
            if default is not None:
                editor.setText(default if isinstance(default, str) else json.dumps(default))
            editor.setPlaceholderText(str(port.spec))
            form.addRow(f"{port.name} ({port.spec})", editor)
            self._editors[port.name] = editor
        layout.addLayout(form)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self) -> None:
        try:
            self.values = self._values()
        except ConversionError as exc:
            for editor in self._editors.values():
                editor.setStyleSheet("")
            self.setWindowTitle(f"Cannot run: {exc}")
            return
        self.accept()

    def _values(self) -> dict:
        values = {}
        for port in self.inputs:
            text = self._editors[port.name].text()
            if port.optional and text == "":
                values[port.name] = None
                continue
            raw = text
            if port.data_type.value not in ("string", "any"):
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError:
                    raw = text
            values[port.name] = coerce_value(raw, port.spec, port.name)
        return values
