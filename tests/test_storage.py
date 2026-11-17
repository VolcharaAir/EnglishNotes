import sqlite3
from dataclasses import replace
from uuid import UUID

import pytest

from englishnotes.domain.errors import ConflictError, NotFoundError, StorageError
from englishnotes.storage.database import SCHEMA_VERSION, Database
from englishnotes.storage.repository import SQLiteNotesRepository


def test_first_launch_creates_database_and_schema(database):
    assert database.path.is_file()
    assert database.connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert database.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert database.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_full_lifecycle_survives_reopening(database, repository):
    lesson = repository.create_lesson("Past Simple")
    assert str(UUID(lesson.id)) == lesson.id
    note = repository.create_note(lesson.id, "Первый урок", "Don't / не забыть 📘\n第二行")
    second = repository.create_note(lesson.id, "Remove me", "draft")
    note = repository.update_note(note, "Vocabulary", "It's useful.\nПример ✅")
    lesson = repository.update_lesson(lesson, "Lesson 1")
    repository.delete_note(second)
    path = database.path
    database.close()
    reopened = Database(path)
    try:
        fresh = SQLiteNotesRepository(reopened)
        assert fresh.list_lessons() == [lesson]
        assert fresh.list_notes(lesson.id) == [note]
        assert note.revision == 2
        assert note.updated_at >= note.created_at
        row = reopened.connection.execute("SELECT * FROM notes WHERE id=?", (second.id,)).fetchone()
        assert row["deleted_at"]
        assert row["revision"] == 2
    finally:
        reopened.close()


def test_notes_belong_to_their_lesson(repository):
    a = repository.create_lesson("A")
    b = repository.create_lesson("B")
    note_a = repository.create_note(a.id, "a", "one")
    note_b = repository.create_note(b.id, "b", "two")
    assert repository.list_lessons() == [b, a]
    assert repository.list_notes(a.id) == [note_a]
    assert repository.list_notes(b.id) == [note_b]
    with pytest.raises(NotFoundError):
        repository.update_note(replace(note_a, lesson_id=b.id), "oops", "oops")
    with pytest.raises(NotFoundError):
        repository.delete_note(replace(note_a, lesson_id=b.id))
    assert repository.list_notes(a.id) == [note_a]


def test_note_order_does_not_change_after_edit(repository):
    lesson = repository.create_lesson("Lesson")
    a = repository.create_note(lesson.id, "A", "")
    b = repository.create_note(lesson.id, "B", "")
    a = repository.update_note(a, "Edited", "updated")
    assert repository.list_notes(lesson.id) == [a, b]


def test_unknown_lesson_and_deleted_note_are_rejected(repository):
    with pytest.raises(NotFoundError):
        repository.create_note("missing", "Title", "Body")
    lesson = repository.create_lesson("Lesson")
    note = repository.create_note(lesson.id, "Title", "Body")
    repository.delete_note(note)
    with pytest.raises(NotFoundError):
        repository.update_note(note, "Title", "New body")
    with pytest.raises(NotFoundError):
        repository.delete_note(note)


def test_sql_text_is_data(repository):
    title = "'); DROP TABLE lessons; --"
    lesson = repository.create_lesson(title)
    note = repository.create_note(lesson.id, title, title)
    assert repository.list_lessons() == [lesson]
    assert repository.list_notes(lesson.id) == [note]


def test_stale_note_cannot_overwrite_or_delete(repository):
    lesson = repository.create_lesson("Lesson")
    old = repository.create_note(lesson.id, "Title", "First")
    new = repository.update_note(old, "Title", "Second")
    with pytest.raises(ConflictError):
        repository.update_note(old, "Title", "Lost update")
    with pytest.raises(ConflictError):
        repository.delete_note(old)
    assert repository.list_notes(lesson.id) == [new]


def test_two_connections_detect_conflicts(database, repository):
    lesson = repository.create_lesson("Lesson")
    other = Database(database.path)
    try:
        second = SQLiteNotesRepository(other)
        new = second.update_lesson(lesson, "Renamed elsewhere")
        with pytest.raises(ConflictError):
            repository.update_lesson(lesson, "Old revision")
        assert repository.list_lessons() == [new]
    finally:
        other.close()


def test_transaction_rolls_back_on_failure(database):
    with pytest.raises(StorageError):
        with database.transaction() as connection:
            connection.execute("INSERT INTO lessons VALUES('x','title','now','now',1,NULL)")
            connection.execute("INSERT INTO notes VALUES('y','missing','','','now','now',1,NULL)")
    assert database.connection.execute("SELECT count(*) FROM lessons").fetchone()[0] == 0


def test_write_failure_does_not_report_success_or_change_record(database, repository):
    lesson = repository.create_lesson("Lesson")
    note = repository.create_note(lesson.id, "Title", "Saved")
    database.connection.execute("PRAGMA query_only=ON")
    with pytest.raises(StorageError):
        repository.update_note(note, "Title", "Unsaved")
    assert repository.list_notes(lesson.id) == [note]
    database.connection.execute("PRAGMA query_only=OFF")
    assert repository.update_note(note, "Title", "Recovered").content == "Recovered"


def test_newer_database_is_not_downgraded(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=999")
        connection.execute("CREATE TABLE future_data(value TEXT)")
        connection.execute("INSERT INTO future_data VALUES('keep')")
    with pytest.raises(StorageError, match="новой версией"):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 999
        assert connection.execute("SELECT * FROM future_data").fetchone()[0] == "keep"


def test_invalid_database_is_not_replaced(tmp_path):
    path = tmp_path / "invalid.sqlite3"
    path.write_bytes(b"not a database")
    with pytest.raises(StorageError):
        Database(path)
    assert path.read_bytes() == b"not a database"


def test_closed_database_has_controlled_errors(database, repository):
    database.close()
    database.close()
    with pytest.raises(StorageError):
        repository.list_lessons()
    with pytest.raises(StorageError):
        repository.create_lesson("Closed")


def test_failed_migration_rolls_back_schema_and_version(tmp_path, monkeypatch):
    from englishnotes.storage import database as module

    path = tmp_path / "migration.sqlite3"
    monkeypatch.setitem(
        module.MIGRATIONS,
        1,
        ("CREATE TABLE temporary_table(id TEXT)", "INVALID SQL"),
    )
    with pytest.raises(StorageError):
        Database(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []
        )


def test_locked_database_rejects_write_and_recovers(database, repository):
    lesson = repository.create_lesson("Lesson")
    database.connection.execute("PRAGMA busy_timeout=30")
    blocker = sqlite3.connect(database.path)
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(StorageError):
            repository.create_note(lesson.id, "Not saved", "")
        assert repository.list_notes(lesson.id) == []
    finally:
        blocker.rollback()
        blocker.close()
    assert repository.create_note(lesson.id, "Recovered", "").title == "Recovered"


def test_invalid_data_directory_has_controlled_error(tmp_path):
    parent = tmp_path / "file_instead_of_directory"
    parent.write_text("keep", encoding="utf-8")
    with pytest.raises(StorageError):
        Database(parent / "notes.sqlite3")
    assert parent.read_text(encoding="utf-8") == "keep"
