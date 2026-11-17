import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from englishnotes.domain.errors import StorageError
from englishnotes.storage.cloud_schema import STATEMENTS

SCHEMA_VERSION = 2
MIGRATIONS = {
    1: (
        """CREATE TABLE lessons (
            id TEXT PRIMARY KEY, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            deleted_at TEXT
        )""",
        """CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            lesson_id TEXT NOT NULL REFERENCES lessons(id),
            title TEXT NOT NULL, content TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
            deleted_at TEXT
        )""",
        "CREATE INDEX notes_by_lesson ON notes(lesson_id, deleted_at, created_at, id)",
        "CREATE INDEX lessons_by_date ON lessons(deleted_at, created_at DESC, id)",
    ),
    2: STATEMENTS,
}


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(self.path, timeout=5)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA temp_store = MEMORY")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise StorageError(
                    "База создана более новой версией EnglishNotes. Обновите приложение."
                )
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = FULL")
            with self.transaction() as connection:
                # Read again under the write lock: another instance may have migrated it.
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version > SCHEMA_VERSION:
                    raise StorageError("Обновите EnglishNotes для работы с этой базой.")
                for target in range(version + 1, SCHEMA_VERSION + 1):
                    for statement in MIGRATIONS[target]:
                        connection.execute(statement)
                    connection.execute(f"PRAGMA user_version = {target}")
        except (OSError, sqlite3.Error, StorageError) as error:
            self.close()
            if isinstance(error, StorageError):
                raise
            raise StorageError("Не удалось открыть локальную базу данных.") from error

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        if self.connection is None:
            raise StorageError("База данных закрыта.")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            self.connection.commit()
        except BaseException as error:
            self.connection.rollback()
            if isinstance(error, sqlite3.Error):
                raise StorageError("Не удалось сохранить изменения в локальную базу.") from error
            raise

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None
