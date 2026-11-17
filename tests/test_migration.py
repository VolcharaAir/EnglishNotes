import os
import sqlite3

import pytest

from englishnotes.domain.errors import StorageError
from englishnotes.storage import migration
from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "legacy" / "englishnotes.sqlite3"
    database = Database(path)
    repo = SQLiteNotesRepository(database)
    lesson = repo.create_lesson("Прежнее занятие")
    note = repo.create_note(lesson.id, "Vocabulary", "Don't lose this\nПривет ✅")
    deleted = repo.create_note(lesson.id, "Removed", "Keep tombstone")
    repo.delete_note(deleted)
    database.close()
    return path, lesson, note, deleted


def test_migration_preserves_all_data_and_source(legacy, tmp_path):
    source, lesson, note, deleted = legacy
    before = source.read_bytes()
    target = tmp_path / "profile" / "englishnotes.sqlite3"
    assert migration.migrate_legacy_database(source, target)
    assert source.read_bytes() == before
    database = Database(target)
    try:
        repo = SQLiteNotesRepository(database)
        assert repo.list_lessons() == [lesson]
        assert repo.list_notes(lesson.id) == [note]
        assert database.connection.execute(
            "SELECT deleted_at FROM notes WHERE id=?", (deleted.id,)
        ).fetchone()[0]
    finally:
        database.close()
    assert not migration.migrate_legacy_database(source, target)
    assert list(target.parent.glob("migration-*")) == []


def test_committed_wal_data_is_included(tmp_path):
    source = tmp_path / "legacy.sqlite3"
    target = tmp_path / "profile" / "notes.sqlite3"
    database = Database(source)
    try:
        repo = SQLiteNotesRepository(database)
        lesson = repo.create_lesson("WAL")
        note = repo.create_note(lesson.id, "WAL note", "Committed but not checkpointed")
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        assert migration.migrate_legacy_database(source, target)
    finally:
        database.close()
    migrated = Database(target)
    try:
        assert SQLiteNotesRepository(migrated).list_notes(lesson.id) == [note]
    finally:
        migrated.close()


def test_existing_target_always_wins_even_if_corrupt(legacy, tmp_path):
    target = tmp_path / "existing.sqlite3"
    target.write_bytes(b"keep this file; never replace it")
    assert not migration.migrate_legacy_database(legacy[0], target)
    assert target.read_bytes() == b"keep this file; never replace it"


def test_second_database_is_not_merged_or_overwritten(legacy, tmp_path):
    target = tmp_path / "existing.sqlite3"
    database = Database(target)
    own_lesson = SQLiteNotesRepository(database).create_lesson("Existing")
    database.close()
    assert not migration.migrate_legacy_database(legacy[0], target)
    database = Database(target)
    try:
        assert SQLiteNotesRepository(database).list_lessons() == [own_lesson]
    finally:
        database.close()


@pytest.mark.parametrize("source_kind", ["missing", "disabled"])
def test_missing_d_does_not_create_legacy_or_target(tmp_path, source_kind):
    source = tmp_path / "no-drive-d" / "old.sqlite3" if source_kind == "missing" else None
    target = tmp_path / "profile" / "notes.sqlite3"
    assert not migration.migrate_legacy_database(source, target)
    assert not target.exists()
    assert not (tmp_path / "no-drive-d").exists()


@pytest.mark.parametrize("kind", ["corrupt", "empty", "future", "wrong_schema"])
def test_invalid_source_never_publishes_target(tmp_path, kind):
    source = tmp_path / "old.sqlite3"
    if kind == "corrupt":
        source.write_bytes(b"not SQLite")
    else:
        with sqlite3.connect(source) as connection:
            if kind == "future":
                connection.execute("PRAGMA user_version=999")
            if kind == "wrong_schema":
                connection.execute("PRAGMA user_version=1")
    before = source.read_bytes()
    target = tmp_path / "profile" / "notes.sqlite3"
    with pytest.raises(StorageError):
        migration.migrate_legacy_database(source, target)
    assert not target.exists()
    assert source.read_bytes() == before
    assert list(target.parent.glob("migration-*")) == []


def test_atomic_publish_does_not_overwrite_racing_target(legacy, tmp_path, monkeypatch):
    target = tmp_path / "profile" / "notes.sqlite3"
    original_link = os.link

    def race(source, destination):
        target.write_bytes(b"created by another process")
        return original_link(source, destination)

    monkeypatch.setattr(migration.os, "link", race)
    assert not migration.migrate_legacy_database(legacy[0], target)
    assert target.read_bytes() == b"created by another process"


def test_access_error_retains_source_and_removes_staging(legacy, tmp_path, monkeypatch):
    target = tmp_path / "profile" / "notes.sqlite3"
    before = legacy[0].read_bytes()

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(migration.os, "link", denied)
    with pytest.raises(StorageError):
        migration.migrate_legacy_database(legacy[0], target)
    assert legacy[0].read_bytes() == before
    assert not target.exists()
    assert list(target.parent.glob("migration-*")) == []


def test_migration_timeout_keeps_source(legacy, tmp_path, monkeypatch):
    clock = iter([0, 11])
    monkeypatch.setattr(migration.time, "monotonic", lambda: next(clock))
    target = tmp_path / "profile" / "notes.sqlite3"
    with pytest.raises(StorageError, match="занята"):
        migration.migrate_legacy_database(legacy[0], target)
    assert legacy[0].is_file()
    assert not target.exists()


def test_foreign_key_violation_is_not_migrated(legacy, tmp_path):
    with sqlite3.connect(legacy[0]) as connection:
        connection.execute("UPDATE notes SET lesson_id='missing'")
    target = tmp_path / "profile" / "notes.sqlite3"
    with pytest.raises(StorageError, match="связи"):
        migration.migrate_legacy_database(legacy[0], target)
    assert not target.exists()
