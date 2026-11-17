# EnglishNotes

Desktop-приложение для заметок к занятиям английским: Python 3.14+, PySide6,
SQLite и Supabase. В версии 0.3.0 добавлен адаптер совместных занятий с локальной
очередью изменений. Прежние локальные занятия не публикуются автоматически.

## Пользователю

Настроенная Windows-сборка запускается двойным щелчком по `EnglishNotes.exe`.
Python, Git, регистрация и настройка Supabase не нужны. Локальные записи работают
без интернета. Для совместного занятия требуется интернет и доступный сервер.

- «+ Новое занятие» — локальная запись на вашем компьютере.
- «Создать занятие» — общее занятие; «Пригласить участника» показывает код.
- «Подключиться к занятию» — вставьте полученный код (до двух участников).
- Заметки автоматически сохраняются локально и отправляются при доступной сети.
- Одновременные правки требуют выбора версии кнопкой «Разрешить конфликт».
- Создатель может завершить занятие: оно останется доступным для чтения.

Доступна [предварительная Windows-сборка 0.3.0 — EnglishNotes.exe](https://github.com/VolcharaAir/EnglishNotes/releases/download/test-0.3.0/EnglishNotes.exe).
Пользователь подтвердил обмен на двух Windows-компьютерах, сохранение offline-правки
после перезапуска и её передачу после восстановления сети.
[Отчёт проверки](docs/windows-test-0.3.0.md). Готовая macOS-сборка пока отсутствует.

Владелец сервера настраивает Supabase один раз по
[инструкции](docs/cloud-desktop.md); пользователям готового EXE такая настройка не нужна.

## Хранение и обновление

| ОС | Данные |
|---|---|
| Windows | `%LOCALAPPDATA%\EnglishNotes` |
| macOS | `~/Library/Application Support/EnglishNotes` |
| Linux | `$XDG_DATA_HOME/EnglishNotes` или `~/.local/share/EnglishNotes` |

База `englishnotes.sqlite3` не зависит от расположения EXE. Обновление/перемещение
EXE не сбрасывает записи. Каталоги создаются автоматически. Без диска D приложение
работает. Прежняя база `D:\EnglishNotesData\englishnotes.sqlite3` безопасно копируется
только при отсутствии новой; исходник сохраняется. Подробности:
[docs/move-to-d.md](docs/move-to-d.md).

Перед резервным копированием закройте приложение и скопируйте всю папку данных.
SQLite не зашифрована. Refresh token сохраняется отдельно в системном хранилище
учётных данных; копирование SQLite не переносит анонимную облачную личность.
Не включайте базы, .env, токены или административные ключи в архивы исходников.

Автосохранение: 350 мс после ввода, максимум 2 секунды при непрерывной печати;
перед переключением/закрытием — синхронное сохранение. При ошибке буфер остаётся
в редакторе. Принудительное завершение процесса может потерять ещё не записанные
символы. Сетевые ошибки не отменяют уже записанные локальные данные.

## Разработка и тесты

```powershell
uv sync --locked --extra dev --extra build
uv run --no-sync pytest -q
uv run --no-sync ruff check src tests tools packaging
uv run --env-file .env --no-sync python -m englishnotes
```

Без uv: Python 3.14, `python -m venv .venv`, затем
`.\.venv\Scripts\python.exe -m pip install -e ".[dev,build]"`.
Для локального запуска `.\.venv\Scripts\python.exe -m englishnotes`.
Для облачного запуска исходников задайте публичные настройки окружения;
настроенный EXE получает их из bundle. `start.cmd` запускает исходники без консоли.

## Windows EXE

На Windows:

```powershell
uv run --env-file .env --no-sync python tools/prepare_cloud_config.py
uv run --no-sync python -m PyInstaller --clean --noconfirm EnglishNotes.spec
```

Результат — `dist\EnglishNotes.exe`, onefile GUI со встроенными Python, Qt,
SQLite, системным keyring backend и WebSocket-клиентом. Для локальной сборки
подготовьте конфигурацию с `--local` вместо чтения .env. Runtime PyInstaller
распаковывается в системный TEMP; пользовательская база остаётся в профиле.
Целевая платформа — Windows 10/11 x64. Linux-сборка не является Windows EXE.

`.github/workflows/windows.yml`: отдельные SQL security проверки, затем
Windows runner, locked-зависимости, lint,
pytest, подготовка публичных настроек из GitHub Variables, PyInstaller, Windows
smoke и Artifact. Релизный job выполняется только после успешной сборки по тегу
`v*`. Не создавайте тег до решения о публикации. Сборка пока без подписи Windows;
программа не отключает SmartScreen.

## Модули

```text
src/englishnotes/
  app.py                 # Запуск, блокировки, сборка зависимостей
  domain/                # Неизменяемые локальные модели
  application/           # Локальные сценарии и порт репозитория
  storage/               # SQLite v1 + добавочная v2, outbox/inbox/conflicts
  auth/                  # Анонимная сессия, системный vault
  cloud/                 # Конфигурация, HTTPS RPC, engine, worker, private Realtime
  ui/                    # Главное окно и адаптер облачного интерфейса
  resources/cloud.json   # Пустой шаблон публичных настроек
supabase/migrations/     # v1 + ручная v2 серверная миграция
supabase/tests/          # PostgreSQL и opt-in live проверки
supabase/verify_desktop.sql
EnglishNotes.spec
.github/workflows/windows.yml
tools/prepare_cloud_config.py
```

[Архитектура](docs/architecture.md),
[настройка сервера и лимитов](docs/cloud-desktop.md),
[результаты и ручная проверка](docs/cloud-testing.md).
