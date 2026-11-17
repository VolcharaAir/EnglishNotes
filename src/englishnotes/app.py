import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from englishnotes.application.service import NotesService
from englishnotes.domain.errors import EnglishNotesError, StorageError
from englishnotes.storage.database import Database
from englishnotes.storage.paths import database_path
from englishnotes.storage.repository import SQLiteNotesRepository
from englishnotes.storage.runtime import configure_runtime
from englishnotes.ui.main_window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("EnglishNotes")
    application.setOrganizationName("EnglishNotes")
    database = None
    lock = None
    try:
        configure_runtime()
        path = database_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(path.parent / "englishnotes.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            raise StorageError(
                "EnglishNotes уже запущено или папка данных недоступна. "
                "Переключитесь на открытое окно приложения и проверьте права на папку данных."
            )
        database = Database(path)
        window = MainWindow(NotesService(SQLiteNotesRepository(database)))
        window.show()
        return application.exec()
    except (EnglishNotesError, OSError) as error:
        QMessageBox.critical(
            None,
            "Не удалось запустить EnglishNotes",
            f"{error}\n\nПроверьте доступ к папке данных. Существующие записи не удалены.",
        )
        return 1
    finally:
        if database:
            database.close()
        if lock:
            lock.unlock()
