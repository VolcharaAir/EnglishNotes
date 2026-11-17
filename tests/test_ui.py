import os
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from englishnotes.application.service import NotesService
from englishnotes.domain.errors import StorageError
from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository
from englishnotes.ui.main_window import MainWindow


@pytest.fixture
def window(qtbot, service):
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.show()
    yield window


def click(qtbot, button):
    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_first_launch_is_empty_and_buttons_create_real_records(qtbot, window, service):
    assert window.lesson_list.count() == 0
    assert not window.new_note_button.isEnabled()
    click(qtbot, window.new_lesson_button)
    assert window.lesson_list.count() == 1
    assert window.new_note_button.isEnabled()
    assert service.list_lessons()[0].id == window.lesson.id
    click(qtbot, window.new_note_button)
    assert window.note_list.count() == 1
    assert service.list_notes(window.lesson.id)[0].id == window.note.id


def test_typing_autosaves_title_body_and_lesson(qtbot, window, service):
    window.create_lesson()
    window.create_note()
    window.lesson_title.setText("Lesson: articles")
    window.note_title.setText("A / an / the")
    window.note_body.setPlainText("An apple\nЯблоко 🍎\n'quoted'")
    assert window.isWindowModified()
    qtbot.waitUntil(lambda: not window.isWindowModified(), timeout=3000)
    assert service.list_lessons()[0].title == "Lesson: articles"
    note = service.list_notes(window.lesson.id)[0]
    assert note.title == "A / an / the"
    assert note.content == "An apple\nЯблоко 🍎\n'quoted'"
    assert window.note_list.currentItem().text() == "A / an / the"


def test_continuous_edits_have_maximum_save_delay(qtbot, window, service):
    window.AUTOSAVE_MS = 1000
    window.MAX_SAVE_DELAY_MS = 80
    window.create_lesson()
    window.create_note()
    window.note_body.setPlainText("first")
    qtbot.wait(30)
    window.note_body.setPlainText("second")
    qtbot.waitUntil(lambda: not window.isWindowModified(), timeout=600)
    assert service.list_notes(window.lesson.id)[0].content == "second"


def test_switching_notes_flushes_unsaved_text(qtbot, window, service):
    window.create_lesson()
    window.create_note()
    first_id = window.note.id
    window.note_body.setPlainText("Immediate switch")
    window.create_note()
    assert service.list_notes(window.lesson.id)[0].content == "Immediate switch"
    window.note_body.setPlainText("Second note")
    window.note_list.setCurrentRow(0)
    assert window.note.id == first_id
    assert window.note_body.toPlainText() == "Immediate switch"
    assert service.list_notes(window.lesson.id)[1].content == "Second note"


def test_switching_lessons_isolates_and_flushes_notes(qtbot, window, service):
    window.create_lesson()
    first_lesson_id = window.lesson.id
    window.create_note()
    window.note_body.setPlainText("First lesson only")
    window.create_lesson()
    assert window.note_list.count() == 0
    assert window.note is None
    window.create_note()
    window.note_body.setPlainText("Second lesson")
    window.lesson_list.setCurrentRow(1)
    assert window.lesson.id == first_lesson_id
    assert window.note_body.toPlainText() == "First lesson only"
    assert len(service.list_lessons()) == 2


def test_close_flushes_and_new_window_restores(qtbot, window, database):
    window.create_lesson()
    window.create_note()
    window.note_title.setText("Restore me")
    window.note_body.setPlainText("Saved by close event")
    assert window.close()
    path = database.path
    database.close()
    reopened = Database(path)
    try:
        restored = MainWindow(NotesService(SQLiteNotesRepository(reopened)))
        qtbot.addWidget(restored)
        assert restored.lesson_list.count() == 1
        assert restored.note_title.text() == "Restore me"
        assert restored.note_body.toPlainText() == "Saved by close event"
        restored.close()
    finally:
        reopened.close()


@pytest.mark.parametrize("confirm", [True, False])
def test_delete_requires_confirmation(qtbot, window, service, monkeypatch, confirm):
    window.create_lesson()
    window.create_note()
    answer = QMessageBox.StandardButton.Yes if confirm else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer)
    click(qtbot, window.delete_note_button)
    assert window.note_list.count() == (0 if confirm else 1)
    assert len(service.list_notes(window.lesson.id)) == (0 if confirm else 1)
    if confirm:
        assert window.note is None
        window.create_note()
        assert window.note is not None
        assert window.note_body.toPlainText() == ""


def test_failed_save_preserves_editor_blocks_navigation_close_and_recovers(
    qtbot,
    window,
    service,
    monkeypatch,
):
    window.create_lesson()
    window.create_note()
    original_note = window.note
    window.create_note()
    window.note_list.setCurrentRow(0)
    original_save = service.save_note

    def fail(*args):
        raise StorageError("Нет места на диске")

    monkeypatch.setattr(service, "save_note", fail)
    window.note_body.setPlainText("Keep this unsaved text")
    assert not window.flush_changes()
    assert window.error_label.isVisible()
    assert window.retry_button.isVisible()
    assert window.isWindowModified()
    window.note_list.setCurrentRow(1)
    assert window.note_list.currentRow() == 0
    assert window.note.id == original_note.id
    assert window.note_body.toPlainText() == "Keep this unsaved text"
    window.create_lesson()
    assert window.lesson_list.count() == 1
    assert not window.close()
    assert window.isVisible()
    assert service.list_notes(window.lesson.id)[0].content == ""
    monkeypatch.setattr(service, "save_note", original_save)
    click(qtbot, window.retry_button)
    assert not window.isWindowModified()
    assert not window.error_label.isVisible()
    assert service.list_notes(window.lesson.id)[0].content == "Keep this unsaved text"


def test_failed_save_prevents_lesson_switch(qtbot, window, service, monkeypatch):
    window.create_lesson()
    window.create_lesson()
    original_lesson = window.lesson
    window.create_note()
    original_save = service.save_note

    def fail(*args):
        raise StorageError("Database busy")

    monkeypatch.setattr(service, "save_note", fail)
    window.note_body.setPlainText("Pending")
    window.lesson_list.setCurrentRow(1)
    assert window.lesson_list.currentRow() == 0
    assert window.lesson == original_lesson
    monkeypatch.setattr(service, "save_note", original_save)
    assert window.flush_changes()


def test_ctrl_s_flushes_immediately(qtbot, window, service):
    window.create_lesson()
    window.create_note()
    window.note_body.setPlainText("Save via shortcut")
    window.note_body.setFocus()
    qtbot.waitUntil(window.isActiveWindow)
    qtbot.keyClick(window.note_body, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert service.list_notes(window.lesson.id)[0].content == "Save via shortcut"


def test_real_database_write_failure_retains_editor_and_recovers(
    qtbot,
    window,
    service,
    database,
):
    window.create_lesson()
    window.create_note()
    database.connection.execute("PRAGMA query_only=ON")
    window.note_body.setPlainText("Keep even when SQLite rejects writing")
    qtbot.waitUntil(lambda: window.error_label.isVisible(), timeout=2000)
    assert window.isWindowModified()
    assert window.note_body.toPlainText() == "Keep even when SQLite rejects writing"
    assert service.list_notes(window.lesson.id)[0].content == ""
    database.connection.execute("PRAGMA query_only=OFF")
    click(qtbot, window.retry_button)
    assert not window.isWindowModified()
    assert service.list_notes(window.lesson.id)[0].content == window.note_body.toPlainText()


def test_partial_save_retries_only_unsaved_note(qtbot, window, service, monkeypatch):
    window.create_lesson()
    window.create_note()
    original_save = service.save_note

    def fail(*args):
        raise StorageError("Write rejected")

    monkeypatch.setattr(service, "save_note", fail)
    window.lesson_title.setText("Saved lesson name")
    window.note_body.setPlainText("Unsaved note")
    assert not window.flush_changes()
    saved_lesson = service.list_lessons()[0]
    assert saved_lesson.title == "Saved lesson name"
    monkeypatch.setattr(service, "save_note", original_save)
    assert window.flush_changes()
    assert service.list_lessons()[0].revision == saved_lesson.revision
    assert service.list_notes(window.lesson.id)[0].content == "Unsaved note"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux isolated XDG bootstrap")
def test_application_bootstrap_creates_database_in_data_directory(tmp_path):
    env = os.environ.copy()
    env["XDG_DATA_HOME"] = str(tmp_path)
    env["LOCALAPPDATA"] = str(tmp_path)
    env["QT_QPA_PLATFORM"] = "offscreen"
    code = """
from PySide6.QtCore import QTimer
from englishnotes import app
original_show = app.MainWindow.show
def show(self):
    original_show(self)
    QTimer.singleShot(50, self.close)
app.MainWindow.show = show
raise SystemExit(app.main())
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "EnglishNotes" / "englishnotes.sqlite3").is_file()
    assert not (tmp_path / "EnglishNotes" / "englishnotes.lock").exists()
