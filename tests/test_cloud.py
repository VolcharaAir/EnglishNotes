"""Deterministic client integration; the fake transport is not a live Supabase test."""

import copy
import json
from uuid import uuid4

import pytest

from englishnotes.auth.session import Identity, SessionManager
from englishnotes.cloud.engine import SyncEngine
from englishnotes.cloud.transport import CloudError
from englishnotes.storage.cloud_store import CloudStore
from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository


class MemoryVault:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return copy.deepcopy(self.values.get(key))

    def put(self, key, value):
        self.values[key] = copy.deepcopy(value)

    def remove(self, key):
        self.values.pop(key, None)


class IdentityFixture:
    def __init__(self):
        self.uid = str(uuid4())

    def ensure(self):
        return Identity(self.uid, self.uid, 9999999999)


class ServerFixture:
    def __init__(self):
        self.sessions = {}
        self.members = {}
        self.notes = {}
        self.receipts = {}
        self.codes = {}
        self.online = True
        self.lose_response = False
        self.sequence = 0

    def rpc(self, name, p, token):
        if not self.online:
            raise CloudError("offline")
        if name == "en_create_session":
            sid = p["p_local_id"]
            s = self.sessions.setdefault(
                sid,
                dict(
                    id=sid,
                    title=p["p_title"],
                    created_by=token,
                    created_at="2026-11-17T00:00:00+00:00",
                    invitation_expires_at="2099-01-01T00:00:00+00:00",
                    status="active",
                ),
            )
            self.members.setdefault(sid, {token})
            code = str(uuid4())
            self.codes[code] = sid
            return dict(outcome="ok", session=copy.deepcopy(s), invitation_code=code)
        if name == "en_join_session":
            sid = self.codes.pop(p["p_code"], None)
            if not sid or len(self.members[sid]) >= 2:
                return dict(outcome="invalid_invitation")
            self.members[sid].add(token)
            return dict(outcome="ok", session=copy.deepcopy(self.sessions[sid]))
        if name == "en_read":
            allowed = {sid for sid, users in self.members.items() if token in users}
            rows = [
                copy.deepcopy(n)
                for n in self.notes.values()
                if n["lesson_id"] in allowed and n["sync_seq"] > p["p_after"]
            ]
            rows.sort(key=lambda n: n["sync_seq"])
            rows = rows[: p["p_limit"]]
            return dict(
                outcome="ok",
                sessions=[copy.deepcopy(s) for sid, s in self.sessions.items() if sid in allowed],
                notes=rows,
                cursor=max([n["sync_seq"] for n in rows], default=p["p_after"]),
                has_more=False,
            )
        if name == "en_finish_session":
            sid = p["p_lesson_id"]
            if self.sessions[sid]["created_by"] != token:
                return dict(outcome="forbidden")
            self.sessions[sid]["status"] = "closed"
            return dict(outcome="ok")
        assert name == "en_write_note"
        sid, nid = p["p_lesson_id"], p["p_note_id"]
        if token not in self.members.get(sid, set()):
            return dict(outcome="forbidden")
        key = (token, p["p_operation_id"])
        if key in self.receipts:
            return copy.deepcopy(self.receipts[key])
        if self.sessions[sid]["status"] != "active":
            return dict(outcome="session_closed")
        old = self.notes.get(nid)
        if (old["revision"] if old else 0) != p["p_base_revision"]:
            return dict(outcome="conflict", note=copy.deepcopy(old))
        self.sequence += 1
        note = dict(
            id=nid,
            lesson_id=sid,
            title=p["p_title"],
            content=p["p_content"],
            author_id=old["author_id"] if old else token,
            position=p["p_position"],
            revision=(old["revision"] if old else 0) + 1,
            sync_seq=self.sequence,
            created_at="2026-11-17T00:00:00+00:00",
            updated_at="2026-11-17T01:00:00+00:00",
            deleted_at="2026-11-17T01:00:00+00:00" if p["p_deleted"] else None,
        )
        self.notes[nid] = note
        self.receipts[key] = dict(outcome="ok", note=copy.deepcopy(note))
        if self.lose_response:
            self.lose_response = False
            raise CloudError("offline")
        return copy.deepcopy(self.receipts[key])


class Client:
    def __init__(self, path, server, identity=None, vault=None):
        self.db = Database(path)
        self.repo = SQLiteNotesRepository(self.db)
        self.store = CloudStore(self.db)
        self.auth = identity or IdentityFixture()
        self.vault = vault or MemoryVault()
        self.engine = SyncEngine(self.store, self.auth, server, self.vault)

    def sync(self):
        self.engine.cycle(True)
        self.store.apply_inbox(self.auth.uid)


@pytest.fixture
def pair(tmp_path):
    server = ServerFixture()
    a, b = Client(tmp_path / "a.sqlite", server), Client(tmp_path / "b.sqlite", server)
    lesson = a.repo.create_lesson("Shared")
    a.store.enroll(lesson.id)
    a.sync()
    code = a.vault.get("invite:" + lesson.id)["code"]
    b.vault.put("join", dict(code=code))
    b.store.command("join", vault_key="join")
    b.sync()
    yield server, a, b, lesson
    a.db.close()
    b.db.close()


def test_two_independent_clients_share_edit_delete_preserve_author(pair):
    server, a, b, lesson = pair
    n = b.repo.create_note(lesson.id, "Title", "From B")
    b.sync()
    a.sync()
    incoming = a.repo.list_notes(lesson.id)[0]
    assert incoming.content == "From B"
    a.repo.update_note(incoming, "Edited", "By A")
    a.sync()
    b.sync()
    assert b.repo.list_notes(lesson.id)[0].content == "By A"
    assert server.notes[n.id]["author_id"] == b.auth.uid
    b.repo.delete_note(b.repo.list_notes(lesson.id)[0])
    b.sync()
    a.sync()
    assert a.repo.list_notes(lesson.id) == []
    assert not a.store.rows("SELECT * FROM cloud_outbox")


def test_offline_queue_survives_restart_and_reconnect(pair, tmp_path):
    server, a, b, lesson = pair
    server.online = False
    n = a.repo.create_note(lesson.id, "Offline", "Never lose this")
    with pytest.raises(CloudError, match="offline"):
        a.sync()
    identity, vault = a.auth, a.vault
    a.db.close()
    reopened = Client(tmp_path / "a.sqlite", server, identity, vault)
    try:
        assert reopened.repo.list_notes(lesson.id)[0].content == "Never lose this"
        server.online = True
        reopened.sync()
        b.sync()
        assert server.notes[n.id]["content"] == "Never lose this"
        assert b.repo.list_notes(lesson.id)[0].id == n.id
    finally:
        reopened.db.close()
        # fixture teardown uses close, which SQLite allows repeatedly


def test_lost_response_then_further_edit_retries_frozen_operation(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "First")
    server.lose_response = True
    with pytest.raises(CloudError):
        a.sync()
    frozen = a.store.rows("SELECT * FROM cloud_inflight")[0]
    a.repo.update_note(n, "Title", "Second")
    assert a.store.rows("SELECT * FROM cloud_outbox")[0]["operation_id"] != frozen["operation_id"]
    a.sync()
    a.sync()
    b.sync()
    assert server.notes[n.id]["revision"] == 2
    assert b.repo.list_notes(lesson.id)[0].content == "Second"
    assert not a.store.rows("SELECT * FROM cloud_conflicts")
    assert not a.store.rows("SELECT * FROM cloud_inflight")


def test_concurrent_edit_conflict_keeps_both_versions_and_latest_buffer(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "Base")
    a.sync()
    b.sync()
    an, bn = a.repo.list_notes(lesson.id)[0], b.repo.list_notes(lesson.id)[0]
    a.repo.update_note(an, "Title", "A edit")
    b.repo.update_note(bn, "Title", "B edit")
    a.sync()
    b.sync()
    assert b.repo.list_notes(lesson.id)[0].content == "B edit"
    conflict = b.store.rows("SELECT * FROM cloud_conflicts")[0]
    assert json.loads(conflict["remote_json"])["content"] == "A edit"
    current = b.repo.list_notes(lesson.id)[0]
    b.repo.update_note(current, "Title", "B latest edit")
    b.store.resolve(n.id, False, conflict["server_revision"])
    assert b.repo.list_notes(lesson.id)[0].content == "A edit"
    archive = json.loads(b.store.rows("SELECT * FROM cloud_conflict_archive")[0]["versions_json"])
    assert json.loads(archive["local_json"])["content"] == "B latest edit"
    assert not b.store.rows("SELECT * FROM cloud_outbox")


def test_resolve_local_uses_new_server_revision(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "Base")
    a.sync()
    b.sync()
    a.repo.update_note(a.repo.list_notes(lesson.id)[0], "Title", "A")
    b.repo.update_note(b.repo.list_notes(lesson.id)[0], "Title", "B")
    a.sync()
    b.sync()
    b.store.resolve(n.id, True, 2)
    b.sync()
    a.sync()
    assert a.repo.list_notes(lesson.id)[0].content == "B"
    assert server.notes[n.id]["revision"] == 3
    assert server.notes[n.id]["author_id"] == a.auth.uid


def test_private_local_notes_never_enqueued_or_uploaded(pair):
    server, a, b, lesson = pair
    private = a.repo.create_lesson("Private")
    n = a.repo.create_note(private.id, "Private", "Secret local")
    a.sync()
    assert n.id not in server.notes
    assert not a.store.rows("SELECT * FROM cloud_outbox")


def test_closed_session_retains_unuploaded_local_changes(pair):
    server, a, b, lesson = pair
    n = b.repo.create_note(lesson.id, "Pending", "Offline edit")
    a.store.command("finish", lesson.id)
    a.sync()
    b.sync()
    assert b.store.scope(lesson.id)["status"] == "closed"
    assert b.repo.list_notes(lesson.id)[0].content == "Offline edit"
    assert b.store.rows("SELECT * FROM cloud_outbox")[0]["note_id"] == n.id


def test_conflict_resolution_rejects_stale_dialog(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "Base")
    a.sync()
    b.sync()
    a.repo.update_note(a.repo.list_notes(lesson.id)[0], "Title", "A")
    b.repo.update_note(b.repo.list_notes(lesson.id)[0], "Title", "B")
    a.sync()
    b.sync()
    with pytest.raises(ValueError):
        b.store.resolve(n.id, False, 999)
    assert b.store.rows("SELECT * FROM cloud_conflicts")


def test_auth_refresh_persists_identity_and_never_logs_tokens():
    vault = MemoryVault()

    class Transport:
        calls = []

        def rpc(self, *args):
            return dict(protocol=2, enabled=True)

        def request(self, path, body):
            self.calls.append(path)
            return dict(
                user=dict(id="same-user"),
                access_token="access",
                refresh_token="refresh",
                expires_in=3600,
            )

    transport = Transport()
    first = SessionManager(transport, vault).ensure()
    second = SessionManager(transport, vault).ensure()
    assert first.uid == second.uid == "same-user"
    assert transport.calls == ["/auth/v1/signup", "/auth/v1/token?grant_type=refresh_token"]
    assert "access" not in json.dumps(vault.values)
    assert "access" not in repr(first)


def test_invalid_saved_auth_never_creates_replacement_anonymous_user():
    vault = MemoryVault()
    vault.put("auth", dict(uid="old", refresh_token="revoked"))

    class Transport:
        def request(self, path, body):
            assert "refresh_token" in path
            raise CloudError("auth_rejected")

        def rpc(self, *args):
            pytest.fail("must not signup over an existing identity")

    with pytest.raises(CloudError):
        SessionManager(Transport(), vault).ensure()
    assert vault.get("auth")["uid"] == "old"


def test_upgrade_v1_retains_exact_user_rows_and_creates_no_uploads(tmp_path):
    import sqlite3

    from englishnotes.storage.database import MIGRATIONS

    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as db:
        for statement in MIGRATIONS[1]:
            db.execute(statement)
        db.execute("INSERT INTO lessons VALUES('local','Old','a','b',7,NULL)")
        db.execute("INSERT INTO notes VALUES('n','local','Unicode','Привет 🍎','a','b',9,NULL)")
        db.execute("PRAGMA user_version=1")
        before = db.execute("SELECT * FROM notes").fetchall()
    upgraded = Database(path)
    try:
        assert [tuple(r) for r in upgraded.connection.execute("SELECT * FROM notes")] == before
        assert not CloudStore(upgraded).rows("SELECT * FROM cloud_outbox")
        assert upgraded.connection.execute("PRAGMA user_version").fetchone()[0] == 2
    finally:
        upgraded.close()


def test_staged_remote_changes_do_not_modify_gui_editor_until_apply(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "First")
    a.sync()
    b.sync()
    a.repo.update_note(a.repo.list_notes(lesson.id)[0], "Title", "Remote")
    a.sync()
    b.engine.cycle(True)
    assert b.repo.list_notes(lesson.id)[0].content == "First"
    # GUI flush occurs before apply, so a pending keystroke becomes a conflict, not lost text.
    b.repo.update_note(b.repo.list_notes(lesson.id)[0], "Title", "Unflushed editor text")
    b.store.apply_inbox(b.auth.uid)
    assert b.repo.list_notes(lesson.id)[0].content == "Unflushed editor text"
    assert b.store.rows("SELECT * FROM cloud_conflicts")[0]["note_id"] == n.id


def test_remote_private_id_collision_does_not_attach_existing_lesson(pair):
    server, a, b, lesson = pair
    private = b.repo.create_lesson("Private")
    session = copy.deepcopy(server.sessions[lesson.id])
    session["id"] = private.id
    b.store.stage(b.auth.uid, dict(sessions=[session], notes=[], cursor=0))
    b.store.apply_inbox(b.auth.uid)
    scopes = b.store.rows("SELECT * FROM cloud_lessons WHERE remote_id=?", (private.id,))
    assert scopes[0]["local_id"] != private.id
    assert b.store.scope(private.id) is None


def test_vault_failure_prevents_using_unpersisted_auth():
    from englishnotes.auth.vault import VaultError

    class BrokenVault(MemoryVault):
        def put(self, *args):
            raise VaultError("unavailable")

    class Transport:
        def rpc(self, *args):
            return dict(protocol=2, enabled=True)

        def request(self, *args):
            return dict(user=dict(id="u"), access_token="access", refresh_token="refresh")

    session = SessionManager(Transport(), BrokenVault())
    with pytest.raises(VaultError):
        session.ensure()
    assert session.identity is None


def test_refresh_cannot_silently_switch_identity():
    vault = MemoryVault()
    vault.put("auth", dict(uid="original", refresh_token="refresh"))

    class Transport:
        def request(self, *args):
            return dict(user=dict(id="different"), refresh_token="r", access_token="a")

    with pytest.raises(CloudError, match="identity_changed"):
        SessionManager(Transport(), vault).ensure()
    assert vault.get("auth")["uid"] == "original"


@pytest.mark.parametrize(
    "url,key",
    [
        ("http://example.com", "sb_publishable_public"),
        ("https://example.com/rest/v1/", "sb_publishable_public"),
        ("https://user:password@example.com", "sb_publishable_public"),
        ("https://example.com", "sb_secret_rejected"),
        ("https://example.com", "eyJlegacyRejected"),
    ],
)
def test_configuration_rejects_unsafe_origins_and_privileged_keys(monkeypatch, url, key):
    from englishnotes.cloud.config import CloudConfig

    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", key)
    with pytest.raises(ValueError):
        CloudConfig.load()


def test_profile_vault_namespace_stable_when_executable_moves(tmp_path):
    from englishnotes.cloud.config import CloudConfig

    config = CloudConfig("https://example.com", "sb_publishable_public")
    profile = tmp_path / "data" / "notes.sqlite"
    assert config.credential_service(profile) == config.credential_service(profile)
    assert config.credential_service(profile) != config.credential_service(
        tmp_path / "other.sqlite"
    )


def test_system_vault_uses_selected_os_store_without_plaintext_fallback(monkeypatch):
    import sys
    import types

    from englishnotes.auth.vault import SystemVault, VaultError

    class Backend:
        priority = 1
        data = {}

        def set_password(self, service, name, value):
            self.data[service, name] = value

        def get_password(self, service, name):
            return self.data.get((service, name))

        def delete_password(self, service, name):
            self.data.pop((service, name), None)

    module = types.ModuleType("keyring.backends.Windows")
    module.WinVaultKeyring = Backend
    monkeypatch.setitem(sys.modules, "keyring.backends.Windows", module)
    monkeypatch.setattr(sys, "platform", "win32")
    vault = SystemVault("test-profile")
    vault.put("auth", dict(refresh_token="not-a-real-token"))
    assert vault.get("auth")["refresh_token"] == "not-a-real-token"
    vault.remove("auth")
    assert vault.get("auth") is None
    Backend.priority = 0
    with pytest.raises(VaultError):
        SystemVault("no-file-fallback")


def test_private_realtime_join_token_and_invalidation_only(monkeypatch):
    import threading

    import englishnotes.cloud.realtime as realtime
    from englishnotes.cloud.config import CloudConfig
    from englishnotes.cloud.realtime import RealtimeHints

    class Socket:
        def __init__(self, url, **callbacks):
            self.url, self.callbacks, self.sent = url, callbacks, []

        def run_forever(self):
            pass

        def send(self, value):
            self.sent.append(json.loads(value))

        def close(self):
            pass

    monkeypatch.setattr(realtime.websocket, "WebSocketApp", Socket)
    wake = threading.Event()
    hints = RealtimeHints(CloudConfig("https://example.com", "sb_publishable_public"), wake.set)
    hints.configure("test-access", ["s1", "s2"])
    socket = hints.socket
    socket.callbacks["on_open"](socket)
    assert all(m["payload"]["config"]["private"] for m in socket.sent)
    assert all(m["payload"]["access_token"] == "test-access" for m in socket.sent)
    assert "test-access" not in socket.url
    socket.callbacks["on_message"](
        socket, json.dumps(dict(event="phx_reply", ref="1001", payload=dict(status="ok")))
    )
    assert not hints.connected  # heartbeat acknowledgment is not subscription authorization
    for ref in ("1", "2"):
        socket.callbacks["on_message"](
            socket, json.dumps(dict(event="phx_reply", ref=ref, payload=dict(status="ok")))
        )
    assert hints.connected
    socket.callbacks["on_message"](
        socket, json.dumps(dict(event="broadcast", payload=dict(changed=True)))
    )
    assert wake.is_set()
    hints.close()
    assert not hints.connected


def test_real_tls_transport_never_follows_redirects():
    from englishnotes.cloud.transport import NoRedirect

    assert NoRedirect().redirect_request(None, None, 302, "m", {}, "https://other.example") is None


def test_retry_receipt_does_not_downgrade_newer_metadata(pair):
    server, a, b, lesson = pair
    n = a.repo.create_note(lesson.id, "Title", "base")
    a.sync()
    queued = dict(operation_id="old", note_id=n.id)
    old = dict(server.notes[n.id])
    with a.db.transaction() as db:
        db.execute("UPDATE cloud_notes SET server_revision=99 WHERE note_id=?", (n.id,))
    a.store.ack(queued, old)
    assert a.store.rows("SELECT server_revision FROM cloud_notes")[0]["server_revision"] == 99


def test_offline_smoke_switch_prevents_all_cloud_initialization(monkeypatch):
    from englishnotes.cloud.config import CloudConfig

    monkeypatch.setenv("ENGLISHNOTES_DISABLE_CLOUD", "1")
    monkeypatch.setenv("SUPABASE_URL", "https://example.com")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_public")
    assert CloudConfig.load() is None


def test_background_worker_retries_after_network_recovery_and_stops(qtbot, tmp_path, monkeypatch):
    import englishnotes.cloud.worker as module
    from englishnotes.cloud.config import CloudConfig

    server = ServerFixture()
    vault = MemoryVault()
    identity = IdentityFixture()
    identity.identity = identity.ensure()

    class Hints:
        connected = False

        def __init__(self, *args):
            pass

        def configure(self, *args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(module, "SystemVault", lambda *args: vault)
    monkeypatch.setattr(module, "SupabaseHTTP", lambda *args: server)
    monkeypatch.setattr(module, "SessionManager", lambda *args: identity)
    monkeypatch.setattr(module, "RealtimeHints", Hints)
    db = Database(tmp_path / "thread.sqlite")
    repo, store = SQLiteNotesRepository(db), CloudStore(db)
    lesson = repo.create_lesson("Threaded")
    store.enroll(lesson.id)
    note = repo.create_note(lesson.id, "Offline", "Threaded queue")
    server.online = False
    worker = module.CloudWorker(
        db.path, CloudConfig("https://example.com", "sb_publishable_public")
    )
    states = []
    worker.state.connect(lambda code, message: states.append(code))
    try:
        worker.start()
        qtbot.waitUntil(lambda: "offline" in states, timeout=3000)
        assert store.rows("SELECT * FROM cloud_outbox")
        server.online = True
        worker.wake()
        qtbot.waitUntil(lambda: note.id in server.notes, timeout=5000)
        qtbot.waitUntil(lambda: not store.rows("SELECT * FROM cloud_outbox"), timeout=3000)
        assert server.notes[note.id]["content"] == "Threaded queue"
    finally:
        worker.stop()
        assert worker.wait(5000)
        db.close()


@pytest.mark.parametrize("payload_bytes,accepted", [(5_000_000, True), (17_000_000, False)])
def test_https_accepts_legacy_payloads_with_hard_memory_bound(payload_bytes, accepted):
    from englishnotes.cloud.config import CloudConfig
    from englishnotes.cloud.transport import SupabaseHTTP

    transport = SupabaseHTTP(CloudConfig("https://example.com", "sb_publishable_public"))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return (b'{"value":"' + b"x" * payload_bytes + b'"}')[:limit]

    class Opener:
        def open(self, *args, **kwargs):
            return Response()

    transport.opener = Opener()
    if accepted:
        assert len(transport.request("/rest/v1/rpc/example", {})["value"]) == payload_bytes
    else:
        with pytest.raises(CloudError, match="response_limit"):
            transport.request("/rest/v1/rpc/example", {})
