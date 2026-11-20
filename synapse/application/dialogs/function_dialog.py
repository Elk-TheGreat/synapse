"""Name/describe a reusable function and preview its signature."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from ...typesystem import PortSpec


class FunctionDialog(QDialog):
    def __init__(
        self,
        *,
        name: str = "",
        description: str = "",
        inputs: list[PortSpec] | tuple[PortSpec, ...] = (),
        outputs: list[PortSpec] | tuple[PortSpec, ...] = (),
        title: str = "Create function",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 380)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("e.g. Normalise scores")
        form.addRow("Name", self.name_edit)
        self.description_edit = QPlainTextEdit(description)
        self.description_edit.setPlaceholderText("What does this function do?")
        self.description_edit.setFixedHeight(90)
        form.addRow("Description", self.description_edit)
        layout.addLayout(form)

        signature = self._signature(inputs, outputs)
        preview = QLabel(signature)
        preview.setWordWrap(True)
        preview.setObjectName("subheading")
        layout.addWidget(QLabel("Signature"))
        layout.addWidget(preview)
        if inputs or outputs:
            detail = QLabel(
                "Inputs and outputs were inferred from the connections that leave the selection."
            )
            detail.setWordWrap(True)
            detail.setObjectName("subheading")
            layout.addWidget(detail)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name_edit.setFocus()

    @staticmethod
    def _signature(inputs, outputs) -> str:
        ins = ", ".join(f"{p.name}: {p.spec}" for p in inputs)
        outs = ", ".join(f"{p.name}: {p.spec}" for p in outputs)
        return f"({ins}) -> ({outs})"

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        self.accept()

    @property
    def function_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def function_description(self) -> str:
        return self.description_edit.toPlainText().strip()
