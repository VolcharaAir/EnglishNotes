import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile

from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository


def run_startup(source: Path, target: Path):
    code = f"""
from pathlib import Path
from PySide6.QtCore import QTimer
from englishnotes import app
app.database_path = lambda: Path({str(target)!r})
app.legacy_database_path = lambda: Path({str(source)!r})
app.configure_runtime = lambda: None
app.QMessageBox.critical = lambda *args: None
original_show = app.MainWindow.show
def show(self):
    original_show(self)
    QTimer.singleShot(30, self.close)
app.MainWindow.show = show
raise SystemExit(app.main())
"""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=20
    )


def test_bootstrap_migrates_then_reopens_existing_lessons(tmp_path):
    source = tmp_path / "legacy" / "englishnotes.sqlite3"
    target = tmp_path / "profile" / "englishnotes.sqlite3"
    database = Database(source)
    lesson = SQLiteNotesRepository(database).create_lesson("Before update")
    database.close()
    assert run_startup(source, target).returncode == 0
    assert run_startup(source, target).returncode == 0
    database = Database(target)
    try:
        assert SQLiteNotesRepository(database).list_lessons() == [lesson]
    finally:
        database.close()
    assert source.is_file()
    assert not (source.parent / "englishnotes.lock").exists()


def test_bootstrap_refuses_migration_while_old_application_is_running(tmp_path):
    source = tmp_path / "legacy" / "englishnotes.sqlite3"
    target = tmp_path / "profile" / "englishnotes.sqlite3"
    database = Database(source)
    database.close()
    lock = QLockFile(str(source.parent / "englishnotes.lock"))
    assert lock.tryLock(0)
    try:
        result = run_startup(source, target)
        assert result.returncode == 1, result.stderr
        assert not target.exists()
        assert lock.isLocked()
    finally:
        lock.unlock()


def test_failed_migration_does_not_initialize_empty_database(tmp_path):
    source = tmp_path / "corrupt.sqlite3"
    source.write_bytes(b"keep original")
    target = tmp_path / "profile" / "englishnotes.sqlite3"
    result = run_startup(source, target)
    assert result.returncode == 1, result.stderr
    assert not target.exists()
    assert source.read_bytes() == b"keep original"
