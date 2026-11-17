from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Lesson:
    id: str
    title: str
    created_at: str
    updated_at: str
    revision: int


@dataclass(frozen=True, slots=True)
class Note:
    id: str
    lesson_id: str
    title: str
    content: str
    created_at: str
    updated_at: str
    revision: int
