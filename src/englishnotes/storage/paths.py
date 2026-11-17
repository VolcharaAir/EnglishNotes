import os
import sys
from pathlib import Path, PureWindowsPath

from englishnotes.domain.errors import StorageError


def data_directory() -> Path:
    """Never derive writable data paths from cwd, __file__ or the executable."""
    if override := os.environ.get("ENGLISHNOTES_DATA_DIR"):
        return Path(override)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / "EnglishNotes"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "EnglishNotes"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / (
        "EnglishNotes"
    )


def database_path() -> Path:
    directory = data_directory()
    absolute = (
        PureWindowsPath(str(directory)).is_absolute()
        if sys.platform == "win32"
        else directory.is_absolute()
    )
    if not absolute:
        raise StorageError("Папка данных должна иметь абсолютный путь.")
    return directory / "englishnotes.sqlite3"


def legacy_database_path() -> Path | None:
    return Path("D:/EnglishNotesData/englishnotes.sqlite3") if sys.platform == "win32" else None
