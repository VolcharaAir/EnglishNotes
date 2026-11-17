"""MANUAL local verification. Creates/removes a disposable PostgreSQL Docker container.

Does not read .env, connect to Supabase, or touch SQLite. Not wired to app startup/CI.
"""

import argparse
import concurrent.futures
import json
import subprocess
import threading
import time
import uuid
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-host", help="Optional Docker daemon endpoint")
    parser.add_argument("--image", default="postgres:16")
    parser.add_argument("--desktop", action="store_true", help="Also verify migration v2")
    args = parser.parse_args()
    docker = ["docker"] + (["--host=" + args.docker_host] if args.docker_host else [])
    container = "englishnotes-sql-test-" + uuid.uuid4().hex[:12]
    root = Path(__file__).resolve().parents[1]

    def command(arguments, *, content=None, timeout=60):
        result = subprocess.run(
            docker + arguments, input=content, text=True, capture_output=True, timeout=timeout
        )
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        return result.stdout.strip()

    def sql(content):
        return command(
            [
                "exec",
                "-i",
                container,
                "psql",
                "-X",
                "-qAt",
                "-U",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
            ],
            content=content,
        )

    try:
        command(
            [
                "run",
                "--rm",
                "-d",
                "--name",
                container,
                "--network",
                "none",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
                args.image,
                "-c",
                "wal_level=logical",
            ],
            timeout=180,
        )
        deadline = time.monotonic() + 30
        while True:
            try:
                # The image briefly starts a Unix-socket-only init server first.
                # Wait for TCP so we do not race that server's restart.
                command(["exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres"])
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)
        print(sql("SELECT version();"))
        sql((root / "tests" / "bootstrap.sql").read_text())
        sql((root / "migrations" / "20261117000100_lesson_sessions.sql").read_text())
        output = sql((root / "tests" / "security.sql").read_text())
        assert "SQL security assertions passed" in output
        print("SQL migration and RLS/ACL/RPC security assertions passed.")

        users = [str(uuid.uuid4()) for _ in range(4)]
        sql("INSERT INTO auth.users(id) VALUES " + ",".join(f"('{u}')" for u in users) + ";")

        def join_as(user, code, barrier, hold=False):
            barrier.wait(timeout=20)
            return sql(
                f"BEGIN; SET LOCAL ROLE authenticated; "
                f"SET LOCAL request.jwt.claim.sub = '{user}'; "
                f"SELECT outcome FROM public.join_lesson_session('{code}'); "
                + ("DO $$ BEGIN PERFORM pg_sleep(0.3); END $$; " if hold else "")
                + "COMMIT;"
            )

        for _ in range(5):
            created = sql(
                f"BEGIN; SET LOCAL ROLE authenticated; "
                f"SET LOCAL request.jwt.claim.sub = '{users[0]}'; "
                "SELECT lesson_id,invitation_code FROM public.create_lesson_session('Race'); "
                "COMMIT;"
            )
            session, code = created.split("|")
            barrier = threading.Barrier(2)
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(join_as, u, code, barrier, True) for u in users[1:3]]
                results = [future.result() for future in futures]
            assert sorted(results) == ["invalid_invitation", "ok"], results
            count = sql(f"SELECT count(*) FROM public.lesson_members WHERE lesson_id='{session}';")
            assert count == "2", count
        print("5 concurrent last-seat races passed: exactly one join succeeds each time.")

        barrier = threading.Barrier(12)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(join_as, users[3], "0" * 64, barrier) for _ in range(12)]
            results = [future.result() for future in futures]
        assert results.count("invalid_invitation") == 5, results
        assert results.count("rate_limited") == 7, results
        attempts = sql(
            "SELECT attempts FROM englishnotes_private.rpc_limits "
            f"WHERE user_id='{users[3]}' AND action='join';"
        )
        assert attempts == "12", attempts
        print("Concurrent budget check passed: 5 attempts, 7 refusals, 12 persisted calls.")
        if args.desktop:
            sql((root / "tests" / "desktop_bootstrap.sql").read_text())
            sql((root / "migrations" / "20261117000200_desktop_sync.sql").read_text())
            sql((root / "verify_desktop.sql").read_text())
            print(sql((root / "tests" / "desktop_security.sql").read_text()).splitlines()[-1])
            print(sql((root / "tests" / "desktop_payloads.sql").read_text()).splitlines()[-1])
            sql("UPDATE englishnotes_private.cloud_limits SET enabled=true,auth_hook_ready=true;")
            u = str(uuid.uuid4())
            sid, nid = str(uuid.uuid4()), str(uuid.uuid4())
            sql(f"INSERT INTO auth.users VALUES('{u}');")

            def as_user(expression):
                return json.loads(
                    sql(
                        f"BEGIN; SET LOCAL ROLE authenticated; "
                        f"SET LOCAL request.jwt.claim.sub='{u}'; SELECT {expression}; COMMIT;"
                    )
                )

            assert as_user(f"public.en_create_session('{sid}','CAS')")["outcome"] == "ok"
            assert (
                as_user(f"public.en_write_note(gen_random_uuid(),'{nid}','{sid}',0,'n','base',0)")[
                    "outcome"
                ]
                == "ok"
            )
            barrier = threading.Barrier(2)

            def edit(text):
                barrier.wait(timeout=20)
                return as_user(
                    f"public.en_write_note(gen_random_uuid(),'{nid}','{sid}',1,'n','{text}',0)"
                )["outcome"]

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(edit, text) for text in ("left", "right")]
                assert sorted(f.result() for f in futures) == ["conflict", "ok"]
            print("Desktop concurrent CAS: one commit, one conflict; no lost update.")
    finally:
        subprocess.run(docker + ["rm", "-f", container], capture_output=True, check=False)


if __name__ == "__main__":
    main()
