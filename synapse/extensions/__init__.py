"""Plugin discovery, installation and loading."""

from .api import PermissionDenied, PluginAPI, build_script_node
from .manager import PluginError, PluginManager, PluginRecord
from .manifest import ManifestError, PluginManifest, PluginNodeSpec

PluginInfo = PluginRecord

__all__ = [
    "ManifestError",
    "PermissionDenied",
    "PluginAPI",
    "PluginError",
    "PluginInfo",
    "PluginManager",
    "PluginManifest",
    "PluginNodeSpec",
    "PluginRecord",
    "build_script_node",
]
