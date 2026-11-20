"""Edit a reusable function's internal graph."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
)

from ..canvas import GraphScene, GraphView
from ..panels import NodeInspector, NodeLibraryPanel


class FunctionEditorDialog(QDialog):
    def __init__(self, function, registry, *, theme_name: str = "dark", parent=None) -> None:
        super().__init__(parent)
        self.function = function
        self.registry = registry
        self.scene = GraphScene(function.graph, theme_name=theme_name)
        self.view = GraphView(self.scene)

        self.setWindowTitle(f"Function · {function.name}")
        self.resize(1080, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(12, 8, 12, 8)
        title = QLabel(function.name)
        title.setObjectName("heading")
        header.addWidget(title)
        signature = ", ".join(f"{p.name}: {p.spec}" for p in function.inputs)
        returns = ", ".join(f"{p.name}: {p.spec}" for p in function.outputs)
        detail = QLabel(f"({signature}) → ({returns})")
        detail.setObjectName("subheading")
        header.addWidget(detail, 1)
        save = QPushButton("Save function")
        save.setObjectName("primary")
        save.clicked.connect(self._apply)
        header.addWidget(save)
        layout.addLayout(header)

        splitter = QSplitter(Qt.Horizontal)
        self.library_panel = NodeLibraryPanel(registry)
        self.library_panel.node_requested.connect(self._add_node)
        splitter.addWidget(self.library_panel)
        splitter.addWidget(self.view)
        self.inspector = NodeInspector()
        splitter.addWidget(self.inspector)
        splitter.setSizes([240, 620, 280])
        layout.addWidget(splitter, 1)

        self.scene.selection_changed.connect(self._selection_changed)
        self.scene.message.connect(lambda text: self.statusBarText(text))
        self._status = QLabel("Edit the function graph, then save.")
        self._status.setObjectName("subheading")
        layout.addWidget(self._status)
        self.inspector.show_empty(function.graph)

    def statusBarText(self, text: str) -> None:
        self._status.setText(text)

    def _selection_changed(self) -> None:
        nodes = [item.node for item in self.scene.selectedItems() if hasattr(item, "node")]
        if len(nodes) == 1:
            self.inspector.show_node(nodes[0], self.registry.get(nodes[0].type), self.scene.graph)
        else:
            self.inspector.show_empty(self.scene.graph)

    def _add_node(self, type_id: str) -> None:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.add_node(type_id, (center.x() - 100, center.y() - 60))

    def _apply(self) -> None:
        problems = self.function.graph.validate()
        if problems:
            QMessageBox.warning(self, "Function", "Fix these problems first:\n\n" + "\n".join(problems[:8]))
            return
        self.accept()
