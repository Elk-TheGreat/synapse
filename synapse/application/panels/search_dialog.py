"""Quick open palette for nodes, graphs and commands."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

from ..theme import category_color


@dataclass
class PaletteEntry:
    label: str
    detail: str
    kind: str
    key: str


def _score(needle: str, haystack: str) -> int:
    if not needle:
        return 1
    haystack = haystack.lower()
    if haystack.startswith(needle):
        return 100 - len(haystack)
    position = haystack.find(needle)
    if position >= 0:
        return 60 - position
    index = 0
    for char in haystack:
        if index < len(needle) and char == needle[index]:
            index += 1
    return 10 if index == len(needle) else 0


class QuickOpenDialog(QDialog):
    def __init__(self, entries: list[PaletteEntry], *, title: str = "Quick open", placeholder: str = "Search…", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(560, 420)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.selected: PaletteEntry | None = None
        self.entries = entries

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        heading = QLabel(title.upper())
        heading.setObjectName("sectionLabel")
        layout.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        layout.addWidget(self.list, 1)
        hint = QLabel("Enter to choose · Esc to close")
        hint.setObjectName("subheading")
        layout.addWidget(hint)

        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._accept_current)
        self.list.itemActivated.connect(lambda _: self._accept_current())
        self.search.setFocus()
        self._filter("")

    def _filter(self, text: str) -> None:
        needle = text.strip().lower()
        scored = []
        for entry in self.entries:
            score = max(_score(needle, entry.label), _score(needle, entry.detail), _score(needle, entry.key) // 2)
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda pair: (-pair[0], pair[1].label.lower()))
        self.list.clear()
        for _, entry in scored[:120]:
            item = QListWidgetItem(f"{entry.label}")
            item.setData(Qt.UserRole, entry)
            item.setToolTip(entry.detail)
            if entry.kind == "node":
                category = entry.detail.split(" · ")[0]
                item.setForeground(Qt.gray)
                item.setToolTip(f"{entry.label}\n{entry.detail}")
            self.list.addItem(item)
            if entry.detail:
                item.setText(f"{entry.label}    {entry.detail}")
        if self.list.count():
            self.list.setCurrentRow(0)

    def _accept_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        self.selected = item.data(Qt.UserRole)
        self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Down, Qt.Key_Up) and self.search.hasFocus():
            self.list.setFocus()
            self.list.keyPressEvent(event)
            self.search.setFocus()
            return
        super().keyPressEvent(event)


def node_entries(registry) -> list[PaletteEntry]:
    entries = []
    for definition in registry.all():
        entries.append(
            PaletteEntry(
                label=definition.name,
                detail=f"{definition.category} · {definition.type_id}",
                kind="node",
                key=definition.type_id,
            )
        )
    return entries
