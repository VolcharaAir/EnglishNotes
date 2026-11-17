from datetime import datetime

from englishnotes.application.ports import NotesRepository
from englishnotes.domain.errors import ValidationError
from englishnotes.domain.models import Lesson, Note


class NotesService:
    def __init__(self, repository: NotesRepository):
        self.repository = repository

    @staticmethod
    def _title(value: str) -> str:
        if not isinstance(value, str) or len(value) > 200:
            raise ValidationError("Название должно содержать не больше 200 символов.")
        return value.strip()

    def list_lessons(self) -> list[Lesson]:
        return self.repository.list_lessons()

    def create_lesson(self) -> Lesson:
        title = f"Занятие {datetime.now():%d.%m.%Y %H:%M}"
        return self.repository.create_lesson(title)

    def rename_lesson(self, lesson: Lesson, title: str) -> Lesson:
        return self.repository.update_lesson(lesson, self._title(title))

    def list_notes(self, lesson_id: str) -> list[Note]:
        return self.repository.list_notes(lesson_id)

    def create_note(self, lesson_id: str) -> Note:
        return self.repository.create_note(lesson_id, "Новая заметка", "")

    def save_note(self, note: Note, title: str, content: str) -> Note:
        if not isinstance(content, str):
            raise ValidationError("Текст заметки должен быть строкой.")
        return self.repository.update_note(note, self._title(title), content)

    def delete_note(self, note: Note) -> None:
        self.repository.delete_note(note)
