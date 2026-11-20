"""New-project dialog with template selection."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ...project.templates import TEMPLATES

TEMPLATE_INFO = {
    "Blank": "An empty graph. Start from scratch.",
    "Arithmetic": "Two constants multiplied and published as a graph output.",
    "Function": "A reusable doubling function called from the main graph.",
    "Loop": "A for-loop accumulating values through a function body.",
    "JSON": "Parse a JSON document and query a field.",
    "Python Script": "Run a sandboxed Python script over a list of numbers.",
}


class NewProjectDialog(QDialog):
    def __init__(self, *, default_dir: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New project")
        self.resize(620, 440)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit("Untitled")
        form.addRow("Project name", self.name_edit)
        location_row = QHBoxLayout()
        self.location_edit = QLineEdit(default_dir)
        location_row.addWidget(self.location_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        location_row.addWidget(browse)
        form.addRow("Location", location_row)
        layout.addLayout(form)

        layout.addWidget(QLabel("Template"))
        self.templates = QListWidget()
        self.templates.setAlternatingRowColors(True)
        for template in TEMPLATES:
            item = QListWidgetItem(f"{template} — {TEMPLATE_INFO.get(template, '')}")
            item.setData(Qt.UserRole, template)
            self.templates.addItem(item)
        self.templates.setCurrentRow(0)
        layout.addWidget(self.templates, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose project folder", self.location_edit.text())
        if folder:
            self.location_edit.setText(folder)

    def _accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        self.accept()

    @property
    def project_name(self) -> str:
        return self.name_edit.text().strip() or "Untitled"

    @property
    def template(self) -> str:
        item = self.templates.currentItem()
        return item.data(Qt.UserRole) if item is not None else "Blank"

    @property
    def directory(self) -> str:
        text = self.location_edit.text().strip()
        return str(Path(text).expanduser()) if text else ""
