"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("SYNAPSE")
    app.setApplicationDisplayName("SYNAPSE")
    app.setOrganizationName("SYNAPSE")
    app.setApplicationVersion(__import__("synapse").__version__)
    font = QFont()
    font.setFamilies(["Inter", "Segoe UI", "SF Pro Text", "Ubuntu", "DejaVu Sans"])
    font.setPointSize(10)
    app.setFont(font)
    return app


def main(argv: list[str] | None = None) -> int:
    app = create_application(argv)
    window = MainWindow()
    window.show()
    args = [arg for arg in (argv if argv is not None else sys.argv[1:]) if not arg.startswith("-")]
    if args:
        window.open_project(args[0])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
