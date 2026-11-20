"""Dockable panels: library, inspector, console, debugger, quick open."""

from .console import ExecutionConsole
from .debugger_panel import DebuggerPanel
from .inspector import NodeInspector
from .library import NodeLibraryPanel
from .search_dialog import PaletteEntry, QuickOpenDialog, node_entries

__all__ = [
    "ExecutionConsole",
    "DebuggerPanel",
    "NodeInspector",
    "NodeLibraryPanel",
    "PaletteEntry",
    "QuickOpenDialog",
    "node_entries",
]
