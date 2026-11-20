"""Main application window: docks, menus, project lifecycle and run control."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..compiler import CompileError, generate_json, generate_python
from ..extensions import PluginError, PluginManager
from ..functions.extract import ExtractionError, extract_function
from ..graph.model import Graph, new_id
from ..nodes.registry import create_registry
from ..project import (
    PROJECT_SUFFIX,
    AppDatabase,
    Project,
    ProjectError,
    ProjectStore,
    TEMPLATES,
    create_project,
    default_database,
)
from .canvas import GraphScene, GraphView, MinimapWidget
from .dialogs import (
    FunctionDialog,
    NewProjectDialog,
    PluginDialog,
    RunInputsDialog,
    SettingsDialog,
)
from .panels import (
    DebuggerPanel,
    ExecutionConsole,
    NodeInspector,
    NodeLibraryPanel,
    QuickOpenDialog,
    node_entries,
)
from .run_controller import RunController, make_executor, options_from_settings
from .theme import DEFAULT_ACCENT, get_theme, set_active_accent, stylesheet
from .welcome import WelcomeScreen

APP_NAME = "SYNAPSE"
SHORTCUT_HELP = """\
File: Ctrl+N new · Ctrl+O open · Ctrl+S save · Ctrl+Shift+S save as
Graph: Ctrl+K quick open · Ctrl+L auto layout · Ctrl+Alt+F to function · Ctrl+Enter run
Edit: Ctrl+Z undo · Ctrl+Shift+Z redo · Ctrl+C/V copy/paste · Del delete
View: Ctrl+= zoom in · Ctrl+- zoom out · Ctrl+0 reset · Ctrl+Shift+F fit
Run: F5 debug · F6 pause · F10 step · Shift+F5 stop
"""


class MainWindow(QMainWindow):
    def __init__(self, database: AppDatabase | None = None) -> None:
        super().__init__()
        self.db = database or default_database()
        self.store = ProjectStore(self.db)
        self.plugins = PluginManager(self.db)
        self.registry = create_registry()
        self.plugins.discover()
        self.plugins.load_enabled(self.registry)

        self.project: Project | None = None
        self.library = None
        self.executor = None
        self.scene: GraphScene | None = None
        self.view: GraphView | None = None
        self.minimap: MinimapWidget | None = None
        self.current_graph_id: str = ""
        self.dirty = False
        self._loading = False
        self._cameras: dict[str, tuple[QPointF, float]] = {}
        self._last_run_graph: str = ""

        self.runner = RunController(self)
        self.runner.started.connect(self._run_started)
        self.runner.event.connect(self._run_event)
        self.runner.node_traced.connect(self._node_traced)
        self.runner.paused.connect(self._run_paused)
        self.runner.resumed.connect(self._run_resumed)
        self.runner.finished.connect(self._run_finished)
        self.runner.failed.connect(self._run_failed)

        self.autosave = QTimer(self)
        self.autosave.timeout.connect(self._autosave)

        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1024, 640)
        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        theme_name = self.db.get("ui.theme", "dark") or "dark"
        accent = self.db.get("ui.accent", DEFAULT_ACCENT) or DEFAULT_ACCENT
        self._apply_theme(theme_name, accent)
        self._update_recent()
        self.show_welcome()
        QTimer.singleShot(120, self._check_recovery)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.welcome = WelcomeScreen()
        self.welcome.new_requested.connect(lambda: self.new_project())
        self.welcome.open_requested.connect(lambda: self.open_project())
        self.welcome.template_requested.connect(lambda t: self.new_project(template=t))
        self.welcome.recent_requested.connect(self.open_project)
        self.stack.addWidget(self.welcome)

        self.canvas_host = QWidget()
        layout = QVBoxLayout(self.canvas_host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(8, 6, 8, 0)
        bar_row.setSpacing(6)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabCloseRequested.connect(self._close_graph)
        self.tabs.tabBarDoubleClicked.connect(self._rename_graph)
        bar_row.addWidget(self.tabs, 1)
        add = QToolButton()
        add.setText("+")
        add.setToolTip("New graph")
        add.clicked.connect(self.add_graph)
        bar_row.addWidget(add)
        layout.addLayout(bar_row)
        self.canvas_slot = QWidget()
        self.canvas_layout = QVBoxLayout(self.canvas_slot)
        self.canvas_layout.setContentsMargins(0, 0, 0, 0)
        empty = QLabel("Open or create a project to start.")
        empty.setAlignment(Qt.AlignCenter)
        empty.setObjectName("subheading")
        self.canvas_layout.addWidget(empty)
        layout.addWidget(self.canvas_slot, 1)
        self.stack.addWidget(self.canvas_host)

        # docks ---------------------------------------------------------
        self.library_panel = NodeLibraryPanel(self.registry)
        self.library_panel.node_requested.connect(self._add_node_from_library)
        self.library_dock = self._dock("Node library", self.library_panel, Qt.LeftDockWidgetArea)

        self.inspector = NodeInspector()
        self._connect_inspector()
        self.inspector_dock = self._dock("Inspector", self.inspector, Qt.RightDockWidgetArea)

        self.console = ExecutionConsole()
        self.console.node_selected.connect(self._select_node)
        self.console_dock = self._dock("Execution console", self.console, Qt.BottomDockWidgetArea)

        self.debugger_panel = DebuggerPanel()
        self.debugger_panel.node_selected.connect(self._select_node)
        self.debugger_panel.resume_requested.connect(self.runner.resume)
        self.debugger_panel.pause_requested.connect(self.runner.pause)
        self.debugger_panel.step_requested.connect(self.runner.step)
        self.debugger_panel.stop_requested.connect(self.stop_run)
        self.debugger_dock = self._dock("Debugger", self.debugger_panel, Qt.BottomDockWidgetArea)
        self.tabifyDockWidget(self.console_dock, self.debugger_dock)

        self.minimap_dock = QDockWidget("Minimap", self)
        self.minimap_dock.setObjectName("dock.minimap")
        self.minimap_dock.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.minimap_placeholder = QLabel("No graph open")
        self.minimap_placeholder.setAlignment(Qt.AlignCenter)
        self.minimap_placeholder.setObjectName("subheading")
        self.minimap_dock.setWidget(self.minimap_placeholder)
        self.addDockWidget(Qt.RightDockWidgetArea, self.minimap_dock)
        self.splitDockWidget(self.inspector_dock, self.minimap_dock, Qt.Vertical)
        self.resizeDocks([self.inspector_dock, self.minimap_dock], [500, 170], Qt.Vertical)

        for dock in (self.library_dock, self.inspector_dock, self.console_dock, self.debugger_dock, self.minimap_dock):
            dock.hide()

    def _dock(self, title: str, widget: QWidget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName("dock." + title.lower().replace(" ", "_"))
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    def _connect_inspector(self) -> None:
        self.inspector.param_changed.connect(self._param_changed)
        self.inspector.label_changed.connect(self._label_changed)
        self.inspector.notes_changed.connect(self._notes_changed)
        self.inspector.flag_changed.connect(self._flag_changed)
        self.inspector.breakpoint_requested.connect(self._toggle_breakpoint)
        self.inspector.delete_requested.connect(self._delete_nodes)
        self.inspector.convert_requested.connect(self.convert_selection)
        self.inspector.graph_meta_changed.connect(self._graph_meta_changed)
        self.inspector.edit_function_requested.connect(self.edit_function)

    def _action(self, text: str, slot, shortcut: str | None = None, *, icon=None, checkable=False) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.ApplicationShortcut)
        action.setCheckable(checkable)
        # triggered (not toggled) so unchecking a theme action does not re-apply the other one.
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        style = self.style()
        self.act_new = self._action("New project…", lambda: self.new_project(), "Ctrl+N", icon=style.StandardPixmap.SP_FileIcon)
        self.act_open = self._action("Open project…", lambda: self.open_project(), "Ctrl+O", icon=style.StandardPixmap.SP_DirOpenIcon)
        self.act_save = self._action("Save", lambda: self.save_project(), "Ctrl+S", icon=style.StandardPixmap.SP_DialogSaveButton)
        self.act_save_as = self._action("Save as…", lambda: self.save_project(save_as=True), "Ctrl+Shift+S")
        self.act_import = self._action("Import graph…", self.import_graph, "Ctrl+Shift+O")
        self.act_export_json = self._action("Export graph as JSON…", self.export_json)
        self.act_export_python = self._action("Export graph as Python…", self.export_python)
        self.act_exit = self._action("Exit", self.close, "Ctrl+Q")

        self.act_undo = self._action("Undo", lambda: self.scene and self.scene.undo(), "Ctrl+Z", icon=style.StandardPixmap.SP_ArrowBack)
        self.act_redo = self._action("Redo", lambda: self.scene and self.scene.redo(), "Ctrl+Shift+Z", icon=style.StandardPixmap.SP_ArrowForward)
        self.act_cut = self._action("Cut", lambda: self._copy(cut=True), "Ctrl+X")
        self.act_copy = self._action("Copy", lambda: self._copy(), "Ctrl+C")
        self.act_paste = self._action("Paste", lambda: self._paste(), "Ctrl+V")
        self.act_duplicate = self._action("Duplicate", lambda: self.scene and self.scene.duplicate_selection(), "Ctrl+D")
        self.act_delete = self._action("Delete", lambda: self.scene and self.scene.delete_selection(), "Del")
        self.act_select_all = self._action("Select all", lambda: self.scene and self.scene.select_all_nodes(), "Ctrl+A")
        self.act_find = self._action("Quick open…", self.quick_open, "Ctrl+K")
        self.act_function = self._action("Convert selection to function…", self.convert_selection, "Ctrl+Alt+F")
        self.act_add_function = self._action("Add function…", self.add_function_node)
        self.act_layout = self._action("Auto layout", lambda: self.scene and self.scene.auto_layout(), "Ctrl+L")
        self.act_group = self._action("Group selection", lambda: self.scene and self.scene.group_selection(), "Ctrl+G")
        self.act_annotate = self._action("Add annotation", lambda: self.scene and self.scene.group_selection(annotation=True), "Ctrl+Shift+A")

        self.act_run = self._action("Run", lambda: self.run_graph(debug=False), "Ctrl+Return", icon=style.StandardPixmap.SP_MediaPlay)
        self.act_debug = self._action("Debug", lambda: self.run_graph(debug=True), "F5", icon=style.StandardPixmap.SP_MediaPlay)
        self.act_pause = self._action("Pause", self.runner.pause, "F6", icon=style.StandardPixmap.SP_MediaPause)
        self.act_step = self._action("Step", self.runner.step, "F10")
        self.act_stop = self._action("Stop", self.stop_run, "Shift+F5", icon=style.StandardPixmap.SP_MediaStop)
        self.act_clear_console = self._action("Clear console", self.console.clear, "Ctrl+Shift+K")

        self.act_zoom_in = self._action("Zoom in", lambda: self.view and self.view.zoom_by(1.2), "Ctrl+=")
        self.act_zoom_out = self._action("Zoom out", lambda: self.view and self.view.zoom_by(1 / 1.2), "Ctrl+-")
        self.act_zoom_reset = self._action("Reset zoom", lambda: self.view and self.view.reset_zoom(), "Ctrl+0")
        self.act_zoom_fit = self._action("Zoom to fit", lambda: self.view and self.view.zoom_to_fit(), "Ctrl+Shift+F")
        self.act_settings = self._action("Project settings…", self.open_settings, "Ctrl+,")
        self.act_plugins = self._action("Extensions…", self.open_plugins)
        self.act_shortcuts = self._action("Keyboard shortcuts", self.show_shortcuts, "F1")
        self.act_about = self._action("About SYNAPSE", self.show_about)

        theme_group = QActionGroup(self)
        self.act_dark = self._action("Dark theme", lambda: self.set_theme("dark"), checkable=True)
        self.act_light = self._action("Light theme", lambda: self.set_theme("light"), checkable=True)
        for action in (self.act_dark, self.act_light):
            theme_group.addAction(action)
        self.act_dark.setChecked(True)
        self.act_accent = self._action("Accent colour…", self.choose_accent)

        self.act_new_graph = self._action("New graph", self.add_graph, "Ctrl+Shift+N")
        self.act_rename_graph = self._action("Rename graph…", lambda: self._rename_graph(self.tabs.currentIndex()))
        self.act_delete_graph = self._action("Delete graph", lambda: self._close_graph(self.tabs.currentIndex()))

    def _build_menus(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")
        for action in (self.act_new, self.act_open, self.act_save, self.act_save_as):
            file_menu.addAction(action)
        file_menu.addSeparator()
        templates = file_menu.addMenu("New from template")
        for template in TEMPLATES:
            templates.addAction(template, lambda t=template: self.new_project(template=t))
        file_menu.addSeparator()
        file_menu.addAction(self.act_import)
        file_menu.addAction(self.act_export_json)
        file_menu.addAction(self.act_export_python)
        file_menu.addSeparator()
        self.recent_menu = file_menu.addMenu("Recent projects")
        file_menu.addSeparator()
        file_menu.addAction(self.act_exit)

        edit_menu = bar.addMenu("&Edit")
        for action in (self.act_undo, self.act_redo):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (self.act_cut, self.act_copy, self.act_paste, self.act_duplicate, self.act_delete, self.act_select_all):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_find)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_function)
        edit_menu.addAction(self.act_add_function)
        edit_menu.addAction(self.act_layout)
        edit_menu.addAction(self.act_group)
        edit_menu.addAction(self.act_annotate)

        graph_menu = bar.addMenu("&Graph")
        for action in (self.act_new_graph, self.act_rename_graph, self.act_delete_graph):
            graph_menu.addAction(action)

        run_menu = bar.addMenu("&Run")
        for action in (self.act_run, self.act_debug, self.act_pause, self.act_step, self.act_stop):
            run_menu.addAction(action)
        run_menu.addSeparator()
        run_menu.addAction(self.act_clear_console)
        run_menu.addAction(self.act_settings)

        view_menu = bar.addMenu("&View")
        for action in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset, self.act_zoom_fit):
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self.library_dock.toggleViewAction())
        view_menu.addAction(self.inspector_dock.toggleViewAction())
        view_menu.addAction(self.console_dock.toggleViewAction())
        view_menu.addAction(self.debugger_dock.toggleViewAction())
        view_menu.addAction(self.minimap_dock.toggleViewAction())
        view_menu.addSeparator()
        appearance = view_menu.addMenu("Appearance")
        appearance.addAction(self.act_dark)
        appearance.addAction(self.act_light)
        appearance.addAction(self.act_accent)

        project_menu = bar.addMenu("&Project")
        project_menu.addAction(self.act_settings)
        project_menu.addAction(self.act_plugins)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_shortcuts)
        help_menu.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(16, 16))
        for action in (self.act_new, self.act_open, self.act_save):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.act_undo)
        toolbar.addAction(self.act_redo)
        toolbar.addSeparator()
        toolbar.addAction(self.act_run)
        toolbar.addAction(self.act_debug)
        toolbar.addAction(self.act_stop)
        toolbar.addSeparator()
        toolbar.addAction(self.act_layout)
        toolbar.addAction(self.act_find)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

    def _build_statusbar(self) -> None:
        self.status_message = QLabel("Ready")
        self.status_run = QLabel("idle")
        self.status_zoom = QLabel("100%")
        self.status_count = QLabel("")
        bar = self.statusBar()
        bar.addWidget(self.status_message, 1)
        bar.addPermanentWidget(self.status_count)
        bar.addPermanentWidget(self.status_run)
        bar.addPermanentWidget(self.status_zoom)

    # ------------------------------------------------------------------
    # theme
    # ------------------------------------------------------------------
    def _apply_theme(self, name: str, accent: str | None = None) -> None:
        accent = accent or DEFAULT_ACCENT
        set_active_accent(accent)
        self.theme_name = name if name in ("dark", "light") else "dark"
        self.setStyleSheet(stylesheet(get_theme(self.theme_name), accent))
        self.act_dark.setChecked(self.theme_name == "dark")
        self.act_light.setChecked(self.theme_name == "light")
        self.db.set("ui.theme", self.theme_name)
        self.db.set("ui.accent", accent)
        if self.scene is not None:
            self._rebuild_scene_theme()

    def _rebuild_scene_theme(self) -> None:
        if self.scene is None:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center()) if self.view else QPointF()
        zoom = self.view.zoom_level() if self.view else 1.0
        self.scene.theme_name = self.theme_name
        self.scene.setBackgroundBrush(QColor(get_theme(self.theme_name).canvas))
        self.scene.rebuild()
        if self.view is not None:
            self.view.resetCachedContent()
            self.view.centerOn(center)
            self.view.zoom_by(zoom / self.view.zoom_level())

    def set_theme(self, name: str) -> None:
        self._apply_theme(name, self._current_accent())
        if self.project is not None:
            self.project.settings.theme = name
            self._mark_dirty()

    def _current_accent(self) -> str:
        if self.project is not None:
            return self.project.settings.accent
        return self.db.get("ui.accent", DEFAULT_ACCENT) or DEFAULT_ACCENT

    def choose_accent(self) -> None:
        from PySide6.QtWidgets import QColorDialog

        colour = QColorDialog.getColor(QColor(self._current_accent()), self, "Accent colour")
        if not colour.isValid():
            return
        value = colour.name()
        self._apply_theme(self.theme_name, value)
        if self.project is not None:
            self.project.settings.accent = value
            self._mark_dirty()


    # ------------------------------------------------------------------
    # project lifecycle
    # ------------------------------------------------------------------
    def show_welcome(self) -> None:
        self.stack.setCurrentWidget(self.welcome)
        for dock in (self.library_dock, self.inspector_dock, self.console_dock, self.debugger_dock, self.minimap_dock):
            dock.hide()
        self._update_recent()
        self._set_project_actions(False)
        self.setWindowTitle(f"{APP_NAME} — visual programming environment")

    def _set_project_actions(self, enabled: bool) -> None:
        for action in (
            self.act_save, self.act_save_as, self.act_import, self.act_export_json,
            self.act_export_python, self.act_run, self.act_debug, self.act_find,
            self.act_layout, self.act_new_graph, self.act_settings,
            self.act_undo, self.act_redo, self.act_cut, self.act_copy, self.act_paste,
            self.act_duplicate, self.act_delete, self.act_select_all, self.act_function,
            self.act_add_function, self.act_group, self.act_annotate,
        ):
            action.setEnabled(enabled)

    def _update_recent(self) -> None:
        rows = self.db.recent(10)
        self.welcome.set_recent(rows)
        self.recent_menu.clear()
        if not rows:
            action = self.recent_menu.addAction("No recent projects")
            action.setEnabled(False)
            return
        for row in rows:
            name = row.get("name") or os.path.basename(row.get("path", ""))
            action = self.recent_menu.addAction(name)
            action.setToolTip(row.get("path", ""))
            action.triggered.connect(lambda _=False, p=row.get("path", ""): self.open_project(p))

    def _check_recovery(self) -> None:
        recoveries = self.store.recoveries()
        if not recoveries:
            return
        item = recoveries[0]
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(item.get("saved_at") or 0))
        answer = QMessageBox.question(
            self,
            "Recover unsaved work",
            f"SYNAPSE found unsaved changes for “{item.get('name')}” from {stamp}.\n\nRecover them?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            try:
                project = self.store.load_recovery(item["snapshot"], registry=self.registry)
            except (ProjectError, OSError) as exc:
                QMessageBox.warning(self, "Recovery failed", str(exc))
                return
            self._load_project(project, path=item.get("path"))
            self._mark_dirty()
            self.status_message.setText(f"Recovered unsaved changes from {stamp}")
        else:
            self.store.discard_recovery(item["snapshot"])

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "This project has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save_project()
        return True

    def new_project(self, template: str = "", name: str = "", directory: str = "") -> None:
        if self.runner.is_running() and not self._confirm_stop():
            return
        if not self._confirm_discard():
            return
        if not name:
            dialog = NewProjectDialog(default_dir=directory or str(Path.home()), parent=self)
            if dialog.exec() != dialog.Accepted:
                return
            template, name, directory = dialog.template, dialog.project_name, dialog.directory
        template = template or "Blank"
        try:
            project = create_project(template, self.registry)
        except KeyError as exc:
            QMessageBox.warning(self, "New project", str(exc))
            return
        project.name = name
        project.bind_registry(self.registry)
        path = None
        if directory:
            path = str(Path(directory).expanduser() / f"{name}{PROJECT_SUFFIX}")
            if Path(path).exists():
                QMessageBox.warning(self, "New project", f"{path} already exists. Choose another name or folder.")
                return
        self._load_project(project, path=path)
        if path:
            self.store.save(self.project, path)
            self.db.add_recent(path, self.project.name)
            self._set_dirty(False)
        else:
            self._mark_dirty()
        self.status_message.setText(f"Created “{project.name}” from the {template} template")

    def open_project(self, path: str | None = None) -> None:
        if self.runner.is_running() and not self._confirm_stop():
            return
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open project", str(Path.home()), f"SYNAPSE project (*{PROJECT_SUFFIX});;All files (*)"
            )
        if not path:
            return
        try:
            project = self.store.load(path, registry=self.registry)
        except ProjectError as exc:
            QMessageBox.warning(self, "Open project", str(exc))
            self.db.remove_recent(path)
            self._update_recent()
            return
        self._load_project(project, path=str(Path(path).expanduser().resolve()))
        self.db.add_recent(project.path or path, project.name)
        self._update_recent()
        self.status_message.setText(f"Opened {project.name}")

    def _load_project(self, project: Project, *, path: str | None = None) -> None:
        self._loading = True
        try:
            self.registry = create_registry()
            self.plugins.discover()
            self.plugins.load_enabled(self.registry)
            project.bind_registry(self.registry)
            project.path = path or project.path
            self.project = project
            self.library = project.function_library(self.registry)
            self.library_panel.registry = self.registry
            self.library_panel.reload()
            self._cameras.clear()
            self.current_graph_id = project.main_graph.id
            self._build_canvas()
            self._rebuild_tabs()
            self.stack.setCurrentWidget(self.canvas_host)
            for dock in (self.library_dock, self.inspector_dock, self.console_dock, self.minimap_dock):
                dock.show()
            self.console.clear()
            self.debugger_panel.clear()
            self._apply_theme(project.settings.theme, project.settings.accent)
            self.autosave.start(max(5, int(project.settings.autosave_seconds)) * 1000)
            self._set_dirty(False)
            self._set_project_actions(True)
            self._update_title()
            if self.tabs.count():
                self.tabs.setCurrentIndex(0)
                self._tab_changed(0)
            self._update_counts()
        finally:
            self._loading = False

    def _build_canvas(self) -> None:
        while self.canvas_layout.count():
            item = self.canvas_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.view = None
        self.scene = None
        self.minimap = None
        if self.project is None:
            return
        graph = self.project.graphs.get(self.current_graph_id) or self.project.main_graph
        scene = GraphScene(graph, theme_name=self.theme_name)
        view = GraphView(scene)
        scene.changed.connect(self._scene_changed)
        scene.selection_changed.connect(self._selection_changed)
        scene.message.connect(self._scene_message)
        scene.request_convert_to_function.connect(self.convert_selection)
        scene.request_add_function.connect(self.add_function_node)
        view.zoom_changed.connect(lambda z: self.status_zoom.setText(f"{int(round(z * 100))}%"))
        view.node_double_clicked.connect(self._focus_node)
        self.scene = scene
        self.view = view
        self.canvas_layout.addWidget(view)
        self.minimap = MinimapWidget(scene, view)
        self.minimap_dock.setWidget(self.minimap)
        self.inspector.show_empty(graph)
        view.setFocus()

    def _rebuild_tabs(self) -> None:
        self.tabs.blockSignals(True)
        while self.tabs.count():
            self.tabs.removeTab(0)
        if self.project is not None:
            for graph in self.project.graphs.values():
                index = self.tabs.addTab(graph.name)
                self.tabs.setTabData(index, graph.id)
                self.tabs.setTabToolTip(index, f"{graph.name} · {len(graph.nodes)} nodes")
        self.tabs.blockSignals(False)

    def _tab_changed(self, index: int) -> None:
        if self._loading or index < 0 or self.project is None:
            return
        graph_id = self.tabs.tabData(index)
        if not graph_id or graph_id not in self.project.graphs:
            return
        if self.scene is not None and self.view is not None and self.current_graph_id:
            self._cameras[self.current_graph_id] = (
                self.view.mapToScene(self.view.viewport().rect().center()),
                self.view.zoom_level(),
            )
        self.current_graph_id = graph_id
        graph = self.project.graphs[graph_id]
        if self.scene is None:
            self._build_canvas()
        else:
            self.scene.graph = graph
            self.scene.rebuild()
        camera = self._cameras.get(graph_id)
        if camera is not None and self.view is not None:
            self.view.centerOn(camera[0])
            if camera[1]:
                self.view.zoom_by(camera[1] / max(0.01, self.view.zoom_level()))
        self.scene.clearSelection()
        self.inspector.show_empty(graph)
        self._update_counts()

    def _close_graph(self, index: int) -> None:
        if self.project is None or index < 0:
            return
        graph_id = self.tabs.tabData(index)
        if len(self.project.graphs) <= 1:
            QMessageBox.information(self, "Delete graph", "A project needs at least one graph.")
            return
        graph = self.project.graphs.get(graph_id)
        if graph is None:
            return
        if QMessageBox.question(self, "Delete graph", f"Delete graph “{graph.name}” and all its nodes?") != QMessageBox.Yes:
            return
        try:
            self.project.remove_graph(graph_id)
        except ProjectError as exc:
            QMessageBox.warning(self, "Delete graph", str(exc))
            return
        self._cameras.pop(graph_id, None)
        if self.current_graph_id == graph_id:
            self.current_graph_id = ""
        self._rebuild_tabs()
        self._mark_dirty()
        if self.tabs.count():
            self.tabs.setCurrentIndex(0)
            self._tab_changed(0)

    def _rename_graph(self, index: int) -> None:
        if self.project is None or index < 0:
            return
        graph_id = self.tabs.tabData(index)
        graph = self.project.graphs.get(graph_id)
        if graph is None:
            return
        name, ok = QInputDialog.getText(self, "Rename graph", "Graph name", text=graph.name)
        if ok and name.strip():
            self.project.rename_graph(graph_id, name.strip())
            self.tabs.setTabText(index, graph.name)
            self._mark_dirty()

    def add_graph(self) -> None:
        if self.project is None:
            return
        name, ok = QInputDialog.getText(self, "New graph", "Graph name", text=f"Graph {len(self.project.graphs) + 1}")
        if not ok or not name.strip():
            return
        graph = self.project.add_graph(name.strip(), registry=self.registry)
        self._rebuild_tabs()
        index = self.tabs.count() - 1
        self.tabs.setCurrentIndex(index)
        self._tab_changed(index)
        self._mark_dirty()

    def save_project(self, *, save_as: bool = False) -> bool:
        if self.project is None:
            return False
        path = self.project.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save project",
                str(Path(self.project.path or (self.project.name + PROJECT_SUFFIX))),
                f"SYNAPSE project (*{PROJECT_SUFFIX})",
            )
            if not path:
                return False
            if not path.endswith(PROJECT_SUFFIX):
                path += PROJECT_SUFFIX
        try:
            saved = self.store.save(self.project, path)
        except (OSError, ProjectError) as exc:
            QMessageBox.warning(self, "Save project", str(exc))
            return False
        self.project.path = str(saved)
        self.store.clear_recovery(saved)
        self.db.add_recent(saved, self.project.name)
        self._update_recent()
        self._set_dirty(False)
        self._update_title()
        self.status_message.setText(f"Saved {saved.name}")
        return True

    def _autosave(self) -> None:
        if self.project is None or not self.dirty or not self.project.path:
            return
        try:
            self.store.autosave(self.project)
            self.status_message.setText("Autosaved recovery snapshot")
        except OSError as exc:
            self.status_message.setText(f"Autosave failed: {exc}")

    def import_graph(self) -> None:
        if self.project is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import graph", "", "Graph or project (*.json *.synapse)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if data.get("format") == "synapse.project":
                other = Project.from_dict(data, registry=self.registry)
                graph_data = other.main_graph.to_dict()
            elif "graph" in data:
                graph_data = data["graph"]
            else:
                graph_data = data
            graph = Graph.from_dict(graph_data, registry=self.registry)
        except (OSError, ValueError, ProjectError, KeyError) as exc:
            QMessageBox.warning(self, "Import graph", f"Cannot import: {exc}")
            return
        if graph.id in self.project.graphs:
            graph.id = new_id("g_")
        base = graph.name or "Imported"
        name = base
        index = 2
        existing = {g.name for g in self.project.graphs.values()}
        while name in existing:
            name = f"{base} {index}"
            index += 1
        graph.name = name
        graph.set_registry(self.registry)
        self.project.graphs[graph.id] = graph
        self.project.touch()
        self._rebuild_tabs()
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        self._tab_changed(self.tabs.count() - 1)
        self._mark_dirty()

    def export_json(self) -> None:
        graph = self._current_graph()
        if graph is None:
            return
        default = str(Path(graph.name.replace(" ", "_") + ".json"))
        path, _ = QFileDialog.getSaveFileName(self, "Export graph as JSON", default, "JSON (*.json)")
        if not path:
            return
        try:
            payload = generate_json(graph, functions=self.library)
        except CompileError as exc:
            QMessageBox.warning(self, "Export", f"The graph does not compile: {exc}")
            return
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.status_message.setText(f"Exported {path}")

    def export_python(self) -> None:
        graph = self._current_graph()
        if graph is None:
            return
        default = str(Path(graph.name.replace(" ", "_") + ".py"))
        path, _ = QFileDialog.getSaveFileName(self, "Export graph as Python", default, "Python (*.py)")
        if not path:
            return
        try:
            source = generate_python(
                graph,
                functions=self.library,
                module_name=Path(path).stem.replace("-", "_"),
                date=time.strftime("%Y-%m-%d"),
            )
        except CompileError as exc:
            QMessageBox.warning(self, "Export", f"The graph does not compile: {exc}")
            return
        Path(path).write_text(source, encoding="utf-8")
        self.status_message.setText(f"Exported {path}")

    # ------------------------------------------------------------------
    # graph editing
    # ------------------------------------------------------------------
    def _current_graph(self) -> Graph | None:
        if self.project is None or self.scene is None:
            return None
        return self.scene.graph

    def _scene_changed(self) -> None:
        self._mark_dirty()
        if self.minimap is not None:
            self.minimap.update()
        self._update_counts()

    def _scene_message(self, text: str) -> None:
        self.status_message.setText(text)

    def _selection_changed(self) -> None:
        if self.scene is None:
            return
        nodes = [item.node for item in self.scene.selectedItems() if hasattr(item, "node")]
        if len(nodes) == 1:
            node = nodes[0]
            self.inspector.show_node(node, self.registry.get(node.type), self.scene.graph)
        else:
            self.inspector.show_empty(self.scene.graph)
        self._update_actions()

    def _update_actions(self) -> None:
        has_selection = bool(self.scene and self.scene.selected_node_ids())
        for action in (self.act_cut, self.act_copy, self.act_duplicate, self.act_function, self.act_group):
            action.setEnabled(bool(self.project) and has_selection)

    def _update_counts(self) -> None:
        if self.scene is None:
            self.status_count.setText("")
            return
        graph = self.scene.graph
        self.status_count.setText(f"{len(graph.nodes)} nodes · {len(graph.edges)} wires")

    def _update_title(self) -> None:
        if self.project is None:
            self.setWindowTitle(APP_NAME)
            return
        marker = "• " if self.dirty else ""
        where = self.project.path or "unsaved"
        self.setWindowTitle(f"{marker}{self.project.name} — {where} — {APP_NAME}")

    def _mark_dirty(self) -> None:
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self._update_title()

    def _param_changed(self, node_id: str, name: str, value) -> None:
        if self.scene is None:
            return
        rebuild = name in {"value_type", "variable_type", "from_type", "to_type", "mode"}
        self.scene.set_param(node_id, name, value, rebuild=rebuild)
        node = self.scene.graph.nodes.get(node_id)
        if node is not None:
            self.inspector.show_node(node, self.registry.get(node.type), self.scene.graph)

    def _label_changed(self, node_id: str, label: str) -> None:
        if self.scene is None or node_id not in self.scene.graph.nodes:
            return
        self.scene.set_node_field(node_id, "label", label, "Rename node")
        node = self.scene.graph.nodes[node_id]
        self.inspector.show_node(node, self.registry.get(node.type), self.scene.graph)

    def _notes_changed(self, node_id: str, notes: str) -> None:
        if self.scene is not None:
            self.scene.set_node_field(node_id, "notes", notes, "Edit node notes")

    def _flag_changed(self, node_id: str, flag: str, value: bool) -> None:
        if self.scene is not None:
            self.scene.set_node_flag(node_id, flag, value)

    def _toggle_breakpoint(self, node_id: str) -> None:
        if self.scene is None:
            return
        active = self.scene.toggle_breakpoint(node_id)
        self.status_message.setText(f"Breakpoint {'set' if active else 'removed'} on {node_id}")
        node = self.scene.graph.nodes.get(node_id)
        if node is not None:
            self.inspector.show_node(node, self.registry.get(node.type), self.scene.graph)

    def _delete_nodes(self, node_ids: list[str]) -> None:
        if self.scene is None:
            return
        self.scene.clearSelection()
        for node_id in node_ids:
            item = self.scene.node_items.get(node_id)
            if item is not None:
                item.setSelected(True)
        self.scene.delete_selection()

    def _graph_meta_changed(self, name: str, description: str) -> None:
        if self.scene is None:
            return
        graph = self.scene.graph
        if graph.name == name and graph.description == description:
            return
        graph.name = name
        graph.description = description
        index = self.tabs.currentIndex()
        if index >= 0:
            self.tabs.setTabText(index, name)
        self.project.touch()
        self._mark_dirty()

    def _add_node_from_library(self, type_id: str) -> None:
        if self.scene is None or self.view is None:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.add_node(type_id, (center.x() - 100, center.y() - 60))

    def _select_node(self, node_id: str) -> None:
        if self.scene is not None:
            self.scene.select_node(node_id)
            self.scene.clear_run_state()

    def _focus_node(self, node_id: str) -> None:
        self._select_node(node_id)

    def _copy(self, *, cut: bool = False) -> None:
        if self.scene is not None:
            self.scene.copy_selection()
            if cut:
                self.scene.delete_selection()

    def _paste(self) -> None:
        if self.scene is None or self.view is None:
            return
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.paste(center)

    def quick_open(self) -> None:
        dialog = QuickOpenDialog(node_entries(self.registry), parent=self)
        if dialog.exec() == QuickOpenDialog.Accepted and dialog.selected is not None:
            self._add_node_from_library(dialog.selected.key)

    def show_shortcuts(self) -> None:
        QMessageBox.information(self, "Keyboard shortcuts", SHORTCUT_HELP)
    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def _confirm_stop(self) -> bool:
        return QMessageBox.question(
            self, "Execution running", "Stop the current run?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        ) == QMessageBox.Yes

    def run_graph(self, *, debug: bool = False) -> None:
        if self.project is None or self.scene is None:
            return
        if self.runner.is_running():
            QMessageBox.information(self, "SYNAPSE", "A run is already in progress.")
            return
        graph = self.scene.graph
        problems = graph.validate()
        if problems:
            self.console.log("Graph validation failed:", "error")
            for problem in problems[:20]:
                self.console.log(f"  • {problem}", "error")
            self.console_dock.show()
            self.console.raise_()
            QMessageBox.warning(self, "Cannot run", "The graph is not valid:\n\n" + "\n".join(problems[:8]))
            return
        inputs: dict = {}
        if graph.inputs:
            dialog = RunInputsDialog(graph.inputs, graph_name=graph.name, parent=self)
            if dialog.exec() != dialog.Accepted:
                return
            inputs = dialog.values
        breakpoints = {graph.id: set(self.scene.breakpoints)} if self.scene.breakpoints else {}
        try:
            executor = make_executor(self.registry, self.library, self.project.settings, self.project.path)
        except (TypeError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot run", str(exc))
            return
        self.executor = executor
        self.scene.clear_run_state()
        self.console.show_started(graph.name, debug)
        self.debugger_panel.clear()
        self.debugger_panel.set_debugging(debug)
        if debug:
            self.debugger_dock.show()
            self.debugger_dock.raise_()
        self._last_run_graph = graph.id
        self.status_run.setText("debugging" if debug else "running")
        started = self.runner.start(
            executor,
            graph,
            inputs=inputs,
            options=options_from_settings(self.project.settings),
            debug=debug,
            breakpoints=breakpoints,
        )
        if not started:
            self.status_run.setText("idle")
        self._update_run_actions()

    def stop_run(self) -> None:
        if not self.runner.is_running():
            return
        self.runner.stop()
        self.status_run.setText("stopping…")
        self.console.log("Stop requested", "warn")

    def _update_run_actions(self) -> None:
        running = self.runner.is_running()
        debugging = running and self.runner.debug_active
        self.act_run.setEnabled(bool(self.project) and not running)
        self.act_debug.setEnabled(bool(self.project) and not running)
        self.act_stop.setEnabled(running)
        self.act_pause.setEnabled(debugging)
        self.act_step.setEnabled(debugging)

    def _run_started(self, graph_name: str, debug: bool) -> None:
        self.status_message.setText(f"{'Debugging' if debug else 'Running'} {graph_name}")
        self._update_run_actions()

    def _run_event(self, event) -> None:
        self.console.handle_event(event)
        if self.scene is None or event.graph_id != self.scene.graph.id:
            return
        if event.kind == "node_start":
            self.scene.set_active_node(event.node_id)
        elif event.kind in ("node_finish", "node_error", "node_skipped"):
            self.scene.set_active_node(None)
        elif event.kind == "debug_pause":
            self.scene.set_active_node(event.node_id)
            self.scene.select_node(event.node_id)
        if self.minimap is not None:
            self.minimap.update()

    def _node_traced(self, entry) -> None:
        self.debugger_panel.add_trace(entry)

    def _run_paused(self, node_id: str, node_name: str, inputs: dict) -> None:
        self.status_run.setText("paused")
        self.debugger_panel.paused(node_id, node_name, inputs)
        if self.scene is not None:
            self.scene.select_node(node_id)
        self._update_run_actions()

    def _run_resumed(self) -> None:
        self.status_run.setText("debugging")
        self._update_run_actions()

    def _run_finished(self, result) -> None:
        self.status_run.setText("idle")
        self.console.show_result(result)
        self.debugger_panel.finished(result)
        if self.scene is not None and self._last_run_graph == self.scene.graph.id:
            self.scene.apply_run_result(result)
        state = "failed" if result.errors else "finished"
        self.status_message.setText(f"Run {state} · {result.summary()}")
        self.console.log(
            f"Run {state} · {result.summary()}", "error" if result.errors else "ok"
        )
        if result.errors:
            self.console_dock.show()
            self.console_dock.raise_()
        self._update_run_actions()
        if self.minimap is not None:
            self.minimap.update()

    def _run_failed(self, message: str) -> None:
        self.status_run.setText("idle")
        self.console.log(message, "error")
        self.console_dock.show()
        self.console_dock.raise_()
        self.status_message.setText("Run crashed; see the execution console")
        self._update_run_actions()

    # ------------------------------------------------------------------
    # functions
    # ------------------------------------------------------------------
    def convert_selection(self) -> None:
        if self.scene is None or self.project is None:
            return
        node_ids = self.scene.selected_node_ids()
        if not node_ids:
            QMessageBox.information(self, "Convert to function", "Select the nodes that should become a function.")
            return
        preview = extract_function(self.scene.graph, node_ids, name="Preview", registry=self.registry)
        dialog = FunctionDialog(
            name="My function",
            description="",
            inputs=preview.function.inputs,
            outputs=preview.function.outputs,
            title="Convert selection to function",
            parent=self,
        )
        if dialog.exec() != FunctionDialog.Accepted:
            return
        try:
            extraction = extract_function(
                self.scene.graph,
                node_ids,
                name=dialog.function_name,
                description=dialog.function_description,
                registry=self.registry,
            )
        except ExtractionError as exc:
            QMessageBox.warning(self, "Convert to function", str(exc))
            return
        function = extraction.function
        self.project.add_function(function, registry=self.registry)
        self.library.add(function, register=True)
        scene = self.scene
        scene.begin_edit()
        scene.graph.remove_nodes(node_ids)
        call = scene.graph.add_node(
            function.type_id,
            {},
            extraction.call_position,
            label=function.name,
        )
        for port_name, (source, source_port) in extraction.input_sources.items():
            if source in scene.graph.nodes:
                try:
                    scene.graph.connect(source, source_port, call.id, port_name)
                except Exception as exc:
                    self.console.log(f"Could not reconnect {port_name}: {exc}", "warn")
        for port_name, targets in extraction.output_links.items():
            for target, target_port in targets:
                if target in scene.graph.nodes:
                    try:
                        scene.graph.connect(call.id, port_name, target, target_port)
                    except Exception as exc:
                        self.console.log(f"Could not reconnect {port_name}: {exc}", "warn")
        scene.rebuild()
        scene.clearSelection()
        item = scene.node_items.get(call.id)
        if item is not None:
            item.setSelected(True)
        scene.commit_edit(f"Extract function {function.name}")
        self.status_message.setText(f"Created function “{function.name}”")
        self._selection_changed()
        self._mark_dirty()

    def add_function_node(self) -> None:
        if self.scene is None or self.project is None:
            return
        if not self.project.functions:
            QMessageBox.information(
                self, "Function library", "No functions yet. Select some nodes and use Edit ▸ Convert selection to function."
            )
            return
        names = [f"{f.name} ({f.id})" for f in self.project.functions]
        choice, ok = QInputDialog.getItem(self, "Add function call", "Function", names, 0, False)
        if not ok:
            return
        function = self.project.functions[names.index(choice)]
        center = self.view.mapToScene(self.view.viewport().rect().center())
        item = self.scene.add_node(function.type_id, (center.x() - 100, center.y() - 60))
        if item is not None:
            self.scene.clearSelection()
            item.setSelected(True)

    def edit_function(self, function_id: str) -> None:
        if self.project is None or self.library is None:
            return
        function = self.library.get(function_id)
        if function is None:
            QMessageBox.information(self, "Function", f"Function {function_id} is not in this project.")
            return
        dialog = FunctionEditorDialog(function, self.registry, theme_name=self.theme_name, parent=self)
        if dialog.exec() == FunctionEditorDialog.Accepted:
            self.registry.register(function.to_definition(), replace=True)
            self.project.touch()
            self._mark_dirty()
            self.status_message.setText(f"Updated function “{function.name}”")
            if self.scene is not None:
                self.scene.rebuild()

    # ------------------------------------------------------------------
    # settings, plugins, help
    # ------------------------------------------------------------------
    def open_settings(self) -> None:
        if self.project is None:
            QMessageBox.information(self, "Settings", "Open a project to change its execution and security settings.")
            return
        dialog = SettingsDialog(self.project.settings, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        self._apply_theme(self.project.settings.theme, self.project.settings.accent)
        self.autosave.start(max(5, int(self.project.settings.autosave_seconds)) * 1000)
        self._mark_dirty()
        self.status_message.setText("Settings updated")

    def open_plugins(self) -> None:
        if self.runner.is_running():
            QMessageBox.information(self, "Extensions", "Stop the current run before changing extensions.")
            return
        dialog = PluginDialog(self.plugins, on_changed=self._reload_plugins, parent=self)
        dialog.exec()

    def _reload_plugins(self) -> None:
        self.registry = create_registry()
        self.plugins.discover()
        failures = self.plugins.load_enabled(self.registry)
        self.library_panel.registry = self.registry
        self.library_panel.reload()
        if self.project is not None:
            self.project.bind_registry(self.registry)
            self.library = self.project.function_library(self.registry)
            if self.scene is not None:
                self.scene.graph.set_registry(self.registry)
                self.scene.rebuild()
                self._selection_changed()
        for name, error in failures.items():
            self.console.log(f"Plugin {name} failed: {error}", "error")

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "About SYNAPSE",
            "<h3>SYNAPSE</h3>"
            "<p>A universal visual programming environment.</p>"
            "<p>Graphs are typed programs executed by an asyncio dataflow engine. "
            "Debug them node by node, extract reusable functions, drop into sandboxed "
            "Python, and extend the node library with plugins.</p>"
            "<p>Built with Python and PySide6.</p>",
        )

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self.runner.is_running():
            if not self._confirm_stop():
                event.ignore()
                return
            self.runner.stop()
            deadline = time.time() + 3.0
            while self.runner.is_running() and time.time() < deadline:
                QApplication.processEvents()
                time.sleep(0.02)
        if not self._confirm_discard():
            event.ignore()
            return
        self.autosave.stop()
        super().closeEvent(event)
