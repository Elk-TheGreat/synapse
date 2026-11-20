"""Welcome screen: new project, recent projects and templates."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

TEMPLATE_CARDS = [
    ("Blank", "An empty canvas", "Start from nothing and build your own graph."),
    ("Arithmetic", "Arithmetic", "Constants, math and a graph output wired together."),
    ("Function", "Reusable function", "Extract logic into a function and call it."),
    ("Loop", "For loop", "Accumulate results through a function body."),
    ("JSON", "JSON query", "Parse structured data and select a field."),
    ("Python Script", "Python script", "Send data into a sandboxed script node."),
]


class TemplateCard(QFrame):
    chosen = Signal(str)

    def __init__(self, template: str, title: str, detail: str, parent=None) -> None:
        super().__init__(parent)
        self.template = template
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        layout.addWidget(heading)
        body = QLabel(detail)
        body.setWordWrap(True)
        body.setObjectName("subheading")
        layout.addWidget(body)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.chosen.emit(self.template)
        super().mouseReleaseEvent(event)


class WelcomeScreen(QWidget):
    new_requested = Signal()
    open_requested = Signal()
    template_requested = Signal(str)
    recent_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("welcome")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 40, 48, 40)
        outer.setSpacing(24)

        brand = QLabel("SYNAPSE")
        brand.setObjectName("brand")
        subtitle = QLabel("Universal visual programming environment")
        subtitle.setObjectName("brandSubtitle")
        tagline = QLabel(
            "Build programs by connecting typed nodes · debug them as they run · "
            "step down to Python when you need it."
        )
        tagline.setWordWrap(True)
        tagline.setObjectName("subheading")
        outer.addWidget(brand)
        outer.addWidget(subtitle)
        outer.addWidget(tagline)

        columns = QHBoxLayout()
        columns.setSpacing(32)
        left = QVBoxLayout()
        left.setSpacing(10)
        new_button = QPushButton("New project…")
        new_button.setObjectName("primary")
        new_button.clicked.connect(self.new_requested)
        left.addWidget(new_button)
        open_button = QPushButton("Open project…")
        open_button.clicked.connect(self.open_requested)
        left.addWidget(open_button)
        recent_label = QLabel("RECENT PROJECTS")
        recent_label.setObjectName("sectionLabel")
        left.addSpacing(12)
        left.addWidget(recent_label)
        self.recent = QListWidget()
        self.recent.setObjectName("recent")
        self.recent.itemActivated.connect(self._recent_activated)
        left.addWidget(self.recent, 1)
        columns.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(10)
        templates_label = QLabel("TEMPLATES")
        templates_label.setObjectName("sectionLabel")
        right.addWidget(templates_label)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        for index, (template, title, detail) in enumerate(TEMPLATE_CARDS):
            card = TemplateCard(template, title, detail)
            card.chosen.connect(self.template_requested)
            grid.addWidget(card, index // 2, index % 2)
        scroll.setWidget(holder)
        right.addWidget(scroll, 1)
        columns.addLayout(right, 1)
        outer.addLayout(columns, 1)

        footer = QLabel("Tip: press Ctrl+K to jump to any node · Ctrl+Enter runs the graph")
        footer.setObjectName("subheading")
        outer.addWidget(footer)

    def set_recent(self, rows: list[dict]) -> None:
        self.recent.clear()
        for row in rows:
            path = row.get("path") or ""
            if not os.path.exists(path):
                continue
            item = QListWidgetItem(row.get("name") or os.path.basename(path))
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            self.recent.addItem(item)
        if self.recent.count() == 0:
            item = QListWidgetItem("No recent projects yet")
            item.setFlags(Qt.NoItemFlags)
            self.recent.addItem(item)

    def _recent_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self.recent_requested.emit(path)
