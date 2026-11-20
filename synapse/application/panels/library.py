"""Searchable node library panel."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..canvas import MIME_NODE
from ..theme import category_color


class _LibraryTree(QTreeWidget):
    drag_requested = None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setIndentation(12)
        self.setAnimated(True)
        self.setUniformRowHeights(True)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        type_id = item.data(0, Qt.UserRole)
        if not type_id:
            return
        mime = QMimeData()
        mime.setData(MIME_NODE, type_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class NodeLibraryPanel(QWidget):
    node_requested = Signal(str)
    node_preview = Signal(str)

    def __init__(self, registry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(8)

        heading = QLabel("NODE LIBRARY")
        heading.setObjectName("sectionLabel")
        layout.addWidget(heading)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nodes…  (Ctrl+P for quick open)")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.tree = _LibraryTree()
        layout.addWidget(self.tree, 1)

        self.hint = QLabel("Drag a node onto the canvas, or double-click it.")
        self.hint.setObjectName("subheading")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        self.search.textChanged.connect(self._apply_filter)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.currentItemChanged.connect(self._on_current)
        self.reload()

    def reload(self) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        categories: dict[str, list] = {}
        for definition in self.registry.all():
            categories.setdefault(definition.category, []).append(definition)
        for category in sorted(categories):
            parent = QTreeWidgetItem([category])
            parent.setFlags(Qt.ItemIsEnabled)
            font = QFont()
            font.setWeight(QFont.DemiBold)
            parent.setFont(0, font)
            parent.setForeground(0, Qt.GlobalColor.gray)
            self.tree.addTopLevelItem(parent)
            for definition in sorted(categories[category], key=lambda d: d.name):
                child = QTreeWidgetItem([definition.name])
                child.setData(0, Qt.UserRole, definition.type_id)
                child.setToolTip(0, f"{definition.name}\n{definition.type_id}\n\n{definition.description}")
                parent.addChild(child)
            parent.setExpanded(True)
        self.tree.blockSignals(False)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            visible_children = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                type_id = child.data(0, Qt.UserRole) or ""
                definition = self.registry.get(type_id)
                haystack = " ".join(
                    [
                        child.text(0),
                        type_id,
                        definition.description if definition else "",
                        " ".join(definition.keywords) if definition else "",
                    ]
                ).lower()
                match = not needle or needle in haystack
                child.setHidden(not match)
                visible_children += int(match)
            parent.setHidden(visible_children == 0)
            if needle and visible_children:
                parent.setExpanded(True)

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            self.node_requested.emit(type_id)

    def _on_current(self, current: QTreeWidgetItem | None, previous) -> None:
        if current is not None:
            type_id = current.data(0, Qt.UserRole)
            if type_id:
                self.node_preview.emit(type_id)
