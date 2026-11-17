"""Opt-in real v2 Auth/RPC/Broadcast integration. Creates three anonymous identities.

No admin key. Leaves test lessons/profile databases for inspection. Never prints tokens/data.
"""

import argparse
import json
import threading
import time
from pathlib import Path
from uuid import uuid4

from launch_live_security import load_environment

from englishnotes.auth.session import SessionManager
from englishnotes.auth.vault import SystemVault
from englishnotes.cloud.config import CloudConfig
from englishnotes.cloud.engine import SyncEngine
from englishnotes.cloud.realtime import RealtimeHints
from englishnotes.cloud.transport import CloudError, SupabaseHTTP
from englishnotes.storage.cloud_store import CloudStore
from englishnotes.storage.database import Database
from englishnotes.storage.repository import SQLiteNotesRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run", action="store_true", help="Authorize test account and session creation"
    )
    args = parser.parse_args()
    if not args.run:
        print("NOT RUN: supply --run. Uses real cloud resources and three test profiles.")
        return 2
    root = Path(__file__).resolve().parents[2]
    databases, hints = [], []
    checks = []
    cleanup = None

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
        print("PASS: " + name)

    def client(label):
        db = Database(root / "work" / "desktop-live" / label / "englishnotes.sqlite3")
        databases.append(db)
        vault = SystemVault(config.credential_service(db.path))
        session = SessionManager(transport, vault)
        identity = session.ensure()
        store = CloudStore(db)
        engine = SyncEngine(store, session, transport, vault)
        return db, SQLiteNotesRepository(db), store, engine, vault, identity

    def sync(client):
        client[3].cycle(True)
        client[2].apply_inbox(client[5].uid)

    try:
        load_environment(root / ".env")
        config = CloudConfig.load()
        if not config:
            raise CloudError("configuration_missing")
        transport = SupabaseHTTP(config)
        a, b, c = [client(label) for label in ("A", "B", "C")]
        check("three independent real Auth identities", len({x[5].uid for x in (a, b, c)}) == 3)
        refreshed = SessionManager(transport, a[4]).ensure()
        check("restart refresh retains identity", refreshed.uid == a[5].uid)
        lesson = a[1].create_lesson("Desktop integration test")
        a[2].enroll(lesson.id)
        sync(a)
        cleanup = (lesson.id, a[5].access_token)
        check("creator registered", a[2].scope(lesson.id)["owner_id"] == a[5].uid)
        invite = a[4].get("invite:" + lesson.id)
        b[4].put("live-join", dict(code=invite["code"]))
        b[2].command("join", vault_key="live-join")
        sync(b)
        check("second independent user joins", b[2].scope(lesson.id)["owner_id"] == a[5].uid)
        check(
            "wrong code is rejected",
            transport.rpc(
                "en_join_session",
                dict(p_code="0" * 64, p_operation_id=str(uuid4())),
                c[5].access_token,
            )["outcome"]
            == "invalid_invitation",
        )
        outside = transport.rpc("en_read", dict(p_after=0, p_limit=64), c[5].access_token)
        check(
            "outsider cannot read session", all(s["id"] != lesson.id for s in outside["sessions"])
        )
        denied = transport.rpc(
            "en_write_note",
            dict(
                p_operation_id=str(uuid4()),
                p_note_id=str(uuid4()),
                p_lesson_id=lesson.id,
                p_base_revision=0,
                p_title="blocked",
                p_content="blocked",
                p_position=0,
            ),
            c[5].access_token,
        )
        check("outsider cannot write", denied["outcome"] == "forbidden")
        check(
            "peer cannot finish owner session",
            transport.rpc("en_finish_session", dict(p_lesson_id=lesson.id), b[5].access_token)[
                "outcome"
            ]
            == "forbidden",
        )
        events = [threading.Event(), threading.Event()]
        for participant, event in zip((a, b), events, strict=True):
            hint = RealtimeHints(config, event.set)
            hints.append(hint)
            hint.configure(participant[5].access_token, [lesson.id])
        deadline = time.monotonic() + 20
        while not all(h.connected for h in hints) and time.monotonic() < deadline:
            time.sleep(0.2)
        if not all(h.connected for h in hints):
            for label, hint in zip(("A", "B"), hints, strict=True):
                print("REALTIME_" + label + "=" + json.dumps(hint.diagnostics(), sort_keys=True))
            if not any(h.rejected for h in hints):
                raise CloudError("realtime_connection_unverified")
        check("both private Realtime subscriptions authorized", all(h.connected for h in hints))
        outsider_event = threading.Event()
        outsider_hint = RealtimeHints(config, outsider_event.set)
        hints.append(outsider_hint)
        outsider_hint.configure(c[5].access_token, [lesson.id])
        deadline = time.monotonic() + 10
        while not outsider_hint.rejected and time.monotonic() < deadline:
            time.sleep(0.2)
        if not outsider_hint.rejected:
            if outsider_hint.connected:
                raise AssertionError("outsider private subscription was accepted")
            print("REALTIME_C=" + json.dumps(outsider_hint.diagnostics(), sort_keys=True))
            raise CloudError("realtime_authorization_unverified")
        check("outsider private subscription explicitly refused", not outsider_hint.connected)
        for event in events:
            event.clear()
        note = b[1].create_note(lesson.id, "Live", "From B")
        sync(b)
        check("Realtime invalidation delivered to A", events[0].wait(10))
        sync(a)
        check(
            "A reads B note with preserved author",
            a[1].list_notes(lesson.id)[0].content == "From B"
            and a[2].rows("SELECT author_id FROM cloud_notes WHERE note_id=?", (note.id,))[0][
                "author_id"
            ]
            == b[5].uid,
        )
        a[1].update_note(a[1].list_notes(lesson.id)[0], "Live", "From A concurrently")
        b[1].update_note(b[1].list_notes(lesson.id)[0], "Live", "From B concurrently")
        sync(a)
        sync(b)
        check(
            "concurrent edit preserved as conflict",
            bool(b[2].rows("SELECT * FROM cloud_conflicts")),
        )
        revision = b[2].rows("SELECT server_revision FROM cloud_conflicts")[0]["server_revision"]
        b[2].resolve(note.id, True, revision)
        sync(b)
        sync(a)
        check(
            "resolved version shared",
            a[1].list_notes(lesson.id)[0].content == "From B concurrently",
        )
        # Deliberately do not execute HTTP while editing: simulates an offline queue.
        a[1].update_note(a[1].list_notes(lesson.id)[0], "Offline", "Queued offline")
        check("offline edit committed locally", bool(a[2].rows("SELECT * FROM cloud_outbox")))
        a[0].close()
        reopened = client("A")
        check(
            "profile reopen keeps offline edit",
            reopened[1].list_notes(lesson.id)[0].content == "Queued offline",
        )
        sync(reopened)
        sync(b)
        check(
            "queue drains on reconnect",
            not reopened[2].rows("SELECT * FROM cloud_outbox")
            and b[1].list_notes(lesson.id)[0].content == "Queued offline",
        )
        b[1].delete_note(b[1].list_notes(lesson.id)[0])
        sync(b)
        sync(reopened)
        check("deletion synchronized", not reopened[1].list_notes(lesson.id))
        reopened[2].command("finish", lesson.id)
        sync(reopened)
        sync(b)
        check("closed status synchronized", b[2].scope(lesson.id)["status"] == "closed")
        print("Live Desktop result: PASS")
        return 0
    except AssertionError as error:
        print("FAIL: " + str(error))
        return 1
    except CloudError as error:
        print("BLOCKED: " + error.code)
        return 2
    except Exception:
        print("BLOCKED: configuration, credential store or protocol error (details hidden).")
        return 2
    finally:
        if cleanup:
            try:
                transport.rpc("en_finish_session", {"p_lesson_id": cleanup[0]}, cleanup[1])
            except Exception:
                print("Cleanup: test session may remain active; no data deleted.")
        for hint in hints:
            hint.close()
        for db in databases:
            db.close()
        print("Completed checks: " + str(len(checks)) + ". Unexecuted checks are not passes.")


if __name__ == "__main__":
    raise SystemExit(main())
