"""Extension manager: discover, enable, install and remove node packages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...extensions import PluginError, PluginManager


class PluginDialog(QDialog):
    def __init__(self, manager: PluginManager, *, on_changed=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Extensions")
        self.resize(720, 460)
        self.manager = manager
        self.on_changed = on_changed

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Plugins add node categories and nodes. Bundled plugins ship with SYNAPSE; "
            "user plugins live in your application data folder. Plugin Python code runs "
            "in-process, so only install packages you trust."
        )
        intro.setWordWrap(True)
        intro.setObjectName("subheading")
        layout.addWidget(intro)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Plugin", "Version", "Source", "Nodes", "Status"])
        self.tree.setColumnWidth(0, 220)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemChanged.connect(self._item_changed)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        install = QPushButton("Install folder…")
        install.clicked.connect(self._install)
        buttons.addWidget(install)
        install_zip = QPushButton("Install .zip…")
        install_zip.clicked.connect(self._install_zip)
        buttons.addWidget(install_zip)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove)
        buttons.addWidget(self.remove_button)
        reload_button = QPushButton("Rescan")
        reload_button.clicked.connect(self._rescan)
        buttons.addWidget(reload_button)
        buttons.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.accept)
        close.accepted.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self._updating = False
        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        self.tree.clear()
        for record in self.manager.discover():
            manifest = record.manifest
            item = QTreeWidgetItem([
                manifest.title or manifest.name,
                manifest.version,
                record.source,
                str(record.node_count or ""),
                record.error or ("enabled" if record.enabled else "disabled"),
            ])
            item.setData(0, Qt.UserRole, manifest.name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if record.enabled else Qt.Unchecked)
            if record.error:
                item.setForeground(4, Qt.red)
                item.setToolTip(4, record.error)
            item.setToolTip(0, manifest.description or manifest.name)
            self.tree.addTopLevelItem(item)
        self._updating = False

    def _current_name(self) -> str:
        item = self.tree.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else ""

    def _item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._updating or column != 0:
            return
        name = item.data(0, Qt.UserRole)
        enabled = item.checkState(0) == Qt.Checked
        try:
            self.manager.set_enabled(name, enabled)
            self._changed()
        except PluginError as exc:
            QMessageBox.warning(self, "Extensions", str(exc))
        self.refresh()

    def _changed(self) -> None:
        if self.on_changed is not None:
            self.on_changed()

    def _install(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a plugin folder")
        if not folder:
            return
        self._install_path(folder)

    def _install_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a plugin archive", "", "Plugin archive (*.zip)")
        if path:
            self._install_path(path)

    def _install_path(self, path: str) -> None:
        try:
            record = self.manager.install(path)
        except PluginError as exc:
            QMessageBox.warning(self, "Extensions", str(exc))
            return
        self._changed()
        self.refresh()
        QMessageBox.information(self, "Extensions", f"Installed {record.manifest.title or record.manifest.name}.")

    def _remove(self) -> None:
        name = self._current_name()
        if not name:
            return
        if QMessageBox.question(self, "Extensions", f"Remove plugin '{name}'?") != QMessageBox.Yes:
            return
        try:
            self.manager.remove(name)
        except PluginError as exc:
            QMessageBox.warning(self, "Extensions", str(exc))
            return
        self._changed()
        self.refresh()

    def _rescan(self) -> None:
        self._changed()
        self.refresh()
