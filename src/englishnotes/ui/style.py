"""Shared dark palette for the workspace, dialogs and native Qt controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

BACKGROUND = "#101318"
SURFACE = "#1a1f28"
TEXT = "#e6eaf2"
MUTED = "#98a3b5"
ACCENT = "#a3afff"

STYLE = """
QWidget {
    font-family: 'Inter', 'Segoe UI Variable', 'Segoe UI', 'DejaVu Sans', sans-serif;
    font-size: 13px; color: #e6eaf2;
}
QMainWindow, QDialog, QInputDialog, QMessageBox { background: #101318; }
QFrame#sidebar { background: #13171e; border-right: 1px solid #272e3a; }
QWidget#workspace { background: #101318; }
QLabel { background: transparent; }
QLabel#brandMark {
    background: #a3afff; color: #151b33; border-radius: 11px;
    font-size: 18px; font-weight: 700;
}
QLabel#brand { font-size: 20px; font-weight: 700; color: #f2f4fa; }
QLabel#subtitle { font-size: 11px; color: #8f9aaf; }
QLabel#eyebrow { font-size: 11px; color: #929eb2; font-weight: 600; }
QLabel#counter {
    font-size: 10px; color: #a4afc1; background: #242b37;
    border-radius: 7px; padding: 2px 7px;
}
QLabel#lessonKind {
    font-size: 11px; color: #a3afff; background: #232a41;
    border-radius: 7px; padding: 5px 9px;
}
QLabel#lessonKind[tone="closed"] { color: #b0b8c7; background: #242b37; }
QLabel#empty { font-size: 21px; font-weight: 600; color: #d3dbe8; }
QLabel#emptyHint { font-size: 13px; color: #98a3b5; }
QLabel#saveStatus { color: #a0acbe; font-size: 11px; }
QLabel#authorMeta, QLabel#shortcut { color: #98a3b5; font-size: 11px; }
QLabel#error {
    color: #ffc2c9; background: #35202a; border: 1px solid #67404c;
    padding: 10px 12px; border-radius: 9px;
}
QFrame#syncPanel { background: #1b2029; border: 1px solid #2b3340; border-radius: 12px; }
QLabel#syncStatus { color: #b8c2d2; font-size: 11px; }
QLabel#syncStatus[tone="online"] { color: #8cdbb8; }
QLabel#syncStatus[tone="warning"] { color: #edc183; }
QLabel#syncStatus[tone="error"] { color: #f0a3ae; }
QLabel#syncPending { color: #a0acbe; font-size: 11px; }
QLabel#syncPending[tone="warning"] { color: #edc183; }
QPushButton {
    background: #222936; border: 1px solid #343e4f; border-radius: 9px;
    padding: 9px 12px; font-size: 13px; font-weight: 500; color: #dce3ef;
    min-height: 18px;
}
QPushButton:hover { background: #2b3545; border-color: #53617b; }
QPushButton:pressed { background: #1c2330; }
QPushButton:focus { border: 1px solid #a3afff; }
QPushButton:disabled { color: #707c90; background: #191e27; border-color: #2b3340; }
QPushButton#primary {
    background: #a3afff; color: #141b32; border-color: #a3afff; font-weight: 600;
}
QPushButton#primary:hover { background: #bac3ff; border-color: #bac3ff; }
QPushButton#primary:pressed { background: #8f9df1; }
QPushButton#primary:disabled { background: #303951; border-color: #303951; color: #909bb8; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; }
QPushButton[variant="ghost"]:hover { background: #222936; border-color: #343e4f; }
QPushButton[variant="ghost"]:focus { border-color: #a3afff; }
QPushButton#delete { color: #e9a2ad; background: transparent; border-color: transparent; }
QPushButton#delete:hover { background: #35202a; border-color: #67404c; }
QPushButton#warning { color: #edc183; background: #342c21; border-color: #625039; }
QPushButton#warning:hover { background: #433728; }
QListWidget { background: transparent; border: none; outline: 0; padding: 0; }
QListWidget::item { border: none; background: transparent; }
QListWidget::item:selected { background: transparent; }
QLineEdit {
    color: #e6eaf2; background: #1b2029; border: 1px solid #343e4f;
    border-radius: 9px; padding: 10px 12px;
    selection-background-color: #46588a; selection-color: #ffffff;
}
QLineEdit#invitationCode {
    font-family: "Cascadia Code", "Consolas", "DejaVu Sans Mono", monospace;
    font-size: 12px; color: #c3cdff; padding: 14px;
}
QLineEdit:focus { border-color: #a3afff; }
QLineEdit:disabled { color: #929eb2; background: #171c24; border-color: #2b3340; }
QLineEdit#lessonTitle {
    background: transparent; border: 1px solid transparent; font-size: 25px;
    font-weight: 600; padding: 6px 0;
}
QLineEdit#lessonTitle:focus { border-bottom-color: #7c8ed0; border-radius: 0; }
QLineEdit#lessonTitle:read-only { border-color: transparent; }
QLineEdit#lessonTitle:disabled { color: #929eb2; }
QFrame#editorSurface { background: #1a1f28; border: 1px solid #303947; border-radius: 14px; }
QLineEdit#noteTitle {
    background: transparent; border: none; border-bottom: 1px solid transparent;
    border-radius: 0; padding: 12px 4px; font-size: 20px; font-weight: 600;
}
QLineEdit#noteTitle:focus { border-bottom-color: #6574ab; }
QPlainTextEdit {
    color: #dce3ef; background: #1a1f28; border: 1px solid #343e4f;
    border-radius: 10px; padding: 14px; font-size: 15px;
    selection-background-color: #46588a; selection-color: #ffffff;
}
QPlainTextEdit:focus { border-color: #8c9ee4; }
QPlainTextEdit#noteBody {
    background: transparent; border: none; padding: 10px 4px; font-size: 16px;
}
QFrame#editorDivider { background: #303947; border: none; max-height: 1px; }
QSplitter::handle { background: #252d39; width: 1px; }
QSplitter::handle:hover { background: #5c6b91; }
QStatusBar { background: #101318; color: #8f9aaf; font-size: 10px; border-top: 1px solid #252d39; }
QStatusBar::item { border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }
QScrollBar::handle:vertical { background: #3b4659; border-radius: 4px; min-height: 28px; }
QScrollBar::handle:vertical:hover { background: #61708c; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0 2px; }
QScrollBar::handle:horizontal { background: #3b4659; border-radius: 4px; min-width: 28px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: none; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QToolTip { color: #e6eaf2; background: #252e3e; border: 1px solid #53617b; padding: 7px; }
QMenu { background: #1a1f28; color: #e6eaf2; border: 1px solid #343e4f; padding: 5px; }
QMenu::item { padding: 7px 20px; border-radius: 5px; }
QMenu::item:selected { background: #303c58; }
QMenu::item:disabled { color: #707c90; }
QMenu::separator { background: #343e4f; height: 1px; margin: 5px; }
"""


def apply_theme(application: QApplication) -> None:
    if application.property("englishnotesDarkTheme"):
        return
    application.setStyle("Fusion")
    application.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    palette = QPalette()
    for role, color in {
        QPalette.ColorRole.Window: BACKGROUND,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE,
        QPalette.ColorRole.AlternateBase: "#232b37",
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.Button: "#222936",
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.Highlight: "#46588a",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: MUTED,
        QPalette.ColorRole.ToolTipBase: "#252e3e",
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.BrightText: "#ffffff",
    }.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#929eb2"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#707c90"))
    application.setPalette(palette)
    application.setStyleSheet(STYLE)
    application.setProperty("englishnotesDarkTheme", True)


def tone(widget: QWidget, value: str) -> None:
    if widget.property("tone") == value:
        return
    widget.setProperty("tone", value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()
