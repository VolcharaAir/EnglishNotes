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


@pytest.mark.parametrize("appdata", ["C:/Users/Person/AppData/Local", "relative", ""])
def test_windows_always_uses_d(monkeypatch, appdata):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", appdata)
    assert paths.database_path().as_posix() == "D:/EnglishNotesData/englishnotes.sqlite3"


def test_windows_does_not_use_home_or_cwd(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    def forbidden():
        raise AssertionError("Home must never be used")

    monkeypatch.setattr(Path, "home", forbidden)
    assert paths.data_directory().as_posix() == "D:/EnglishNotesData"


def test_linux_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.database_path() == tmp_path / "EnglishNotes" / "englishnotes.sqlite3"


def test_relative_data_directory_is_rejected(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    with pytest.raises(StorageError):
        paths.database_path()
