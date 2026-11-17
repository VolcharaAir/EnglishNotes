import json
from contextlib import contextmanager
from uuid import uuid4

from englishnotes.storage.repository import timestamp


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class CloudStore:
    def __init__(self, database):
        self.db = database

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.connection.execute(sql, args)]

    @contextmanager
    def incoming(self):
        with self.db.transaction() as connection:
            connection.execute("UPDATE cloud_runtime SET remote=1 WHERE id=1")
            try:
                yield connection
            finally:
                connection.execute("UPDATE cloud_runtime SET remote=0 WHERE id=1")

    def enroll(self, lesson_id):
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO cloud_lessons(local_id) VALUES(?)", (lesson_id,)
            )
            connection.execute(
                "INSERT OR IGNORE INTO cloud_commands VALUES(?,'share',?,NULL,NULL)",
                (str(uuid4()), lesson_id),
            )
            for note in connection.execute(
                "SELECT * FROM notes WHERE lesson_id=?", (lesson_id,)
            ).fetchall():
                connection.execute(
                    "INSERT OR IGNORE INTO cloud_notes(note_id,position) VALUES(?,?)",
                    (
                        note["id"],
                        connection.execute("SELECT count(*) FROM cloud_notes").fetchone()[0],
                    ),
                )
                self._queue(connection, note)

    @staticmethod
    def _queue(connection, note):
        meta = connection.execute(
            "SELECT * FROM cloud_notes WHERE note_id=?", (note["id"],)
        ).fetchone()
        payload = encode(
            {
                "title": note["title"],
                "content": note["content"],
                "deleted": note["deleted_at"] is not None,
                "position": meta["position"],
            }
        )
        connection.execute(
            "INSERT OR REPLACE INTO cloud_outbox VALUES(?,?,?,?,?,NULL)",
            (note["id"], str(uuid4()), note["revision"], meta["server_revision"], payload),
        )

    def scope(self, lesson_id):
        rows = self.rows("SELECT * FROM cloud_lessons WHERE local_id=?", (lesson_id,))
        return rows[0] if rows else None

    def command(self, kind, lesson_id=None, vault_key=None):
        with self.db.transaction() as connection:
            if (
                kind == "join"
                and connection.execute("SELECT 1 FROM cloud_commands WHERE kind='join'").fetchone()
            ):
                raise ValueError("Подключение уже ожидает обработки.")
            connection.execute(
                "INSERT OR IGNORE INTO cloud_commands VALUES(?,?,?,NULL,?)",
                (str(uuid4()), kind, lesson_id, vault_key),
            )

    def bind(self, command, uid, session):
        with self.db.transaction() as connection:
            if command["kind"] == "share":
                connection.execute(
                    "UPDATE cloud_lessons SET "
                    "remote_id=?,account_id=?,owner_id=?,status=? WHERE local_id=?",
                    (
                        session["id"],
                        uid,
                        session["created_by"],
                        session["status"],
                        command["local_id"],
                    ),
                )
                connection.execute(
                    "UPDATE cloud_notes SET author_id=? WHERE author_id IS NULL AND note_id IN "
                    "(SELECT id FROM notes WHERE lesson_id=?)",
                    (uid, command["local_id"]),
                )
            connection.execute(
                "INSERT OR REPLACE INTO cloud_inbox VALUES('session',?,?,?)",
                (session["id"], uid, encode(session)),
            )
            connection.execute("DELETE FROM cloud_commands WHERE id=?", (command["id"],))
            connection.execute(
                "INSERT INTO cloud_cursors VALUES(?,0) ON CONFLICT(account_id) DO "
                "UPDATE SET cursor=0",
                (uid,),
            )

    def stage(self, uid, value):
        with self.db.transaction() as connection:
            for kind, values in (("session", value["sessions"]), ("note", value["notes"])):
                for item in values:
                    connection.execute(
                        "INSERT OR REPLACE INTO cloud_inbox VALUES(?,?,?,?)",
                        (kind, item["id"], uid, encode(item)),
                    )
            connection.execute(
                "INSERT OR REPLACE INTO cloud_cursors VALUES(?,?)", (uid, value["cursor"])
            )

    def prepare_outbox(self, uid):
        # Freeze the request before HTTP. Edits may replace the outbox while a
        # response is lost; retrying must still use exactly the original operation.
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO cloud_inflight "
                "SELECT q.note_id,q.operation_id,q.local_revision,q.base_revision,"
                "q.payload,l.remote_id "
                "FROM cloud_outbox q JOIN notes n ON n.id=q.note_id "
                "JOIN cloud_lessons l ON l.local_id=n.lesson_id "
                "WHERE l.account_id=? AND l.remote_id IS NOT NULL AND l.status='active' "
                "AND q.error IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM cloud_conflicts c WHERE c.note_id=q.note_id) LIMIT 8",
                (uid,),
            )
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT f.* FROM cloud_inflight f JOIN notes n ON n.id=f.note_id "
                    "JOIN cloud_lessons l ON l.local_id=n.lesson_id WHERE l.account_id=? "
                    "AND l.status='active' AND NOT EXISTS "
                    "(SELECT 1 FROM cloud_conflicts c WHERE c.note_id=f.note_id) LIMIT 8",
                    (uid,),
                )
            ]

    def ack(self, queued, note):
        with self.db.transaction() as connection:
            connection.execute(
                "DELETE FROM cloud_inflight WHERE operation_id=?", (queued["operation_id"],)
            )
            connection.execute(
                "UPDATE cloud_notes SET server_revision=?,author_id=?,position=?,base_json=? "
                "WHERE note_id=? AND server_revision<=?",
                (
                    note["revision"],
                    note["author_id"],
                    note["position"],
                    encode(note),
                    queued["note_id"],
                    note["revision"],
                ),
            )
            connection.execute(
                "DELETE FROM cloud_outbox WHERE operation_id=?", (queued["operation_id"],)
            )
            # An edit made during the HTTP call descends from the acknowledged local version.
            connection.execute(
                "UPDATE cloud_outbox SET base_revision=MAX(base_revision,?) WHERE note_id=?",
                (note["revision"], queued["note_id"]),
            )

    def conflict(self, queued, remote):
        with self.db.transaction() as connection:
            connection.execute(
                "DELETE FROM cloud_inflight WHERE operation_id=?", (queued["operation_id"],)
            )
            pending = connection.execute(
                "SELECT * FROM cloud_outbox WHERE note_id=?", (queued["note_id"],)
            ).fetchone()
            if not pending or (
                pending["operation_id"] != queued["operation_id"]
                and pending["base_revision"] >= remote["revision"]
            ):
                return
            meta = connection.execute(
                "SELECT * FROM cloud_notes WHERE note_id=?", (queued["note_id"],)
            ).fetchone()
            current = connection.execute(
                "SELECT * FROM notes WHERE id=?", (queued["note_id"],)
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO cloud_conflicts VALUES(?,?,?,?,?)",
                (
                    queued["note_id"],
                    meta["base_json"],
                    encode(dict(current)),
                    encode(remote),
                    remote["revision"],
                ),
            )
            connection.execute(
                "UPDATE cloud_outbox SET error='conflict' WHERE note_id=?", (queued["note_id"],)
            )

    def apply_inbox(self, uid):
        """Only GUI thread calls this, after successfully flushing its editor buffer."""
        with self.incoming() as connection:
            items = connection.execute(
                "SELECT * FROM cloud_inbox WHERE account_id=? ORDER BY kind DESC", (uid,)
            ).fetchall()
            for item in items:
                value = json.loads(item["payload"])
                if item["kind"] == "session":
                    link = connection.execute(
                        "SELECT * FROM cloud_lessons WHERE remote_id=?", (value["id"],)
                    ).fetchone()
                    local_id = link["local_id"] if link else value["id"]
                    # Never attach a colliding private/local lesson to an incoming session.
                    if (
                        not link
                        and connection.execute(
                            "SELECT 1 FROM lessons WHERE id=?", (local_id,)
                        ).fetchone()
                    ):
                        local_id = str(uuid4())
                    connection.execute(
                        "INSERT OR IGNORE INTO lessons VALUES(?,?,?,?,1,NULL)",
                        (local_id, value["title"], value["created_at"], value["created_at"]),
                    )
                    connection.execute(
                        "INSERT INTO cloud_lessons VALUES(?,?,?,?,?) "
                        "ON CONFLICT(local_id) DO UPDATE "
                        "SET owner_id=excluded.owner_id,status=excluded.status",
                        (local_id, value["id"], uid, value["created_by"], value["status"]),
                    )
                else:
                    link = connection.execute(
                        "SELECT * FROM cloud_lessons WHERE remote_id=? AND account_id=?",
                        (value["lesson_id"], uid),
                    ).fetchone()
                    if not link:
                        continue
                    meta = connection.execute(
                        "SELECT * FROM cloud_notes WHERE note_id=?", (value["id"],)
                    ).fetchone()
                    pending = connection.execute(
                        "SELECT * FROM cloud_outbox WHERE note_id=?", (value["id"],)
                    ).fetchone()
                    if meta and value["revision"] <= meta["server_revision"]:
                        connection.execute(
                            "DELETE FROM cloud_inbox WHERE kind=? AND remote_id=? AND account_id=?",
                            (item["kind"], item["remote_id"], uid),
                        )
                        continue
                    if pending:
                        current = connection.execute(
                            "SELECT * FROM notes WHERE id=?", (value["id"],)
                        ).fetchone()
                        connection.execute(
                            "INSERT OR REPLACE INTO cloud_conflicts VALUES(?,?,?,?,?)",
                            (
                                value["id"],
                                meta["base_json"],
                                encode(dict(current)),
                                encode(value),
                                value["revision"],
                            ),
                        )
                        connection.execute(
                            "UPDATE cloud_outbox SET error='conflict' WHERE note_id=?",
                            (value["id"],),
                        )
                    else:
                        existing = connection.execute(
                            "SELECT * FROM notes WHERE id=?", (value["id"],)
                        ).fetchone()
                        if existing and existing["lesson_id"] != link["local_id"]:
                            raise ValueError("Коллизия локального UUID: данные не заменены.")
                        connection.execute(
                            "INSERT INTO notes VALUES(?,?,?,?,?,?,1,?) "
                            "ON CONFLICT(id) DO UPDATE SET "
                            "title=excluded.title,content=excluded.content,updated_at=excluded.updated_at,"
                            "revision=notes.revision+1,deleted_at=excluded.deleted_at",
                            (
                                value["id"],
                                link["local_id"],
                                value["title"],
                                value["content"],
                                value["created_at"],
                                value["updated_at"],
                                value["deleted_at"],
                            ),
                        )
                        connection.execute(
                            "INSERT OR REPLACE INTO cloud_notes VALUES(?,?,?,?,?)",
                            (
                                value["id"],
                                value["revision"],
                                value["author_id"],
                                value["position"],
                                encode(value),
                            ),
                        )
                connection.execute(
                    "DELETE FROM cloud_inbox WHERE kind=? AND remote_id=? AND account_id=?",
                    (item["kind"], item["remote_id"], uid),
                )

    def resolve(self, note_id, keep_local, expected_revision=None):
        with self.incoming() as connection:
            conflict = connection.execute(
                "SELECT * FROM cloud_conflicts WHERE note_id=?", (note_id,)
            ).fetchone()
            if not conflict:
                return
            if expected_revision is not None and conflict["server_revision"] != expected_revision:
                raise ValueError("Conflict changed while the dialog was open")
            archived = dict(conflict)
            archived["local_json"] = encode(
                dict(connection.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())
            )
            connection.execute(
                "INSERT INTO cloud_conflict_archive VALUES(?,?,?,?)",
                (str(uuid4()), note_id, encode(archived), timestamp()),
            )
            remote = json.loads(conflict["remote_json"])
            connection.execute(
                "UPDATE cloud_notes SET server_revision=?,base_json=?,author_id=? WHERE note_id=?",
                (remote["revision"], encode(remote), remote["author_id"], note_id),
            )
            connection.execute("DELETE FROM cloud_outbox WHERE note_id=?", (note_id,))
            if keep_local:
                current = connection.execute(
                    "SELECT * FROM notes WHERE id=?", (note_id,)
                ).fetchone()
                self._queue(connection, current)
            else:
                connection.execute(
                    "UPDATE notes SET title=?,content=?,deleted_at=?,updated_at=?,"
                    "revision=revision+1 WHERE id=?",
                    (
                        remote["title"],
                        remote["content"],
                        remote["deleted_at"],
                        timestamp(),
                        note_id,
                    ),
                )
            connection.execute("DELETE FROM cloud_conflicts WHERE note_id=?", (note_id,))
