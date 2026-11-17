import json

import pytest
from PySide6.QtWidgets import QInputDialog

from englishnotes.ui.cloud_bridge import CloudBridge
from englishnotes.ui.main_window import MainWindow


@pytest.fixture
def bridge(qtbot, service, database):
    window = MainWindow(service)
    qtbot.addWidget(window)
    window.cloud_bridge = CloudBridge(window, database, None)
    window.show()
    return window.cloud_bridge


def test_unconfigured_build_keeps_local_working(bridge):
    window = bridge.window
    window.create_lesson()
    window.create_note()
    window.note_body.setPlainText("Offline preserved")
    assert window.flush_changes()
    assert window.service.list_notes(window.lesson.id)[0].content == "Offline preserved"
    assert not bridge.create_button.isEnabled()
    assert "локально" in bridge.status.text()


def test_failed_create_never_uploads_previous_private_lesson(bridge, monkeypatch):
    window = bridge.window
    window.create_lesson()
    old = window.lesson.id
    monkeypatch.setattr(QInputDialog, "getText", lambda *a: ("Shared", True))
    monkeypatch.setattr(window, "create_lesson", lambda: None)
    bridge.create()
    assert bridge.store.scope(old) is None
    assert not bridge.store.rows("SELECT * FROM cloud_commands")


def test_cloud_refresh_preserves_editor_cursor_and_flushes_buffer(bridge):
    window = bridge.window
    window.create_lesson()
    window.create_note()
    window.note_body.setPlainText("New typed text")
    cursor = window.note_body.textCursor()
    cursor.setPosition(4)
    window.note_body.setTextCursor(cursor)
    bridge.received("u")
    assert window.note_body.toPlainText() == "New typed text"
    assert window.note_body.textCursor().position() == 4
    assert window.service.list_notes(window.lesson.id)[0].content == "New typed text"


def test_deleted_note_conflict_remains_accessible(bridge):
    window = bridge.window
    window.create_lesson()
    window.create_note()
    note = window.note
    bridge.store.enroll(window.lesson.id)
    window.service.delete_note(note)
    with bridge.store.db.transaction() as db:
        db.execute(
            "INSERT INTO cloud_conflicts VALUES(?,?,?,?,?)",
            (note.id, None, json.dumps({}), json.dumps({}), 2),
        )
    window._select_lesson(window.lesson_list.currentItem())
    assert window.note is None
    bridge.update_controls()
    assert bridge.conflict_button.isEnabled()
