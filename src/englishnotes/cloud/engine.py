import json
import time

from englishnotes.cloud.transport import CloudError


class SyncEngine:
    """Single network worker. Never mutates existing note text: stages a GUI inbox."""

    def __init__(self, store, sessions, transport, vault):
        self.store = store
        self.sessions = sessions
        self.transport = transport
        self.vault = vault
        self.last_read = 0
        self.force_read = True
        self.uid = None
        self.warning = None
        self.cancelled = lambda: False

    def call(self, name, payload):
        if self.cancelled():
            raise CloudError("stopped")
        identity = self.sessions.ensure()
        try:
            value = self.transport.rpc(name, payload, identity.access_token)
        except CloudError as error:
            if error.code == "unauthorized":
                self.sessions.invalidate_access()
            raise
        if value.get("outcome") not in ("ok", "conflict"):
            raise CloudError(value.get("outcome", "protocol_error"))
        return value

    def cycle(self, changed=False):
        if self.cancelled():
            return False
        identity = self.sessions.ensure()
        self.uid = identity.uid
        commands = self.store.rows("SELECT * FROM cloud_commands ORDER BY rowid")
        for command in commands:
            if command["account_id"] and command["account_id"] != identity.uid:
                continue
            with self.store.db.transaction() as connection:
                connection.execute(
                    "UPDATE cloud_commands SET account_id=? WHERE id=?",
                    (identity.uid, command["id"]),
                )
            if command["kind"] == "share":
                lesson = self.store.rows(
                    "SELECT * FROM lessons WHERE id=?", (command["local_id"],)
                )[0]
                result = self.call(
                    "en_create_session",
                    {"p_local_id": lesson["id"], "p_title": lesson["title"] or "Занятие"},
                )
                code = result.get("invitation_code")
                if code:
                    self.vault.put(
                        "invite:" + result["session"]["id"],
                        {"code": code, "expires_at": result["session"]["invitation_expires_at"]},
                    )
                self.store.bind(command, identity.uid, result["session"])
                self.force_read = True
                changed = True
            elif command["kind"] == "join":
                secret = self.vault.get(command["vault_key"])
                if not secret:
                    raise CloudError("invitation_missing")
                try:
                    result = self.call(
                        "en_join_session",
                        {"p_code": secret["code"], "p_operation_id": command["id"]},
                    )
                except CloudError as error:
                    if error.code == "invalid_invitation":
                        with self.store.db.transaction() as connection:
                            connection.execute(
                                "DELETE FROM cloud_commands WHERE id=?", (command["id"],)
                            )
                        self.vault.remove(command["vault_key"])
                        self.warning = error.code
                        changed = True
                        continue
                    raise
                self.store.bind(command, identity.uid, result["session"])
                self.vault.remove(command["vault_key"])
                self.force_read = True
                changed = True

        outbox = self.store.prepare_outbox(identity.uid)
        for queued in outbox:
            payload = json.loads(queued["payload"])
            try:
                result = self.call(
                    "en_write_note",
                    {
                        "p_operation_id": queued["operation_id"],
                        "p_note_id": queued["note_id"],
                        "p_lesson_id": queued["remote_id"],
                        "p_base_revision": queued["base_revision"],
                        "p_title": payload["title"],
                        "p_content": payload["content"],
                        "p_position": payload["position"],
                        "p_deleted": payload["deleted"],
                    },
                )
            except CloudError as error:
                if error.code in ("note_too_large_or_invalid", "session_closed", "note_limit"):
                    with self.store.db.transaction() as connection:
                        connection.execute(
                            "DELETE FROM cloud_inflight WHERE operation_id=?",
                            (queued["operation_id"],),
                        )
                        connection.execute(
                            "UPDATE cloud_outbox SET error=? WHERE operation_id=?",
                            (error.code, queued["operation_id"]),
                        )
                    self.warning = error.code
                    self.force_read = True
                    changed = True
                    continue
                raise
            remote = result.get("note")
            if (
                not remote
                or remote["id"] != queued["note_id"]
                or remote["lesson_id"] != queued["remote_id"]
            ):
                raise CloudError("protocol_error")
            if result["outcome"] == "conflict":
                self.store.conflict(queued, remote)
            else:
                self.store.ack(queued, remote)
            changed = True
            self.force_read = True

        for command in commands:
            if command["kind"] != "finish" or (
                command["account_id"] and command["account_id"] != identity.uid
            ):
                continue
            pending = self.store.rows(
                "SELECT 1 FROM cloud_outbox q JOIN notes n ON n.id=q.note_id WHERE n.lesson_id=?",
                (command["local_id"],),
            )
            link = self.store.scope(command["local_id"])
            if pending or not link or not link["remote_id"]:
                continue
            self.call("en_finish_session", {"p_lesson_id": link["remote_id"]})
            with self.store.db.transaction() as connection:
                connection.execute("DELETE FROM cloud_commands WHERE id=?", (command["id"],))
            self.force_read = True

        if self.force_read or changed or time.monotonic() - self.last_read >= 20:
            cursor = self.store.rows(
                "SELECT cursor FROM cloud_cursors WHERE account_id=?", (identity.uid,)
            )
            result = self.call(
                "en_read", {"p_after": cursor[0]["cursor"] if cursor else 0, "p_limit": 64}
            )
            self.store.stage(identity.uid, result)
            self.force_read = bool(result["has_more"])
            self.last_read = time.monotonic()
            changed = True
        return changed
