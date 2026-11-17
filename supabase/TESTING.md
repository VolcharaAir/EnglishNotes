> Исторический протокол v1. После миграции Desktop v2 используйте
> [новую инструкцию](../docs/cloud-testing.md) и `tests/live_desktop.py`.

# Фактически выполненная проверка

17 ноября 2026 года, изолированный Docker-контейнер без опубликованных портов.
PostgreSQL **16.16**, официальный образ `postgres:16`. В реальный Supabase-проект
подключения и применения миграции не было; `.env` не использовался.

```text
python supabase/tests/check_sql.py --docker-host=unix:///var/run/docker.sock

SQL migration and RLS/ACL/RPC security assertions passed.
5 concurrent last-seat races passed: exactly one join succeeds each time.
Concurrent budget check passed: 5 attempts, 7 refusals, 12 persisted calls.
```

Проверены создание схемы и PL/pgSQL-функций, RLS и column-level grants,
создание членства, запрет доступа anon/постороннего пользователя, отсутствие
доступа к хешу и лимитеру, подмена автора/ID/ревизии, ограничения позиции,
неизменность состава участников, совместное редактирование чужой заметки,
серверные revision/timestamps, tombstones, срок действия/одноразовость кода,
ограничения create/join, закрытые занятия, публикация Realtime.
Участник также создавал одноимённую временную таблицу и менял search_path:
SECURITY DEFINER helper-ы продолжили использовать правильные таблицы.

Пять отдельных гонок использовали два параллельных PostgreSQL-соединения
и задержку перед COMMIT: на каждое занятие ровно один успешный join,
ровно два участника. Двенадцать одновременных вызовов одним UUID подтвердили,
что лимитер сериализует счётчик и не теряет неудачные запросы между транзакциями.

`verify.sql` выполнен после применения на отдельной локальной тестовой базе:
RLS включена на всех четырёх таблицах, пять политик, пять definer-функций
с пустым search_path, ожидаемые ACL, lesson_notes включена в публикацию.

Регрессия локального приложения:

```text
python -m pytest -q
64 passed in 3.55s

ruff check src tests tools packaging supabase/tests/check_sql.py
All checks passed!

ruff format --check src tests tools packaging supabase/tests/check_sql.py
29 files already formatted
```

**Граница проверки:** `auth.users` и `auth.uid()` в контейнере — минимальные
тестовые заглушки Supabase. Привилегии и RLS проверялись реальными PostgreSQL
ролями anon/authenticated, но реальный выпуск/проверка JWT, PostgREST и доставка
событий Realtime в Supabase здесь не выполнялись. Для них в README приведён
чек-лист с тремя независимыми Auth-контекстами. Успешный SQL-тест не является
подтверждением, что ваш облачный проект уже настроен или мигрирован.
