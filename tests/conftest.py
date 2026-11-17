import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from englishnotes.application.service import NotesService  # noqa: E402
from englishnotes.storage.database import Database  # noqa: E402
from englishnotes.storage.repository import SQLiteNotesRepository  # noqa: E402


@pytest.fixture
def database(tmp_path):
    database = Database(tmp_path / "data" / "notes.sqlite3")
    yield database
    database.close()


@pytest.fixture
def repository(database):
    return SQLiteNotesRepository(database)


@pytest.fixture
def service(repository):
    return NotesService(repository)
