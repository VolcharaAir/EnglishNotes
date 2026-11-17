from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from englishnotes.application.service import NotesService
from englishnotes.domain.errors import EnglishNotesError
from englishnotes.domain.models import Lesson, Note
from englishnotes.ui.delegates import EntryDelegate
from englishnotes.ui.icons import icon
from englishnotes.ui.style import apply_theme


class MainWindow(QMainWindow):
    AUTOSAVE_MS = 350
    MAX_SAVE_DELAY_MS = 2000

    def __init__(self, service: NotesService):
        super().__init__()
        self.service = service
        self.lesson: Lesson | None = None
        self.note: Note | None = None
        self._lesson_dirty = False
        self._note_dirty = False
        self._loading = False
        apply_theme(QApplication.instance())
        self.setWindowTitle("EnglishNotes[*]")
        self.resize(1280, 800)
        self.setMinimumSize(900, 600)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.flush_changes)
        self.max_save_timer = QTimer(self)
        self.max_save_timer.setSingleShot(True)
        self.max_save_timer.timeout.connect(self.flush_changes)
        self._build_ui()
        self._connect_actions()
        self._reload_lessons()

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(256)
        sidebar.setMaximumWidth(340)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 24, 18, 18)
        side.setSpacing(12)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(11)
        mark = QLabel("en")
        mark.setObjectName("brandMark")
        mark.setFixedSize(38, 38)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand_row.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(3)
        brand = QLabel("EnglishNotes")
        brand.setObjectName("brand")
        brand_text.addWidget(brand)
        subtitle = QLabel("Заметки к английскому")
        subtitle.setObjectName("subtitle")
        brand_text.addWidget(subtitle)
        brand_row.addLayout(brand_text, 1)
        side.addLayout(brand_row)
        side.addSpacing(14)

        self.session_actions = QVBoxLayout()
        self.session_actions.setSpacing(8)
        self.new_lesson_button = QPushButton("Локальное занятие")
        self.new_lesson_button.setIcon(icon("plus"))
        self.new_lesson_button.setToolTip("Новое занятие на этом компьютере · Ctrl+N")
        self.new_lesson_button.setProperty("variant", "ghost")
        self.new_lesson_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.session_actions.addWidget(self.new_lesson_button)
        side.addLayout(self.session_actions)
        side.addSpacing(12)
        history = QHBoxLayout()
        heading = QLabel("ИСТОРИЯ ЗАНЯТИЙ")
        heading.setObjectName("eyebrow")
        history.addWidget(heading)
        history.addStretch()
        self.lesson_count = QLabel("0")
        self.lesson_count.setObjectName("counter")
        history.addWidget(self.lesson_count)
        side.addLayout(history)
        self.lesson_list = QListWidget()
        self.lesson_list.setAccessibleName("История занятий")
        self.lesson_list.setItemDelegate(EntryDelegate("lesson", self.lesson_list))
        self.lesson_list.setSpacing(2)
        self.lesson_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lesson_list.setMouseTracking(True)
        side.addWidget(self.lesson_list, 1)

        sync_panel = QFrame()
        sync_panel.setObjectName("syncPanel")
        sync = QVBoxLayout(sync_panel)
        sync.setContentsMargins(13, 13, 13, 13)
        sync.setSpacing(8)
        sync_heading = QLabel("СОХРАНЕНИЕ И СВЯЗЬ")
        sync_heading.setObjectName("eyebrow")
        sync.addWidget(sync_heading)
        self.sync_details = QVBoxLayout()
        self.sync_details.setSpacing(8)
        sync.addLayout(self.sync_details)
        local = QLabel("Локальная копия доступна без интернета")
        local.setObjectName("subtitle")
        local.setWordWrap(True)
        sync.addWidget(local)
        side.addWidget(sync_panel)
        splitter.addWidget(sidebar)

        main = QWidget()
        main.setObjectName("workspace")
        layout = QVBoxLayout(main)
        layout.setContentsMargins(28, 24, 28, 16)
        layout.setSpacing(12)
        heading_row = QHBoxLayout()
        eyebrow = QLabel("РАБОЧЕЕ ПРОСТРАНСТВО")
        eyebrow.setObjectName("eyebrow")
        heading_row.addWidget(eyebrow)
        heading_row.addStretch()
        self.lesson_kind = QLabel("Ваши занятия")
        self.lesson_kind.setObjectName("lessonKind")
        heading_row.addWidget(self.lesson_kind)
        layout.addLayout(heading_row)
        self.lesson_title = QLineEdit()
        self.lesson_title.setObjectName("lessonTitle")
        self.lesson_title.setAccessibleName("Название занятия")
        self.lesson_title.setPlaceholderText("Начнём новое занятие?")
        self.lesson_title.setMaxLength(200)
        self.lesson_title.setEnabled(False)
        layout.addWidget(self.lesson_title)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.save_status = QLabel("Создайте занятие или подключитесь по приглашению")
        self.save_status.setObjectName("saveStatus")
        self.save_status.setWordWrap(True)
        top.addWidget(self.save_status, 1)
        self.lesson_actions = QHBoxLayout()
        self.lesson_actions.setSpacing(6)
        top.addLayout(self.lesson_actions)
        self.new_note_button = QPushButton("Заметка")
        self.new_note_button.setObjectName("primary")
        self.new_note_button.setIcon(icon("plus", "#151b33"))
        self.new_note_button.setToolTip("Добавить заметку · Ctrl+Shift+N")
        self.new_note_button.setAccessibleName("Добавить заметку")
        self.new_note_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.new_note_button.setEnabled(False)
        top.addWidget(self.new_note_button)
        layout.addLayout(top)
        error_row = QHBoxLayout()
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setObjectName("error")
        self.error_label.setWordWrap(True)
        self.error_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.error_label.hide()
        self.retry_button = QPushButton("Повторить сохранение")
        self.retry_button.hide()
        error_row.addWidget(self.error_label, 1)
        error_row.addWidget(self.retry_button)
        layout.addLayout(error_row)

        self.pages = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setSpacing(16)
        empty_layout.addStretch()
        empty_symbol = QLabel()
        empty_symbol.setPixmap(icon("book", "#8b9ad8", 52).pixmap(52, 52))
        empty_symbol.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_symbol)
        self.empty_label = QLabel("Хорошие занятия начинаются\nс чистой страницы")
        self.empty_label.setObjectName("empty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        empty_hint = QLabel("Новые слова, правила и маленькие открытия — всё в одном месте.")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setWordWrap(True)
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_hint)
        empty_layout.addStretch()
        self.pages.addWidget(empty)

        workspace = QSplitter(Qt.Orientation.Horizontal)
        notes_panel = QWidget()
        notes_panel.setMinimumWidth(150)
        notes_layout = QVBoxLayout(notes_panel)
        notes_layout.setContentsMargins(0, 10, 16, 0)
        notes_layout.setSpacing(12)
        notes_header = QHBoxLayout()
        label = QLabel("ЗАМЕТКИ")
        label.setObjectName("eyebrow")
        notes_header.addWidget(label)
        notes_header.addStretch()
        self.note_count = QLabel("0")
        self.note_count.setObjectName("counter")
        notes_header.addWidget(self.note_count)
        notes_layout.addLayout(notes_header)
        self.note_list = QListWidget()
        self.note_list.setAccessibleName("Заметки занятия")
        self.note_list.setItemDelegate(EntryDelegate("note", self.note_list))
        self.note_list.setMouseTracking(True)
        self.note_list.setSpacing(2)
        self.note_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        notes_layout.addWidget(self.note_list)
        workspace.addWidget(notes_panel)

        editor_panel = QWidget()
        editor = QVBoxLayout(editor_panel)
        editor.setContentsMargins(18, 0, 0, 0)
        editor.setSpacing(12)
        surface = QFrame()
        surface.setObjectName("editorSurface")
        document = QVBoxLayout(surface)
        document.setContentsMargins(20, 10, 20, 14)
        document.setSpacing(0)
        self.note_title = QLineEdit()
        self.note_title.setObjectName("noteTitle")
        self.note_title.setAccessibleName("Название заметки")
        self.note_title.setPlaceholderText("Название заметки")
        self.note_title.setMaxLength(200)
        document.addWidget(self.note_title)
        divider = QFrame()
        divider.setObjectName("editorDivider")
        divider.setFixedHeight(1)
        document.addWidget(divider)
        self.note_body = QPlainTextEdit()
        self.note_body.setObjectName("noteBody")
        self.note_body.setAccessibleName("Текст заметки")
        self.note_body.setPlaceholderText(
            "Новые слова, примеры, правила и вопросы…\n\nПишите свободно."
        )
        document.addWidget(self.note_body, 1)
        editor.addWidget(surface, 1)
        bottom = QHBoxLayout()
        self.author_meta = QLabel("Локальная заметка")
        self.author_meta.setObjectName("authorMeta")
        bottom.addWidget(self.author_meta)
        bottom.addStretch()
        self.note_meta = QLabel()
        self.note_meta.setObjectName("subtitle")
        bottom.addWidget(self.note_meta)
        self.delete_note_button = QPushButton("Удалить")
        self.delete_note_button.setAccessibleName("Удалить заметку")
        self.delete_note_button.setToolTip("Удалить заметку")
        self.delete_note_button.setIcon(icon("trash", "#e9a2ad", 17))
        self.delete_note_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_note_button.setObjectName("delete")
        bottom.addWidget(self.delete_note_button)
        editor.addLayout(bottom)
        workspace.addWidget(editor_panel)
        workspace.setSizes([190, 650])
        workspace.setCollapsible(0, False)
        workspace.setCollapsible(1, False)
        self.pages.addWidget(workspace)
        layout.addWidget(self.pages, 1)
        splitter.addWidget(main)
        splitter.setSizes([282, 998])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        self.statusBar().showMessage("Сохраняется на вашем компьютере")
        shortcut = QLabel("Ctrl+S  Сохранить")
        shortcut.setObjectName("shortcut")
        self.statusBar().addPermanentWidget(shortcut)

    def _connect_actions(self) -> None:
        self.new_lesson_button.clicked.connect(self.create_lesson)
        self.new_note_button.clicked.connect(self.create_note)
        self.delete_note_button.clicked.connect(self.delete_note)
        self.retry_button.clicked.connect(self.flush_changes)
        self.lesson_list.currentItemChanged.connect(self._select_lesson)
        self.note_list.currentItemChanged.connect(self._select_note)
        self.lesson_title.textChanged.connect(self._lesson_changed)
        self.note_title.textChanged.connect(self._note_changed)
        self.note_body.textChanged.connect(self._note_changed)
        for text, shortcut, slot in (
            ("Новое занятие", "Ctrl+N", self.create_lesson),
            ("Добавить заметку", "Ctrl+Shift+N", self.create_note),
            ("Сохранить", "Ctrl+S", self.flush_changes),
        ):
            action = QAction(text, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(slot)
            self.addAction(action)

    @staticmethod
    def _select_id(widget: QListWidget, record_id: str | None) -> None:
        for row in range(widget.count()):
            if widget.item(row).data(Qt.ItemDataRole.UserRole).id == record_id:
                widget.setCurrentRow(row)
                return
        widget.setCurrentRow(0 if widget.count() else -1)

    def _reload_lessons(self, selected_id: str | None = None) -> None:
        lessons = self.service.list_lessons()
        self.lesson_count.setText(str(len(lessons)))
        with QSignalBlocker(self.lesson_list):
            self.lesson_list.clear()
            for lesson in lessons:
                item = QListWidgetItem(self._lesson_caption(lesson))
                item.setData(Qt.ItemDataRole.UserRole, lesson)
                self.lesson_list.addItem(item)
        self._select_id(self.lesson_list, selected_id)

    @staticmethod
    def _lesson_caption(lesson: Lesson) -> str:
        date = datetime.fromisoformat(lesson.created_at).astimezone().strftime("%d.%m.%Y")
        return f"{lesson.title or 'Занятие без названия'}\n{date}"

    def _fill_notes(self, notes: list[Note], selected_id: str | None = None) -> None:
        self.note_count.setText(str(len(notes)))
        self.note = None
        with QSignalBlocker(self.note_list):
            self.note_list.clear()
            for note in notes:
                item = QListWidgetItem(note.title or "Без названия")
                item.setData(Qt.ItemDataRole.UserRole, note)
                self.note_list.addItem(item)
        self.pages.setCurrentIndex(1 if notes else 0)
        self.empty_label.setText(
            "В этом занятии пока нет заметок.\nДобавьте первую кнопкой «+ Заметка»."
        )
        self._select_id(self.note_list, selected_id)

    def _select_lesson(self, current: QListWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        if not self.flush_changes():
            with QSignalBlocker(self.lesson_list):
                self.lesson_list.setCurrentItem(previous)
            return
        lesson = current.data(Qt.ItemDataRole.UserRole)
        try:
            notes = self.service.list_notes(lesson.id)
        except EnglishNotesError as error:
            self._show_error(error)
            with QSignalBlocker(self.lesson_list):
                self.lesson_list.setCurrentItem(previous)
            return
        self.lesson = lesson
        self._loading = True
        self.lesson_title.setText(lesson.title)
        self._loading = False
        self.lesson_title.setEnabled(True)
        self.lesson_kind.setText("Локальное занятие")
        self.new_note_button.setEnabled(True)
        self.save_status.setText("Все изменения сохранены на компьютере")
        self._fill_notes(notes)
        bridge = getattr(self, "cloud_bridge", None)
        if bridge:
            bridge.update_controls()

    def _select_note(self, current: QListWidgetItem | None, previous=None) -> None:
        if current is None:
            return
        if not self.flush_changes():
            with QSignalBlocker(self.note_list):
                self.note_list.setCurrentItem(previous)
            return
        self.note = current.data(Qt.ItemDataRole.UserRole)
        self.author_meta.setText("Локальная заметка")
        self._loading = True
        self.note_title.setText(self.note.title)
        self.note_body.setPlainText(self.note.content)
        self._loading = False
        self._update_meta()
        bridge = getattr(self, "cloud_bridge", None)
        if bridge:
            bridge.update_controls()

    def _update_meta(self) -> None:
        if self.note:
            date = (
                datetime.fromisoformat(self.note.updated_at).astimezone().strftime("%d.%m · %H:%M")
            )
            self.note_meta.setText(f"Изменено {date}")

    def _lesson_changed(self) -> None:
        if not self._loading and self.lesson:
            self._lesson_dirty = True
            self._schedule_save()

    def _note_changed(self) -> None:
        if not self._loading and self.note:
            self._note_dirty = True
            self._schedule_save()

    def _schedule_save(self) -> None:
        self.setWindowModified(True)
        self.save_status.setText("Сохраняем изменения…")
        self.save_timer.start(self.AUTOSAVE_MS)
        if not self.max_save_timer.isActive():
            self.max_save_timer.start(self.MAX_SAVE_DELAY_MS)

    def _show_error(self, error: EnglishNotesError) -> None:
        self.error_label.setText(str(error))
        self.error_label.show()
        dirty = self._lesson_dirty or self._note_dirty
        self.retry_button.setVisible(dirty)
        self.save_status.setText("Не сохранено — текст остаётся в редакторе" if dirty else "Ошибка")

    def flush_changes(self) -> bool:
        self.save_timer.stop()
        self.max_save_timer.stop()
        try:
            if self._lesson_dirty and self.lesson:
                self.lesson = self.service.rename_lesson(self.lesson, self.lesson_title.text())
                self._lesson_dirty = False
                for row in range(self.lesson_list.count()):
                    item = self.lesson_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole).id == self.lesson.id:
                        item.setData(Qt.ItemDataRole.UserRole, self.lesson)
                        item.setText(self._lesson_caption(self.lesson))
            if self._note_dirty and self.note:
                self.note = self.service.save_note(
                    self.note, self.note_title.text(), self.note_body.toPlainText()
                )
                self._note_dirty = False
                for row in range(self.note_list.count()):
                    item = self.note_list.item(row)
                    if item.data(Qt.ItemDataRole.UserRole).id == self.note.id:
                        item.setData(Qt.ItemDataRole.UserRole, self.note)
                        item.setText(self.note.title or "Без названия")
                self._update_meta()
        except EnglishNotesError as error:
            self._show_error(error)
            return False
        self.setWindowModified(False)
        self.error_label.hide()
        self.retry_button.hide()
        if self.lesson:
            self.save_status.setText("Все изменения сохранены на компьютере")
        return True

    def create_lesson(self) -> None:
        if not self.flush_changes():
            return
        try:
            lesson = self.service.create_lesson()
            self._reload_lessons(lesson.id)
        except EnglishNotesError as error:
            self._show_error(error)
            return
        self.lesson_title.setFocus()
        self.lesson_title.selectAll()

    def create_note(self) -> None:
        if not self.lesson or not self.flush_changes():
            return
        try:
            note = self.service.create_note(self.lesson.id)
            notes = self.service.list_notes(self.lesson.id)
        except EnglishNotesError as error:
            self._show_error(error)
            return
        self._fill_notes(notes, note.id)
        self.note_title.setFocus()
        self.note_title.selectAll()

    def delete_note(self) -> None:
        if not self.note or not self.flush_changes():
            return
        answer = QMessageBox.question(
            self,
            "Удалить заметку?",
            "Заметка исчезнет из занятия. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.delete_note(self.note)
            notes = self.service.list_notes(self.note.lesson_id)
        except EnglishNotesError as error:
            self._show_error(error)
            return
        self._fill_notes(notes)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.flush_changes():
            bridge = getattr(self, "cloud_bridge", None)
            if bridge is None or bridge.request_close():
                event.accept()
            else:
                event.ignore()
        else:
            event.ignore()
