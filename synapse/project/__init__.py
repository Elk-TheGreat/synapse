"""Project files, settings, autosave and recovery."""

from .model import FORMAT, FORMAT_VERSION, Project, ProjectError, ProjectSettings
from .settings import AppDatabase, app_data_dir, default_database
from .store import PROJECT_SUFFIX, ProjectStore
from .templates import TEMPLATES, create_project

__all__ = [
    "AppDatabase",
    "FORMAT",
    "FORMAT_VERSION",
    "PROJECT_SUFFIX",
    "Project",
    "ProjectError",
    "ProjectSettings",
    "ProjectStore",
    "TEMPLATES",
    "app_data_dir",
    "create_project",
    "default_database",
]
