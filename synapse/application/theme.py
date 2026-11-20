"""Theme palettes and application stylesheet."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_ACCENT = "#5ac8fa"
_ACTIVE_ACCENT = DEFAULT_ACCENT


def set_active_accent(colour: str) -> None:
    global _ACTIVE_ACCENT
    _ACTIVE_ACCENT = colour or DEFAULT_ACCENT


def active_accent() -> str:
    return _ACTIVE_ACCENT
CATEGORY_COLORS = {
    "Core": "#8b95a5",
    "Logic": "#c084fc",
    "Mathematics": "#fbbf24",
    "Data": "#38bdf8",
    "Files": "#34d399",
    "Networking": "#f472b6",
    "AI": "#a78bfa",
    "Graphics": "#fb923c",
    "System": "#94a3b8",
    "Scripting": "#2dd4bf",
    "Functions": "#60a5fa",
    "Extensions": "#f59e0b",
}


def category_color(category: str) -> str:
    return CATEGORY_COLORS.get(category, "#7c8aa0")


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    canvas: str
    grid: str
    grid_major: str


DARK = Theme(
    name="dark",
    background="#0d1014",
    surface="#151a21",
    surface_alt="#1b222b",
    border="#27303c",
    text="#e6edf3",
    muted="#8b97a8",
    canvas="#0f141a",
    grid="#171e26",
    grid_major="#1d2631",
)

LIGHT = Theme(
    name="light",
    background="#f4f6f9",
    surface="#ffffff",
    surface_alt="#eef2f7",
    border="#d6dee8",
    text="#1b2430",
    muted="#5f6f82",
    canvas="#f7f9fc",
    grid="#e8edf4",
    grid_major="#dce3ec",
)


def get_theme(name: str) -> Theme:
    return LIGHT if str(name).lower() == "light" else DARK


def stylesheet(theme: Theme, accent: str = DEFAULT_ACCENT) -> str:
    t = theme
    accent_soft = accent + "2b"
    return f"""
* {{
    font-family: "Inter", "Segoe UI", "Noto Sans", Ubuntu, sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog {{ background: {t.background}; color: {t.text}; }}
QWidget {{ color: {t.text}; }}
QMenuBar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {t.surface_alt}; }}
QMenu {{ background: {t.surface}; border: 1px solid {t.border}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {t.text}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}
QToolBar {{ background: {t.surface}; border: none; border-bottom: 1px solid {t.border}; padding: 4px 6px; spacing: 4px; }}
QToolBar QToolButton {{ padding: 5px 8px; border-radius: 5px; color: {t.text}; }}
QToolBar QToolButton:hover {{ background: {t.surface_alt}; }}
QToolBar QToolButton:pressed, QToolBar QToolButton:checked {{ background: {accent_soft}; color: {accent}; }}
QToolBar::separator {{ background: {t.border}; width: 1px; margin: 4px 6px; }}
QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; color: {t.muted}; }}
QStatusBar QLabel {{ color: {t.muted}; padding: 0 6px; }}
QDockWidget {{ titlebar-close-icon: none; color: {t.muted}; }}
QDockWidget::title {{ background: {t.surface}; padding: 6px 10px; border-bottom: 1px solid {t.border};
    text-transform: uppercase; font-size: 10px; letter-spacing: 1px; }}
QDockWidget::close-button, QDockWidget::float-button {{ border: none; background: transparent; padding: 0; icon-size: 12px; }}
QTabWidget::pane {{ border: 1px solid {t.border}; background: {t.surface}; }}
QTabBar::tab {{ background: transparent; color: {t.muted}; padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {accent}; }}
QTabBar::tab:hover {{ color: {t.text}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {t.surface_alt}; border: 1px solid {t.border}; border-radius: 5px;
    padding: 5px 7px; selection-background-color: {accent}; selection-color: #06121c;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {accent};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {t.surface}; border: 1px solid {t.border}; selection-background-color: {accent_soft}; }}
QPushButton {{ background: {t.surface_alt}; border: 1px solid {t.border}; border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {accent_soft}; }}
QPushButton:disabled {{ color: {t.muted}; }}
QPushButton#primary {{ background: {accent}; color: #06121c; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {accent}cc; }}
QPushButton#danger {{ background: transparent; border: 1px solid #ef4444; color: #ef4444; }}
QPushButton#danger:hover {{ background: #ef444422; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {t.muted}; }}
QPushButton#ghost:hover {{ color: {t.text}; border-color: {t.border}; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {t.border}; background: {t.surface_alt}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QTreeWidget, QTreeView, QListWidget, QTableView {{
    background: {t.surface}; border: 1px solid {t.border}; outline: 0;
    alternate-background-color: {t.surface_alt};
}}
QTreeWidget::item, QListWidget::item {{ padding: 5px 4px; border-radius: 4px; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {t.surface_alt}; }}
QTreeWidget::item:selected, QListWidget::item:selected {{ background: {accent_soft}; color: {t.text}; }}
QHeaderView::section {{ background: {t.surface_alt}; color: {t.muted}; border: none; padding: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {t.border}; width: 1px; height: 1px; }}
QToolTip {{ background: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border}; padding: 5px; }}
QLabel#heading {{ font-size: 20px; font-weight: 600; }}
QLabel#subheading {{ color: {t.muted}; }}
QLabel#sectionLabel {{ color: {t.muted}; font-size: 10px; letter-spacing: 1px; text-transform: uppercase; }}
QLabel#badge {{ background: {accent_soft}; color: {accent}; border-radius: 4px; padding: 2px 8px; font-size: 10px; }}
QFrame#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; }}
QFrame#separator {{ background: {t.border}; max-height: 1px; border: none; }}
QProgressBar {{ background: {t.surface_alt}; border: none; border-radius: 3px; height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 3px; }}
QStackedWidget {{ background: {t.background}; }}
QPlainTextEdit#console {{ background: {t.surface}; border: none; font-family: "JetBrains Mono", "SF Mono", Menlo, monospace; font-size: 11px; }}
QListWidget#welcomeRecent {{ background: transparent; border: none; }}
QListWidget#welcomeRecent::item {{ padding: 8px; border-radius: 6px; }}
QListWidget#welcomeRecent::item:hover {{ background: {t.surface_alt}; }}
"""
