import sys

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox

from englishnotes.application.service import NotesService
from englishnotes.cloud.config import CloudConfig
from englishnotes.domain.errors import EnglishNotesError, StorageError
from englishnotes.storage.database import Database
from englishnotes.storage.migration import migrate_legacy_database
from englishnotes.storage.paths import database_path, legacy_database_path
from englishnotes.storage.repository import SQLiteNotesRepository
from englishnotes.storage.runtime import configure_runtime
from englishnotes.ui.main_window import MainWindow


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName("EnglishNotes")
    application.setOrganizationName("EnglishNotes")
    database = None
    lock = None
    legacy_lock = None
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
        legacy = legacy_database_path()
        if not path.exists() and legacy is not None and legacy.is_file():
            legacy_lock = QLockFile(str(legacy.parent / "englishnotes.lock"))
            legacy_lock.setStaleLockTime(0)
            if not legacy_lock.tryLock(0):
                raise StorageError(
                    "Закройте старую версию EnglishNotes и проверьте доступ к её папке данных."
                )
        migrated = migrate_legacy_database(legacy, path)
        database = Database(path)
        window = MainWindow(NotesService(SQLiteNotesRepository(database)))
        from englishnotes.ui.cloud_bridge import CloudBridge

        try:
            config = CloudConfig.load()
        except ValueError, OSError:
            config = None
        window.cloud_bridge = CloudBridge(window, database, config)
        if migrated:
            window.statusBar().showMessage("Занятия перенесены. Исходная база на D: сохранена.")
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
        if legacy_lock:
            legacy_lock.unlock()
        if lock:
            lock.unlock()
