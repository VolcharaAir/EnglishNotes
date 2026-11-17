import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from englishnotes.domain.errors import ConflictError, NotFoundError, StorageError
from englishnotes.domain.models import Lesson, Note
from englishnotes.storage.database import Database


def timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


class SQLiteNotesRepository:
    def __init__(self, database: Database):
        self.database = database

    def _read(self, sql: str, parameters: tuple = ()) -> list[sqlite3.Row]:
        connection = self.database.connection
        if connection is None:
            raise StorageError("База данных закрыта.")
        try:
            return connection.execute(sql, parameters).fetchall()
        except sqlite3.Error as error:
            raise StorageError("Не удалось прочитать локальные данные.") from error

    @staticmethod
    def _lesson(row: sqlite3.Row) -> Lesson:
        return Lesson(*(row[key] for key in Lesson.__dataclass_fields__))

    @staticmethod
    def _note(row: sqlite3.Row) -> Note:
        return Note(*(row[key] for key in Note.__dataclass_fields__))

    @staticmethod
    def _require_lesson(connection: sqlite3.Connection, lesson_id: str) -> None:
        if not connection.execute(
            "SELECT 1 FROM lessons WHERE id=? AND deleted_at IS NULL", (lesson_id,)
        ).fetchone():
            raise NotFoundError("Занятие не найдено.")

    @staticmethod
    def _check_note(connection: sqlite3.Connection, note: Note) -> None:
        row = connection.execute(
            "SELECT revision FROM notes WHERE id=? AND lesson_id=? AND deleted_at IS NULL",
            (note.id, note.lesson_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Заметка не найдена.")
        if row["revision"] != note.revision:
            raise ConflictError(
                "Заметка изменена в другом окне. Скопируйте текст и откройте её заново."
            )

    def list_lessons(self) -> list[Lesson]:
        return [
            self._lesson(row)
            for row in self._read(
                "SELECT * FROM lessons WHERE deleted_at IS NULL ORDER BY created_at DESC, id"
            )
        ]

    def create_lesson(self, title: str) -> Lesson:
        now = timestamp()
        lesson = Lesson(str(uuid4()), title, now, now, 1)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO lessons(id,title,created_at,updated_at,revision) VALUES(?,?,?,?,?)",
                (lesson.id, title, now, now, 1),
            )
        return lesson

    def update_lesson(self, lesson: Lesson, title: str) -> Lesson:
        now = timestamp()
        with self.database.transaction() as connection:
            self._require_lesson(connection, lesson.id)
            result = connection.execute(
                "UPDATE lessons SET title=?,updated_at=?,revision=revision+1 "
                "WHERE id=? AND revision=? AND deleted_at IS NULL",
                (title, now, lesson.id, lesson.revision),
            )
            if result.rowcount != 1:
                raise ConflictError("Название занятия изменено в другом окне.")
        return Lesson(lesson.id, title, lesson.created_at, now, lesson.revision + 1)

    def list_notes(self, lesson_id: str) -> list[Note]:
        return [
            self._note(row)
            for row in self._read(
                "SELECT n.* FROM notes n JOIN lessons l ON l.id=n.lesson_id "
                "WHERE n.lesson_id=? AND n.deleted_at IS NULL AND l.deleted_at IS NULL "
                "ORDER BY n.created_at, n.id",
                (lesson_id,),
            )
        ]

    def create_note(self, lesson_id: str, title: str, content: str) -> Note:
        now = timestamp()
        note = Note(str(uuid4()), lesson_id, title, content, now, now, 1)
        with self.database.transaction() as connection:
            self._require_lesson(connection, lesson_id)
            connection.execute(
                "INSERT INTO notes(id,lesson_id,title,content,created_at,updated_at,revision) "
                "VALUES(?,?,?,?,?,?,?)",
                (note.id, lesson_id, title, content, now, now, 1),
            )
        return note

    def update_note(self, note: Note, title: str, content: str) -> Note:
        now = timestamp()
        with self.database.transaction() as connection:
            self._require_lesson(connection, note.lesson_id)
            self._check_note(connection, note)
            connection.execute(
                "UPDATE notes SET title=?,content=?,updated_at=?,revision=revision+1 WHERE id=?",
                (title, content, now, note.id),
            )
        return Note(
            note.id, note.lesson_id, title, content, note.created_at, now, note.revision + 1
        )

    def delete_note(self, note: Note) -> None:
        with self.database.transaction() as connection:
            self._require_lesson(connection, note.lesson_id)
            self._check_note(connection, note)
            now = timestamp()
            connection.execute(
                "UPDATE notes SET deleted_at=?,updated_at=?,revision=revision+1 WHERE id=?",
                (now, now, note.id),
            )
