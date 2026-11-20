"""Modal dialogs used by the main window."""

from .function_dialog import FunctionDialog
from .function_editor import FunctionEditorDialog
from .new_project_dialog import NewProjectDialog
from .plugin_dialog import PluginDialog
from .run_dialog import RunInputsDialog
from .settings_dialog import SettingsDialog

__all__ = [
    "FunctionDialog",
    "FunctionEditorDialog",
    "NewProjectDialog",
    "PluginDialog",
    "RunInputsDialog",
    "SettingsDialog",
]
