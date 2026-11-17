import threading

from PySide6.QtCore import QThread, Signal

from englishnotes.auth.session import SessionManager
from englishnotes.auth.vault import SystemVault
from englishnotes.cloud.engine import SyncEngine
from englishnotes.cloud.realtime import RealtimeHints
from englishnotes.cloud.transport import CloudError, SupabaseHTTP
from englishnotes.storage.cloud_store import CloudStore
from englishnotes.storage.database import Database

MESSAGES = {
    "offline": "Нет связи с облаком. Изменения сохраняются на компьютере.",
    "rate_limited": "Слишком много запросов. Синхронизация продолжится автоматически.",
    "cloud_paused": "Облачные операции временно приостановлены. Локальные данные доступны.",
    "budget_exhausted": "Достигнут общий лимит облака. Локальные изменения остаются в очереди.",
    "storage_budget_exhausted": "Облачное хранилище заполнено. Локальные записи сохранены.",
    "invalid_invitation": "Приглашение неверно, использовано или истекло.",
    "session_closed": "Занятие завершено. Локальные изменения сохранены.",
    "migration_required": "Сервер ещё не обновлён для совместных занятий.",
    "auth_rejected": "Облачный вход недоступен. Сохранённая учётная запись не заменена.",
    "session_limit": "Достигнут лимит занятий. Локальная работа доступна.",
    "note_too_large_or_invalid": "Заметка превышает облачный лимит. Текст сохранён локально.",
}


class CloudWorker(QThread):
    changed = Signal(str)
    state = Signal(str, str)

    def __init__(self, path, config):
        super().__init__()
        self.path = path
        self.config = config
        self.wakeup = threading.Event()
        self.stopping = threading.Event()

    def wake(self):
        self.wakeup.set()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()

    def run(self):
        database = None
        hints = None
        backoff = 2
        try:
            database = Database(self.path)
            store = CloudStore(database)
            vault = SystemVault(self.config.credential_service(self.path))
            transport = SupabaseHTTP(self.config)
            engine = SyncEngine(store, SessionManager(transport, vault), transport, vault)
            engine.cancelled = self.stopping.is_set
            hints = RealtimeHints(self.config, self.wake)
            while not self.stopping.is_set():
                notification = self.wakeup.is_set()
                self.wakeup.clear()
                try:
                    if notification:
                        engine.force_read = True
                    if engine.cycle():
                        self.changed.emit(engine.uid)
                    topics = [
                        r["remote_id"]
                        for r in store.rows(
                            "SELECT remote_id FROM cloud_lessons WHERE account_id=? AND "
                            "remote_id IS NOT NULL AND status='active'",
                            (engine.uid,),
                        )
                    ]
                    hints.configure(engine.sessions.identity.access_token, topics)
                    if engine.warning:
                        self.state.emit(
                            engine.warning,
                            MESSAGES.get(engine.warning, "Локальные изменения ожидают отправки."),
                        )
                        engine.warning = None
                    else:
                        self.state.emit(
                            "online",
                            "Подключено"
                            + (" • Realtime" if hints.connected else " • проверка изменений"),
                        )
                    backoff = 2
                    self.wakeup.wait(2)
                except CloudError as error:
                    self.state.emit(
                        error.code,
                        MESSAGES.get(
                            error.code, "Облако временно недоступно. Локальные данные сохранены."
                        ),
                    )
                    self.wakeup.wait(backoff)
                    backoff = min(backoff * 2, 120)
        except Exception:
            self.state.emit(
                "unavailable",
                "Облачный вход недоступен. Проверьте системное хранилище учётных данных.",
            )
        finally:
            if hints:
                hints.close()
            if database:
                database.close()
