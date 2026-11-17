STYLE = """
QMainWindow, QWidget { background: #f7f8fc; color: #24314a; font-size: 14px; }
QWidget { font-family: 'Segoe UI', 'DejaVu Sans', sans-serif; }
QLabel { background: transparent; }
QFrame#sidebar { background: #edf1f8; border: none; }
QLabel#brand { font-size: 24px; font-weight: 700; color: #2946a4; }
QLabel#eyebrow { color: #68758b; font-size: 12px; }
QLabel#empty { font-size: 18px; color: #68758b; }
QLabel#saveStatus { color: #54657e; }
QLabel#error { color: #8e2832; background: #fff0f0; padding: 10px; border-radius: 6px; }
QPushButton { background: #ffffff; border: 1px solid #d8dfed; padding: 9px 14px;
              border-radius: 7px; font-weight: 600; }
QPushButton:hover { background: #e7ecfb; border-color: #acbcec; }
QPushButton:disabled { color: #9ca6b8; background: #f1f3f7; }
QPushButton#primary { background: #3759c7; color: white; border: 1px solid #3759c7; }
QPushButton#primary:hover { background: #2c49ac; }
QPushButton#delete { color: #a13343; }
QListWidget { background: transparent; border: none; outline: 0; }
QListWidget::item { padding: 12px 10px; margin: 3px 0; border-radius: 6px; }
QListWidget::item:selected { background: #dce5fd; color: #243c85; }
QListWidget::item:hover:!selected { background: #e8ecf5; }
QLineEdit { background: white; border: 1px solid #d8dfed; border-radius: 7px; padding: 9px; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #6380d9; }
QLineEdit#lessonTitle { font-size: 22px; font-weight: 600; }
QLineEdit#noteTitle { font-size: 18px; font-weight: 600; }
QPlainTextEdit { background: white; border: 1px solid #d8dfed; border-radius: 8px;
                 padding: 14px; font-size: 16px; selection-background-color: #dce5fd; }
QSplitter::handle { background: #e0e5ef; width: 1px; }
QStatusBar { background: #edf1f8; color: #68758b; }
"""
