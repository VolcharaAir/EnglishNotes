import tempfile

import pytest

from englishnotes.domain.errors import StorageError
from englishnotes.storage import runtime


def test_windows_temp_files_use_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "database_path", lambda: tmp_path / "notes.sqlite3")
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "C:/old-temp")
    monkeypatch.setenv("TMP", "C:/old-temp")
    runtime.configure_runtime()
    assert tempfile.gettempdir() == str(tmp_path / "temp")
    with tempfile.TemporaryFile() as file:
        file.write(b"in user data directory")
    assert runtime.os.environ["TEMP"] == str(tmp_path / "temp")
    assert runtime.os.environ["TMP"] == str(tmp_path / "temp")


def test_unavailable_profile_does_not_fall_back(monkeypatch, tmp_path):
    unavailable = tmp_path / "unavailable"
    unavailable.write_text("blocked")
    monkeypatch.setattr(runtime, "database_path", lambda: unavailable / "notes.sqlite3")
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "C:/old-temp")
    with pytest.raises(OSError):
        runtime.configure_runtime()
    assert tempfile.tempdir is None
    assert unavailable.read_text() == "blocked"


def test_runtime_creates_parents(monkeypatch, tmp_path):
    location = tmp_path / "missing" / "profile"
    monkeypatch.setattr(runtime, "database_path", lambda: location / "notes.sqlite3")
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "/existing-temp")
    monkeypatch.setenv("TMP", "/existing-temp")
    runtime.configure_runtime()
    assert (location / "temp").is_dir()
    assert tempfile.gettempdir() == str(location / "temp")


def test_invalid_relative_profile_does_not_write_to_working_directory(monkeypatch, tmp_path):
    from englishnotes.storage import paths

    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "relative-profile")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(StorageError, match="абсолютный"):
        runtime.configure_runtime()
    assert not (tmp_path / "relative-profile").exists()
