"""Copy the legacy SQLite database without deleting or overwriting user files."""

import os
import sqlite3
import tempfile
import time
from contextlib import closing, suppress
from pathlib import Path

from englishnotes.domain.errors import StorageError
from englishnotes.storage.database import SCHEMA_VERSION


def migrate_legacy_database(source: Path | None, target: Path) -> bool:
    """Caller holds both application locks. Backup includes committed WAL data.

    Publish the validated snapshot atomically with a hard link: an existing
    target can never be replaced. The source is retained as a recovery copy.
    """
    temporary: Path | None = None
    try:
        if os.path.lexists(target) or source is None:
            return False
        try:
            source.stat()
        except FileNotFoundError:
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix="migration-", suffix=".sqlite3", dir=target.parent
        )
        os.close(descriptor)
        temporary = Path(name)
        deadline = time.monotonic() + 10

        def progress(status: int, remaining: int, total: int) -> None:
            if time.monotonic() > deadline:
                raise StorageError(
                    "Старая база занята. Закройте прежнюю версию и повторите запуск."
                )

        uri = source.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=2)) as old:
            with closing(sqlite3.connect(temporary)) as snapshot:
                old.backup(snapshot, pages=256, progress=progress, sleep=0.05)
                if snapshot.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise StorageError("Проверка старой базы не пройдена. Исходник сохранён.")
                if snapshot.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    raise StorageError("Версия старой базы не поддерживается для переноса.")
                for table, columns in (
                    ("lessons", "id,title,created_at,updated_at,revision,deleted_at"),
                    (
                        "notes",
                        "id,lesson_id,title,content,created_at,updated_at,revision,deleted_at",
                    ),
                ):
                    snapshot.execute(f"SELECT {columns} FROM {table} LIMIT 0")
                if snapshot.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise StorageError("В старой базе нарушены связи. Исходник сохранён.")
                snapshot.execute("PRAGMA journal_mode=DELETE")
        with temporary.open("r+b") as file:
            os.fsync(file.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            return False
        return True
    except (OSError, sqlite3.Error) as error:
        raise StorageError(
            "Не удалось перенести базу из D:\\EnglishNotesData. "
            "Исходная база сохранена. Проверьте доступ и свободное место."
        ) from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
