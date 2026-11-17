"""Offline tests of the live test RUNNER; these are not live Supabase results."""

import csv
import importlib.util
import io
import json
import re
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "englishnotes_live_test", ROOT / "supabase/tests/live_security.py"
)
live = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = live
SPEC.loader.exec_module(live)

KEY = "sb_publishable_unit_key_do_not_log"
TOKENS = {label: f"unit-token-{label}-DO-NOT-LOG" for label in ("A", "B", "C")}
INVITATION = "f" * 64


def snapshot():
    sql = (ROOT / "supabase/migrations/20261117000100_lesson_sessions.sql").read_text()
    functions = []
    for schema, name, body in re.findall(
        r"CREATE FUNCTION (\w+)\.(\w+)\s*\(.*?AS \$function\$(.*?)\$function\$;", sql, re.DOTALL
    ):
        args = {
            "create_lesson_session": ["p_title", "p_creator_role", "p_invitation_ttl"],
            "join_lesson_session": ["p_invitation_code"],
        }.get(name, [])
        functions.append(
            {
                "schema": schema,
                "name": name,
                "body": body,
                "input_args": args,
                "input_types": {
                    "create_lesson_session": "text, text, interval",
                    "join_lesson_session": "text",
                }.get(name, ""),
                "settings": ['search_path=""'],
            }
        )
    tables = []
    for name, columns in (
        ("lesson_sessions", live.SESSION_COLUMNS + ",invitation_code_hash"),
        ("lesson_members", live.MEMBER_COLUMNS + ",joined_at"),
        ("lesson_notes", live.NOTE_COLUMNS + ",created_at,updated_at"),
    ):
        tables.append(
            {"schema": "public", "name": name, "columns": [{"name": c} for c in columns.split(",")]}
        )
    return {"format_version": 1, "functions": functions, "tables": tables}


@pytest.fixture
def configured(monkeypatch, tmp_path):
    path = tmp_path / "applied.json"
    path.write_text(json.dumps(snapshot()))
    monkeypatch.setenv("SUPABASE_URL", "https://unit.invalid")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", KEY)
    monkeypatch.setenv("SUPABASE_SCHEMA_FILE", str(path))
    return path


class Response(io.BytesIO):
    def __init__(self, status, value):
        super().__init__(json.dumps(value).encode() if value is not None else b"")
        self.code = status


class FakeAPI:
    """Deterministic HTTP responses to validate assertions and redaction only."""

    def __init__(self, *, leak=False, bad_insert=False, fail_signup=None):
        self.uids = {label: str(uuid.uuid4()) for label in TOKENS}
        self.lesson = str(uuid.uuid4())
        self.notes = {}
        self.leak = leak
        self.bad_insert = bad_insert
        self.fail_signup = fail_signup
        self.calls = []

    def open(self, request, timeout):
        path = urlsplit(request.full_url).path
        query = parse_qs(urlsplit(request.full_url).query)
        payload = json.loads(request.data) if request.data else None
        token = request.get_header("Authorization")
        who = next((label for label, value in TOKENS.items() if token == "Bearer " + value), None)
        assert request.get_header("Apikey") == KEY
        self.calls.append((request.method, path, who))
        if path == "/auth/v1/signup":
            label = payload["data"]["actor"]
            assert token is None, "A sign-in must not reuse another actor JWT"
            if label == self.fail_signup:
                return Response(
                    429, {"code": "over_request_rate_limit", "message": KEY + str(TOKENS)}
                )
            return Response(
                200,
                {
                    "access_token": TOKENS[label],
                    "refresh_token": "never-log-refresh",
                    "user": {"id": self.uids[label], "is_anonymous": True},
                },
            )
        assert who is not None
        if path == "/auth/v1/user":
            return Response(200, {"id": self.uids[who], "is_anonymous": True})
        if path == "/auth/v1/logout":
            return Response(204, None)
        if path.endswith("/rpc/create_lesson_session"):
            assert set(payload) == {"p_title", "p_creator_role", "p_invitation_ttl"}
            return Response(
                200, [{"lesson_id": self.lesson, "invitation_code": INVITATION, "outcome": "ok"}]
            )
        if path.endswith("/rpc/join_lesson_session"):
            assert set(payload) == {"p_invitation_code"}
            return Response(
                200,
                [
                    {
                        "lesson_id": self.lesson if who == "B" else None,
                        "outcome": "ok" if who == "B" else "invalid_invitation",
                    }
                ],
            )
        denied = {"code": "42501", "message": KEY + str(TOKENS) + INVITATION}
        if path.endswith("/lesson_sessions"):
            if request.method == "PATCH" or query.get("select") == ["invitation_code_hash"]:
                return Response(403, denied)
            return Response(
                200,
                []
                if who == "C" and not self.leak
                else [{"id": self.lesson, "created_by": self.uids["A"]}],
            )
        if path.endswith("/lesson_members"):
            if request.method != "GET":
                return Response(403, denied)
            return Response(
                200,
                [
                    {"lesson_id": self.lesson, "user_id": self.uids[label], "role": role}
                    for label, role in (("A", "student"), ("B", "teacher"))
                ],
            )
        assert path.endswith("/lesson_notes")
        selected = list(self.notes.values())
        if "id" in query:
            selected = [n for n in selected if n["id"] == query["id"][0][3:]]
        if request.method == "POST":
            if who == "C":
                return Response(
                    400 if self.bad_insert else 403,
                    {"code": "23503"} if self.bad_insert else denied,
                )
            row = dict(payload, author_id=self.uids[who], revision=1, deleted_at=None)
            self.notes[row["id"]] = row
            return Response(201, [row])
        if request.method == "DELETE":
            return Response(403, denied)
        if who == "C":
            return Response(200, selected if self.leak and request.method == "GET" else [])
        if request.method == "PATCH":
            for row in selected:
                row.update(payload)
                row["revision"] += 1
        return Response(200, selected)


def use_fake_api(monkeypatch, api):
    monkeypatch.setattr(live, "build_opener", lambda *args: api)


def test_all_live_assertions_have_expected_success_and_denial_paths(
    configured, monkeypatch, tmp_path, capsys
):
    api = FakeAPI()
    use_fake_api(monkeypatch, api)
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 0
    report = json.loads(path.read_text())
    assert report["status"] == "PASS"
    assert len(report["scenarios"]) == 14
    assert set(report["scenarios"].values()) == {"PASS"}
    assert len({uid for uid in report["fixtures"]["users"].values()}) == 3
    output = capsys.readouterr().out + path.read_text()
    for secret in (KEY, INVITATION, "never-log-refresh", *TOKENS.values()):
        assert secret not in output
    assert sum(path == "/auth/v1/logout" for _, path, _ in api.calls) == 3


def test_rls_leak_is_a_failure_even_if_other_denials_pass(configured, monkeypatch, tmp_path):
    api = FakeAPI(leak=True)
    use_fake_api(monkeypatch, api)
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 1
    report = json.loads(path.read_text())
    assert report["scenarios"]["07_C_read_session"] == "FAIL"
    assert report["scenarios"]["08_C_read_notes"] == "FAIL"
    assert any(c.get("requires_security_review") for c in report["checks"])


def test_bad_payload_error_is_not_counted_as_rls_protection(configured, monkeypatch, tmp_path):
    use_fake_api(monkeypatch, FakeAPI(bad_insert=True))
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 1
    report = json.loads(path.read_text())
    assert report["scenarios"]["09_C_insert_note"] == "FAIL"


def test_auth_rate_limit_blocks_run_without_counting_later_tests_as_passes(
    configured,
    monkeypatch,
    tmp_path,
    capsys,
):
    api = FakeAPI(fail_signup="B")
    use_fake_api(monkeypatch, api)
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 2
    report = json.loads(path.read_text())
    assert report["status"] == "BLOCKED"
    assert report["scenarios"]["04_A_creates"] == "NOT_RUN"
    assert not any("/rest/" in path for _, path, _ in api.calls)
    assert KEY not in capsys.readouterr().out + path.read_text()


@pytest.mark.parametrize("change", ["body", "input_args", "settings", "columns"])
def test_applied_schema_drift_stops_before_any_network_call(
    configured, monkeypatch, tmp_path, change
):
    value = json.loads(configured.read_text())
    if change == "columns":
        value["tables"][0]["columns"].pop()
    else:
        function = next(f for f in value["functions"] if f["name"] == "create_lesson_session")
        function[change] = "changed" if change == "body" else []
    configured.write_text(json.dumps(value))
    api = FakeAPI()
    use_fake_api(monkeypatch, api)
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 2
    assert not api.calls
    assert set(json.loads(path.read_text())["scenarios"].values()) == {"NOT_RUN"}


@pytest.mark.parametrize(
    "key", ["sb_secret_forbidden", "service_role", "eyJlegacy-token", "sb_publishable_ has-space"]
)
def test_only_publishable_key_is_accepted(configured, monkeypatch, key):
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", key)
    with pytest.raises(live.SetupError):
        live.Config.from_environment()


@pytest.mark.parametrize(
    "url",
    ["http://unit.invalid", "https://user:pass@unit.invalid", "https://unit.invalid/?x=secret"],
)
def test_url_cannot_contain_credentials_or_query(configured, monkeypatch, url):
    monkeypatch.setenv("SUPABASE_URL", url)
    with pytest.raises(live.SetupError):
        live.Config.from_environment()


@pytest.mark.parametrize(
    "wrapper",
    [lambda x: x, lambda x: [{"schema_snapshot": x}], lambda x: {"schema_snapshot": json.dumps(x)}],
)
def test_dashboard_snapshot_export_formats_are_readable(tmp_path, wrapper):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(wrapper(snapshot())))
    assert live.read_snapshot(path)["format_version"] == 1


def test_unexpected_row_shapes_cannot_satisfy_assertions():
    assert live.one_row(live.Reply(200, ["not a row"])) == {}
    assert not live.denied(live.Reply(401, {"code": "42501"}))
    assert not live.denied(live.Reply(400, {"code": "23503"}))
    assert live.Reply(403, {"code": KEY}).code is None


def test_dashboard_csv_export_is_readable(tmp_path):
    path = tmp_path / "schema.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["schema_snapshot"])
        writer.writeheader()
        writer.writerow({"schema_snapshot": json.dumps(snapshot())})
    assert live.read_snapshot(path)["format_version"] == 1


def test_network_failure_is_blocked_and_does_not_echo_exception(
    configured, monkeypatch, tmp_path, capsys
):
    class Broken:
        def open(self, *args, **kwargs):
            raise URLError(KEY + str(TOKENS))

    use_fake_api(monkeypatch, Broken())
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 2
    report = json.loads(path.read_text())
    assert report["status"] == "BLOCKED"
    assert set(report["scenarios"].values()) == {"NOT_RUN"}
    assert KEY not in capsys.readouterr().out + path.read_text()


def test_real_http_denial_and_redirect_are_handled_without_forwarding_credentials(tmp_path):
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/must-not-receive-credentials")
                self.end_headers()
            else:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(json.dumps({"code": "42501", "message": KEY}).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = live.Config(f"http://127.0.0.1:{server.server_port}", KEY, tmp_path)
        client = live.Client(config, "unit HTTP transport")
        client.token = TOKENS["A"]
        assert client.request("GET", "/redirect").status == 302
        assert paths == ["/redirect"]
        assert live.denied(client.request("GET", "/denied"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_missing_configuration_is_not_run(monkeypatch, tmp_path):
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SCHEMA_FILE"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "report.json"
    assert live.main(["--report", str(path)]) == 2
    report = json.loads(path.read_text())
    assert report["status"] == "NOT_RUN"
    assert len(report["scenarios"]) == 14
    assert set(report["scenarios"].values()) == {"NOT_RUN"}


def test_local_launcher_does_not_evaluate_env_or_load_admin_keys(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "live_security", live)
    spec = importlib.util.spec_from_file_location(
        "live_local_launcher", ROOT / "supabase/tests/launch_live_security.py"
    )
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    for key in loader.ALLOWED | {"SUPABASE_SERVICE_ROLE_KEY"}:
        # Register restoration even if the variable did not exist before this test.
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.setenv("SUPABASE_URL", "https://environment-wins.invalid")
    env = tmp_path / ".env"
    env.write_text(
        "SUPABASE_URL=https://file.invalid\n"
        "SUPABASE_PUBLISHABLE_KEY='sb_publishable_$(not-executed)'\n"
        "SUPABASE_SERVICE_ROLE_KEY=never-load-admin\n"
    )
    loader.load_environment(env)
    assert live.os.environ["SUPABASE_URL"] == "https://environment-wins.invalid"
    assert live.os.environ["SUPABASE_PUBLISHABLE_KEY"] == "sb_publishable_$(not-executed)"
    assert "SUPABASE_SERVICE_ROLE_KEY" not in live.os.environ
