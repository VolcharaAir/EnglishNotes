# Отчёт 0.3.0 — 17 ноября 2026

Исходники находятся в ветке `desktop-supabase-0.3.0`. Владелец вручную применил
миграцию Supabase, настроил hook/Realtime, собрал Windows EXE и опубликовал
предварительный релиз `test-0.3.0`. Он подтвердил 19 живых проверок и обмен
между двумя Windows EXE, включая физическое отключение сети и перезапуск.

Доказательства и границы проверки: [Windows test report](windows-test-0.3.0.md).
Локальные пользовательские Windows-базы агент не открывал; облачная разработка
использовала отдельные тестовые профили.

## Реализовано

Анонимная авторизация с refresh в системном vault, общий сеанс на двух произвольных
пользователей, одноразовое приглашение с TTL, создание/подключение/завершение,
private Realtime invalidation + ограниченный RPC fetch, offline outbox/inbox,
идемпотентные повторы, CAS/conflicts с сохранением версий, UI состояний и очереди.

Серверная миграция v2 вводит обязательные квоты и Auth Hook, закрывает прямые API
обходы лимитов. Данные v1 сохраняются. Настройки публичного облака включаются при
сборке; service_role/secret/JWT не включаются. Автоматической оплаты/upgrade нет.

SQLite v2 только добавляет служебную схему и триггеры. Старые lessons/notes при
миграции сохраняют значения/идентификаторы/ревизии. Частные занятия не отправляются
до явного действия пользователя. Серверная миграция применяется вручную владельцем.

## Основные новые файлы

- `src/englishnotes/auth/{session,vault}.py`
- `src/englishnotes/cloud/{config,transport,engine,worker,realtime}.py`
- `src/englishnotes/storage/{cloud_schema,cloud_store}.py`
- `src/englishnotes/ui/cloud_bridge.py`
- `src/englishnotes/resources/cloud.json` и маркеры пакетов `__init__.py`
- `supabase/migrations/20261117000200_desktop_sync.sql`
- `supabase/verify_desktop.sql`
- `supabase/tests/{desktop_bootstrap,desktop_security,desktop_payloads}.sql`
- `supabase/tests/live_desktop.py`, `run_live_desktop.cmd`
- `tests/test_cloud.py`, `test_cloud_ui.py`, `test_build_config.py`
- `tools/prepare_cloud_config.py`
- `docs/cloud-desktop.md`, `cloud-testing.md`, этот отчёт

## Основные изменённые файлы

- `src/englishnotes/app.py`, `__init__.py` — подключение адаптера/версия.
- `storage/database.py`, `migration.py`, `paths.py` — добавочная схема,
  совместимость старой миграции и изолированные тестовые профили.
- `ui/main_window.py` — корректное завершение worker, сохранены локальные функции.
- `sync/__init__.py` — ссылка на реализованный адаптер.
- `pyproject.toml`, `uv.lock` — keyring/WebSocket, версия 0.3.0.
- `EnglishNotes.spec`, `tools/smoke_windows.py` — ресурсы/backend в bundle,
  изолированный offline smoke без регистрации на сервере.
- `.github/workflows/windows.yml` — SQL security job, публичные build variables.
- `supabase/tests/check_sql.py` — применение и конкурентные проверки v2.
- `README.md`, `docs/architecture.md`, прежние отчёты/инструкции Supabase —
  актуальные ссылки и разграничение исторического протокола v1 и нового v2.

Первоначальная серверная миграция `20261117000100_lesson_sessions.sql` не изменялась.

## Фактические результаты

| Проверка | Результат |
|---|---|
| pytest, Python 3.14.10 / Linux | **152 passed** (142 базовых + 10 Realtime) |
| Ruff lint и format | PASS |
| Миграции v1/v2 в PostgreSQL 16.16 | PASS |
| Большие v1 данные / JSON escaping | 6 заметок, 3 ограниченные страницы |
| SQL ACL/RLS, RPC, ограничения и Auth-hook fixtures | PASS |
| Пять конкурентных гонок за второе место | PASS |
| 12 параллельных попыток подбора | 5 обработаны, 7 ограничены, учтены все |
| Две записи одной серверной версии | Один commit, один conflict |
| PyInstaller Linux local bundle | Собран, ресурсы/backend/WebSocket включены |
| Linux frozen startup + перемещение бинарного файла | PASS; SQLite и заметка сохранились |
| Windows EXE / сохранение Auth через vault | Пользователь собрал и проверил на Windows |
| Живые Auth/JWT/Realtime Desktop v2 | Пользователь предоставил PASS: 19 проверок |
| Два Windows EXE / offline / reopen / reconnect | Пользователь подтвердил обмен и очередь 0 |

Linux frozen smoke использовал Qt offscreen и принудительное завершение пустого
редактора; он не заменяет обычное закрытие Windows EXE и ручную проверку двух ПК.
В Linux системный vault проверен через backend fixture; владелец отдельно выполнил
реальные Auth/refresh и EXE-проверки с Windows vault.
SQL fixture проверяет PostgreSQL, а не настоящие JWT/GoTrue/Realtime-сервис.

После исправления join_ref живой runner завершился PASS у пользователя.
Переданные результаты не считаются запуском Supabase из облачной среды.

## Опубликованная предварительная сборка

[Скачать EnglishNotes.exe](https://github.com/VolcharaAir/EnglishNotes/releases/download/test-0.3.0/EnglishNotes.exe).
Релиз предназначен для Windows 10/11 x64. Версия macOS остаётся отдельной задачей.
Работа GitHub Actions и автоматическая релизная сборка этим ручным выпуском
не подтверждены. Исходники и инструкция сохраняют возможность воспроизведения.

Точные шаги Dashboard/сборки: [cloud-desktop.md](cloud-desktop.md).
Команды тестов и ручные сценарии: [cloud-testing.md](cloud-testing.md).

SQL-квоты — защита ресурсоёмких операций приложения с запасом, не точная стоимость
Supabase и не гарантия от DDoS. Usage, Free-план и ограничения шлюза/Auth/Realtime
контролируются отдельно владельцем. Приложение платный тариф не включает.
