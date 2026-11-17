import tempfile

import pytest

from englishnotes.storage import runtime


def test_windows_temp_files_use_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime, "data_directory", lambda: tmp_path)
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "C:/old-temp")
    monkeypatch.setenv("TMP", "C:/old-temp")
    runtime.configure_runtime()
    assert tempfile.gettempdir() == str(tmp_path / "temp")
    with tempfile.TemporaryFile() as file:
        file.write(b"on D data directory")
    assert runtime.os.environ["TEMP"] == str(tmp_path / "temp")
    assert runtime.os.environ["TMP"] == str(tmp_path / "temp")


def test_unavailable_d_does_not_fall_back(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    unavailable = tmp_path / "unavailable"
    unavailable.write_text("blocked")
    monkeypatch.setattr(runtime, "data_directory", lambda: unavailable)
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setenv("TEMP", "C:/old-temp")
    with pytest.raises(OSError):
        runtime.configure_runtime()
    assert tempfile.tempdir is None
    assert unavailable.read_text() == "blocked"


def test_other_platforms_keep_existing_runtime(monkeypatch):
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("TEMP", "/existing-temp")
    runtime.configure_runtime()
    assert runtime.os.environ["TEMP"] == "/existing-temp"
