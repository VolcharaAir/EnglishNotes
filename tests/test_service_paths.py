from pathlib import Path

import pytest

from englishnotes.domain.errors import StorageError, ValidationError
from englishnotes.storage import paths


def test_service_crud_and_title_normalization(service):
    lesson = service.create_lesson()
    lesson = service.rename_lesson(lesson, "  English lesson  ")
    assert lesson.title == "English lesson"
    note = service.create_note(lesson.id)
    note = service.save_note(note, " Vocabulary ", "  Do not trim text\n")
    assert note.title == "Vocabulary"
    assert note.content == "  Do not trim text\n"
    service.delete_note(note)
    assert service.list_notes(lesson.id) == []


@pytest.mark.parametrize("title", ["a" * 201, None, 123])
def test_invalid_title_does_not_change_storage(service, title):
    lesson = service.create_lesson()
    note = service.create_note(lesson.id)
    with pytest.raises(ValidationError):
        service.save_note(note, title, "Changed")
    with pytest.raises(ValidationError):
        service.rename_lesson(lesson, title)
    assert service.list_notes(lesson.id) == [note]
    assert service.list_lessons() == [lesson]


def test_blank_titles_and_empty_note_are_saved(service):
    lesson = service.create_lesson()
    lesson = service.rename_lesson(lesson, "")
    note = service.create_note(lesson.id)
    note = service.save_note(note, "", "")
    assert service.list_lessons() == [lesson]
    assert service.list_notes(lesson.id) == [note]


def test_invalid_body_does_not_change_storage(service):
    lesson = service.create_lesson()
    note = service.create_note(lesson.id)
    with pytest.raises(ValidationError):
        service.save_note(note, "Title", None)
    assert service.list_notes(lesson.id) == [note]


def test_windows_uses_localappdata_without_drive_d(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/Person/AppData/Local")
    assert paths.database_path().as_posix() == (
        "C:/Users/Person/AppData/Local/EnglishNotes/englishnotes.sqlite3"
    )


def test_windows_fallback_uses_user_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.data_directory() == tmp_path / "AppData" / "Local" / "EnglishNotes"


def test_macos_uses_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.database_path() == (
        tmp_path / "Library" / "Application Support" / "EnglishNotes" / "englishnotes.sqlite3"
    )


def test_changing_executable_and_cwd_does_not_change_database(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "profile"))
    original = paths.database_path()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths.sys, "executable", str(tmp_path / "moved" / "EnglishNotes.exe"))
    monkeypatch.setattr(paths.sys, "_MEIPASS", str(tmp_path / "extracted"), raising=False)
    assert paths.database_path() == original


def test_linux_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.database_path() == tmp_path / "EnglishNotes" / "englishnotes.sqlite3"


def test_relative_data_directory_is_rejected(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(StorageError):
        paths.database_path()


def test_linux_default_uses_user_share(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert paths.data_directory() == tmp_path / ".local" / "share" / "EnglishNotes"
