"""Project settings: appearance, execution limits and the security policy."""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...project.model import ProjectSettings


class SettingsDialog(QDialog):
    def __init__(self, settings: ProjectSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project settings")
        self.resize(560, 520)
        self.settings = settings
        self._accent = settings.accent

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        # Appearance ----------------------------------------------------
        appearance = QWidget()
        form = QFormLayout(appearance)
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(settings.theme)
        form.addRow("Theme", self.theme)
        accent_row = QHBoxLayout()
        self.accent_button = QPushButton(settings.accent)
        self.accent_button.clicked.connect(self._pick_accent)
        accent_row.addWidget(self.accent_button, 1)
        accent_row.addStretch(1)
        form.addRow("Accent colour", accent_row)
        self.autosave = QSpinBox()
        self.autosave.setRange(5, 3600)
        self.autosave.setSuffix(" s")
        self.autosave.setValue(int(settings.autosave_seconds))
        form.addRow("Autosave every", self.autosave)
        tabs.addTab(appearance, "Appearance")

        # Execution -----------------------------------------------------
        execution = QWidget()
        form = QFormLayout(execution)
        self.run_timeout = QDoubleSpinBox()
        self.run_timeout.setRange(1.0, 3600.0)
        self.run_timeout.setSuffix(" s")
        self.run_timeout.setValue(float(settings.run_timeout))
        form.addRow("Run timeout", self.run_timeout)
        self.node_timeout = QDoubleSpinBox()
        self.node_timeout.setRange(1.0, 600.0)
        self.node_timeout.setSuffix(" s")
        self.node_timeout.setValue(float(settings.node_timeout))
        form.addRow("Node timeout", self.node_timeout)
        self.max_steps = QSpinBox()
        self.max_steps.setRange(100, 10_000_000)
        self.max_steps.setSingleStep(1000)
        self.max_steps.setValue(int(settings.max_steps))
        form.addRow("Step limit", self.max_steps)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 64)
        self.concurrency.setValue(int(settings.concurrency))
        form.addRow("Parallel nodes", self.concurrency)
        tabs.addTab(execution, "Execution")

        # Security ------------------------------------------------------
        security = QWidget()
        form = QFormLayout(security)
        self.allow_network = QCheckBox("Allow network access (HTTP, WebSocket, downloads)")
        self.allow_network.setChecked(settings.allow_network)
        form.addRow("", self.allow_network)
        self.allow_write = QCheckBox("Allow file writes and deletes")
        self.allow_write.setChecked(settings.allow_file_write)
        form.addRow("", self.allow_write)
        self.allow_process = QCheckBox("Allow starting processes")
        self.allow_process.setChecked(settings.allow_process)
        form.addRow("", self.allow_process)
        self.allow_scripts = QCheckBox("Allow Python script nodes")
        self.allow_scripts.setChecked(settings.allow_scripts)
        form.addRow("", self.allow_scripts)
        self.file_roots = QPlainTextEdit("\n".join(settings.file_roots))
        self.file_roots.setPlaceholderText("One folder per line. The project folder is always allowed.")
        self.file_roots.setFixedHeight(80)
        form.addRow("Additional file roots", self.file_roots)
        self.allowed_hosts = QLineEdit(", ".join(settings.allowed_hosts))
        self.allowed_hosts.setPlaceholderText("Empty means any host; e.g. api.openai.com, example.org")
        form.addRow("Allowed hosts", self.allowed_hosts)
        note = QLabel(
            "These limits are enforced by the execution engine. They are guard rails, "
            "not an operating-system sandbox: only run projects you trust."
        )
        note.setWordWrap(True)
        note.setObjectName("subheading")
        form.addRow(note)
        tabs.addTab(security, "Security")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _pick_accent(self) -> None:
        colour = QColorDialog.getColor(QColor(self._accent), self, "Accent colour")
        if colour.isValid():
            self._accent = colour.name()
            self.accent_button.setText(self._accent)
            self.accent_button.setStyleSheet(f"border-left: 12px solid {self._accent};")

    def _apply(self) -> None:
        settings = self.settings
        settings.theme = self.theme.currentText()
        settings.accent = self._accent
        settings.autosave_seconds = int(self.autosave.value())
        settings.run_timeout = float(self.run_timeout.value())
        settings.node_timeout = float(self.node_timeout.value())
        settings.max_steps = int(self.max_steps.value())
        settings.concurrency = int(self.concurrency.value())
        settings.allow_network = self.allow_network.isChecked()
        settings.allow_file_write = self.allow_write.isChecked()
        settings.allow_process = self.allow_process.isChecked()
        settings.allow_scripts = self.allow_scripts.isChecked()
        settings.file_roots = [line.strip() for line in self.file_roots.toPlainText().splitlines() if line.strip()]
        settings.allowed_hosts = [part.strip() for part in self.allowed_hosts.text().split(",") if part.strip()]
        self.accept()
