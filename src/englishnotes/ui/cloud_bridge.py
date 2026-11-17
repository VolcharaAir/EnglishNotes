import json
from datetime import UTC, datetime
from uuid import uuid4

from PySide6.QtCore import QObject, QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from englishnotes.auth.vault import SystemVault
from englishnotes.cloud.worker import CloudWorker
from englishnotes.storage.cloud_store import CloudStore
from englishnotes.ui.icons import icon
from englishnotes.ui.style import tone


class CloudBridge(QObject):
    def __init__(self, window, database, config):
        super().__init__(window)
        self.window = window
        self.store = CloudStore(database)
        self.config = config
        self.uid = None
        self.worker = None
        self.vault = None
        self.refreshing = False
        self.create_button = QPushButton("Создать занятие")
        self.join_button = QPushButton("Подключиться к занятию")
        self.invite_button = QPushButton("Пригласить")
        self.finish_button = QPushButton("Завершить")
        self.conflict_button = QPushButton("Разрешить конфликт")
        self.status = QLabel("Облако: ожидание подключения")
        self.status.setObjectName("syncStatus")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.pending = QLabel()
        self.pending.setObjectName("syncPending")
        self.pending.setWordWrap(True)
        window.new_lesson_button.setToolTip("Создать занятие только на этом компьютере")
        self.conflict_button.setToolTip("Сравнить версии при одновременных изменениях")
        self.create_button.setObjectName("primary")
        self.create_button.setIcon(icon("users", "#151b33"))
        self.join_button.setIcon(icon("join"))
        self.invite_button.setIcon(icon("users"))
        self.invite_button.setAccessibleName("Пригласить участника")
        self.invite_button.setToolTip("Показать код приглашения")
        self.finish_button.setIcon(icon("finish"))
        self.finish_button.setAccessibleName("Завершить занятие")
        self.conflict_button.setObjectName("warning")
        self.conflict_button.setIcon(icon("conflict", "#edc183"))
        for button in (self.invite_button, self.finish_button):
            button.setProperty("variant", "ghost")
            window.lesson_actions.addWidget(button)
        window.session_actions.insertWidget(0, self.create_button)
        window.session_actions.addWidget(self.join_button)
        for widget in (self.status, self.pending, self.conflict_button):
            window.sync_details.addWidget(widget)
        for button in (
            self.create_button,
            self.join_button,
            self.invite_button,
            self.finish_button,
            self.conflict_button,
        ):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_button.clicked.connect(self.create)
        self.join_button.clicked.connect(self.join)
        self.invite_button.clicked.connect(self.invite)
        self.finish_button.clicked.connect(self.finish)
        self.conflict_button.clicked.connect(self.resolve)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_controls)
        self.timer.start(700)
        if config:
            try:
                self.vault = SystemVault(config.credential_service(database.path))
                saved = self.vault.get("auth")
                if saved:
                    self.uid = saved.get("uid")
                self.worker = CloudWorker(database.path, config)
                self.worker.changed.connect(self.received)
                self.worker.state.connect(self.on_state)
                self.worker.finished.connect(self.worker_finished)
                self.worker.start()
            except Exception:
                self.status.setText(
                    "Системное хранилище авторизации недоступно. Локальная работа сохранена."
                )
        else:
            self.status.setText("Эта сборка работает локально. Облачная конфигурация не включена.")
        self.update_controls()

    def on_state(self, code, message):
        self.status.setText("● Подключено к облаку" if code == "online" else message)
        tone(self.status, "online" if code == "online" else "warning")

    def wake(self):
        if self.worker:
            self.worker.wake()

    def create(self):
        if not self.window.flush_changes():
            return
        title, accepted = QInputDialog.getText(self.window, "Создать занятие", "Название занятия:")
        if not accepted or not title.strip() or len(title) > 200:
            return
        previous = self.window.lesson.id if self.window.lesson else None
        self.window.create_lesson()
        if self.window.lesson and self.window.lesson.id != previous:
            self.window.lesson_title.setText(title.strip())
            if not self.window.flush_changes():
                return
            try:
                self.store.enroll(self.window.lesson.id)
            except Exception:
                self.status.setText(
                    "Занятие сохранено локально, но не поставлено в очередь облака."
                )
                return
            self.wake()
            self.update_controls()

    def join(self):
        code, accepted = QInputDialog.getText(
            self.window, "Подключение", "Вставьте код приглашения:"
        )
        if not accepted or not code.strip():
            return
        try:
            reference = "join:" + str(uuid4())
            self.vault.put(reference, {"code": code.strip()})
            self.store.command("join", vault_key=reference)
            self.wake()
            self.status.setText("Подключение ожидает ответа сервера…")
        except Exception:
            self.status.setText(
                "Не удалось поставить подключение в очередь. Локальные заметки сохранены."
            )

    def invite(self):
        if not self.window.lesson or not self.window.flush_changes():
            return
        link = self.store.scope(self.window.lesson.id)
        if not link:
            try:
                self.store.enroll(self.window.lesson.id)
            except Exception:
                self.status.setText("Не удалось создать приглашение. Локальные записи сохранены.")
                return
            self.wake()
            self.status.setText("Создаём приглашение. Оно появится после подключения к облаку.")
            return
        if not link["remote_id"]:
            self.status.setText("Приглашение ожидает подключения к облаку.")
            return
        try:
            invitation = self.vault.get("invite:" + link["remote_id"])
            if not invitation or datetime.fromisoformat(invitation["expires_at"]) <= datetime.now(
                UTC
            ):
                self.status.setText("Приглашение уже недоступно или истекло.")
                return
            dialog = QDialog(self.window)
            dialog.setWindowTitle("Приглашение на занятие")
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(24, 24, 24, 24)
            layout.setSpacing(14)
            layout.addWidget(QLabel("Код действует до указанного времени и используется один раз."))
            value = QLineEdit(invitation["code"])
            value.setObjectName("invitationCode")
            value.setReadOnly(True)
            value.setMinimumWidth(600)
            layout.addWidget(value)
            layout.addWidget(
                QLabel(
                    "Срок: "
                    + datetime.fromisoformat(invitation["expires_at"])
                    .astimezone()
                    .strftime("%d.%m %H:%M")
                )
            )
            copy = QPushButton("Скопировать код")
            copy.setObjectName("primary")
            copy.clicked.connect(lambda: self.copy_code(value.text()))
            copy.clicked.connect(lambda: copy.setText("Код скопирован"))
            layout.addWidget(copy)
            close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            close.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
            close.rejected.connect(dialog.reject)
            layout.addWidget(close)
            dialog.exec()
        except Exception:
            self.status.setText("Не удалось прочитать приглашение из системного хранилища.")

    @staticmethod
    def copy_code(code):
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(code)

    def finish(self):
        if not self.window.lesson or not self.window.flush_changes():
            return
        if (
            QMessageBox.question(
                self.window,
                "Завершить занятие?",
                "После отправки сохранённых изменений занятие станет доступно только для чтения.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            self.store.command("finish", self.window.lesson.id)
        except Exception:
            self.status.setText("Не удалось поставить завершение в очередь. Попробуйте снова.")
            return
        self.wake()

    def received(self, uid):
        if self.refreshing or not self.window.flush_changes():
            return
        self.refreshing = True
        try:
            self.uid = uid
            lesson_id = self.window.lesson.id if self.window.lesson else None
            note_id = self.window.note.id if self.window.note else None
            cursor = self.window.note_body.textCursor()
            position, anchor = cursor.position(), cursor.anchor()
            scroll = self.window.note_body.verticalScrollBar().value()
            title_position = self.window.note_title.cursorPosition()
            self.store.apply_inbox(uid)
            # Block reload callbacks: the previous model may have a stale local revision now.
            with QSignalBlocker(self.window.lesson_list):
                self.window._reload_lessons(lesson_id)
            self.window._select_lesson(self.window.lesson_list.currentItem())
            self.window._select_id(self.window.note_list, note_id)
            if self.window.note and self.window.note.id == note_id:
                from PySide6.QtGui import QTextCursor

                cursor = self.window.note_body.textCursor()
                length = len(self.window.note_body.toPlainText())
                cursor.setPosition(min(anchor, length))
                cursor.setPosition(min(position, length), QTextCursor.MoveMode.KeepAnchor)
                self.window.note_body.setTextCursor(cursor)
                self.window.note_body.verticalScrollBar().setValue(scroll)
                self.window.note_title.setCursorPosition(title_position)
            self.update_controls()
        except Exception:
            self.status.setText(
                "Не удалось применить облачные изменения. Локальные версии сохранены."
            )
        finally:
            self.refreshing = False

    def update_controls(self):
        if self.store.db.connection is None:
            self.timer.stop()
            return
        available = bool(self.worker and self.worker.isRunning() and self.vault)
        self.create_button.setEnabled(available)
        self.join_button.setEnabled(available)
        lesson = self.window.lesson
        scope = self.store.scope(lesson.id) if lesson else None
        self.invite_button.setEnabled(
            available
            and lesson is not None
            and (not scope or scope["owner_id"] in (None, self.uid))
        )
        self.finish_button.setEnabled(
            available
            and scope is not None
            and scope["owner_id"] == self.uid
            and scope["status"] == "active"
        )
        pending = self.store.rows("SELECT count(*) AS total FROM cloud_outbox")[0]["total"]
        conflicts = self.store.rows("SELECT count(*) AS total FROM cloud_conflicts")[0]["total"]
        self.pending.setText(f"К отправке: {pending} · Конфликты: {conflicts}")
        tone(self.pending, "warning" if pending or conflicts else "neutral")
        self.conflict_button.setEnabled(bool(conflicts))
        self.conflict_button.setVisible(bool(conflicts))
        closed = bool(scope and scope["status"] == "closed")
        kind = (
            "Занятие завершено"
            if closed
            else ("Совместное занятие" if scope else "Локальное занятие")
        )
        self.window.lesson_kind.setText(kind if lesson else "Ваши занятия")
        tone(self.window.lesson_kind, "closed" if closed else "active")
        self.window.lesson_title.setReadOnly(bool(scope))
        self.window.note_title.setReadOnly(closed)
        self.window.note_body.setReadOnly(closed)
        self.window.new_note_button.setEnabled(lesson is not None and not closed)
        self.window.delete_note_button.setEnabled(self.window.note is not None and not closed)
        if self.window.note:
            meta = self.store.rows(
                "SELECT author_id FROM cloud_notes WHERE note_id=?", (self.window.note.id,)
            )
            if meta and meta[0]["author_id"]:
                author = "Вы" if meta[0]["author_id"] == self.uid else "Другой участник"
                self.window.author_meta.setText("Автор: " + author)
            else:
                self.window.author_meta.setText("Локальная заметка")

    def resolve(self):
        if not self.window.flush_changes():
            return
        selected_id = self.window.note.id if self.window.note else ""
        rows = self.store.rows(
            "SELECT * FROM cloud_conflicts ORDER BY (note_id=?) DESC LIMIT 1", (selected_id,)
        )
        if not rows:
            return
        conflict = rows[0]
        note_id = conflict["note_id"]
        local = self.store.rows("SELECT * FROM notes WHERE id=?", (note_id,))[0]
        remote = json.loads(conflict["remote_json"])
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Одновременные изменения")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(
            QLabel(
                "Выберите версию для продолжения. "
                "Обе исходные версии сохранятся для восстановления."
            )
        )
        columns = QHBoxLayout()
        versions = (
            local["title"]
            + "\n\n"
            + local["content"]
            + ("\n[Удалено вами]" if local["deleted_at"] else ""),
            remote["title"]
            + "\n\n"
            + remote["content"]
            + ("\n[Удалено участником]" if remote["deleted_at"] else ""),
        )
        for heading_text, text in zip(("МОЯ ВЕРСИЯ", "ВЕРСИЯ УЧАСТНИКА"), versions, strict=True):
            column = QVBoxLayout()
            heading = QLabel(heading_text)
            heading.setObjectName("eyebrow")
            column.addWidget(heading)
            editor = QPlainTextEdit(text)
            editor.setReadOnly(True)
            column.addWidget(editor)
            columns.addLayout(column)
        layout.addLayout(columns)
        buttons = QHBoxLayout()

        def choose(keep):
            try:
                self.store.resolve(note_id, keep, expected_revision=conflict["server_revision"])
                dialog.accept()
                self.received(self.uid)
                self.wake()
            except Exception:
                self.status.setText("Версия уже обновилась. Откройте сравнение повторно.")
                dialog.reject()

        for text, keep in (("Оставить мою", True), ("Принять вторую", False)):
            button = QPushButton(text)
            if keep:
                button.setObjectName("primary")
            button.clicked.connect(lambda checked=False, k=keep: choose(k))
            buttons.addWidget(button)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        dialog.resize(950, 600)
        dialog.exec()

    def request_close(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.window.setEnabled(False)
            self.status.setText("Завершаем сетевой запрос. Изменения уже сохранены на компьютере.")
            return False
        self.timer.stop()
        return True

    def worker_finished(self):
        if not self.window.isEnabled():
            self.window.close()
