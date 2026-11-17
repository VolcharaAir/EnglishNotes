"""Explicit live Supabase test. Environment-only configuration; no SDK/SQLite imports.

Creates three anonymous accounts and its own labelled test fixtures. Never applies
migrations, sets JWT claims, uses administrative keys, or changes policies.
"""

import argparse
import csv
import hashlib
import http.cookiejar
import io
import json
import os
import re
import secrets
import socket
import ssl
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

SESSION_COLUMNS = "id,title,created_by,created_at,invitation_expires_at,status"
NOTE_COLUMNS = "id,lesson_id,author_id,title,content,position,revision,deleted_at"
MEMBER_COLUMNS = "lesson_id,user_id,role"
SCENARIOS = {
    "01_A_sign_in": [
        "A anonymous sign-in",
        "A JWT accepted by Auth for the same anonymous identity",
    ],
    "02_B_sign_in": [
        "B anonymous sign-in",
        "B JWT accepted by Auth for the same anonymous identity",
    ],
    "03_C_sign_in": [
        "C anonymous sign-in",
        "C JWT accepted by Auth for the same anonymous identity",
    ],
    "04_A_creates": ["A creates a lesson through the actual RPC", "A is recorded as the creator"],
    "05_B_joins": ["B joins the lesson with its one-time invitation"],
    "06_C_bad_code": ["C wrong invitation is rejected without revealing a lesson ID"],
    "07_C_read_session": ["C cannot read A lesson directly"],
    "08_C_read_notes": ["C cannot read existing notes"],
    "09_C_insert_note": ["C cannot insert a note into A lesson", "C rejected insert left no row"],
    "10_C_modify_delete": [
        "C cannot modify A note",
        "C cannot soft-delete A note",
        "C cannot hard-delete A note",
        "A canary survives C update/delete attempts unchanged",
    ],
    "11_C_membership": [
        "C cannot add itself to the roster",
        "C cannot change member roles",
        "C cannot remove the creator",
    ],
    "12_B_adds_note": ["B can add a note with B as its author"],
    "13_A_reads_B_note": ["A can read B note"],
    "14_B_not_owner": [
        "B cannot take ownership of A lesson",
        "B cannot change its role",
        "B cannot remove A membership",
        "B still sees A as the creator",
        "roster remains exactly A/student and B/teacher",
    ],
}


class SetupError(Exception):
    """Static, safe-to-log setup failure; never include provider messages."""


class NetworkFailure(Exception):
    pass


def transport_failure_code(error):
    """Classify the failure without exposing free-form exception text or URLs."""
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "TLS_CERT_VERIFY_FAILED"
    if isinstance(reason, ssl.SSLError):
        return "TLS_ERROR"
    if isinstance(reason, socket.gaierror):
        return "DNS_LOOKUP_FAILED"
    if isinstance(reason, TimeoutError):
        return "CONNECTION_TIMEOUT"
    if isinstance(reason, ConnectionRefusedError):
        return "CONNECTION_REFUSED"
    if isinstance(reason, ConnectionResetError):
        return "CONNECTION_RESET"
    if isinstance(reason, str) and "tunnel connection failed" in reason.lower():
        return "PROXY_TUNNEL_FAILED"
    return "TRANSPORT_ERROR"


class StopScenario(Exception):
    pass


@dataclass(repr=False)
class Config:
    url: str
    key: str
    schema_file: Path

    @classmethod
    def from_environment(cls):
        address = os.environ.get("SUPABASE_URL", "").rstrip("/")
        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
        schema = os.environ.get("SUPABASE_SCHEMA_FILE", "")
        if not address or not key or not schema:
            raise SetupError("Set SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY and SUPABASE_SCHEMA_FILE.")
        parts = urlsplit(address)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username
            or parts.password
            or parts.path
            or parts.query
            or parts.fragment
        ):
            raise SetupError("SUPABASE_URL must be a plain HTTPS origin without credentials.")
        # Modern publishable keys only. No legacy JWT-shaped API key, secret or service-role key.
        if not key.startswith("sb_publishable_") or any(c.isspace() for c in key):
            raise SetupError("Use a modern sb_publishable_ key, never a secret/service-role key.")
        return cls(address, key, Path(schema))


@dataclass(repr=False)
class Reply:
    status: int
    body: object

    @property
    def code(self):
        code = self.body.get("code") if isinstance(self.body, dict) else None
        # Do not copy arbitrary backend strings/messages into a report.
        known = {
            "42501",
            "23505",
            "23503",
            "23514",
            "22023",
            "PGRST202",
            "PGRST204",
            "anonymous_provider_disabled",
            "over_request_rate_limit",
            "over_email_send_rate_limit",
            "captcha_failed",
            "validation_failed",
            "bad_jwt",
            "unexpected_failure",
        }
        return code if isinstance(code, str) and code in known else None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward API keys or JWTs to another origin (or any redirected path).
        return None


class Client:
    def __init__(self, config: Config, label: str):
        self.config = config
        self.label = label
        self.uid = None
        self.token = None
        self.opener = build_opener(NoRedirect(), HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def __repr__(self):
        return f"Client({self.label})"

    def request(self, method, path, *, payload=None, query=None, representation=False):
        url = self.config.url + path
        if query:
            url += "?" + urlencode(query)
        headers = {"apikey": self.config.key, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if representation:
            headers["Prefer"] = "return=representation"
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(url, data=data, headers=headers, method=method)
        try:
            try:
                response = self.opener.open(request, timeout=25)
            except HTTPError as error:
                response = error
            with response:
                status = response.code
                raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise NetworkFailure("Response exceeded the test size limit.")
            try:
                body = json.loads(raw) if raw else None
            except ValueError, UnicodeError:
                body = None
            return Reply(status, body)
        except (URLError, OSError, TimeoutError) as error:
            code = transport_failure_code(error)
            raise NetworkFailure(
                "Network/TLS request failed [" + code + "]; details suppressed."
            ) from None

    def table(self, method, name, *, filters=None, columns=None, payload=None):
        query = dict(filters or {})
        if columns is not None:
            query["select"] = columns
        return self.request(
            method,
            "/rest/v1/" + name,
            query=query,
            payload=payload,
            representation=method != "GET",
        )

    def rpc(self, name, payload):
        return self.request("POST", "/rest/v1/rpc/" + name, payload=payload)


@dataclass
class Report:
    status: str = "NOT_RUN"
    run_id: str = field(default_factory=lambda: "security-test-" + uuid.uuid4().hex)
    checks: list = field(default_factory=list)
    fixtures: dict = field(default_factory=lambda: {"users": {}, "lesson_id": None})
    warnings: list = field(default_factory=list)
    schema_sha256: str | None = None

    def check(self, name, passed, reply=None, *, security=False, required=False):
        row = {"name": name, "result": "PASS" if passed else "FAIL"}
        if reply is not None:
            row["http_status"] = reply.status
            row["sql_or_auth_code"] = reply.code
            if isinstance(reply.body, list):
                row["returned_rows"] = len(reply.body)
                if len(reply.body) == 1 and isinstance(reply.body[0], dict):
                    outcome = reply.body[0].get("outcome")
                    if outcome in ("ok", "invalid_invitation", "rate_limited"):
                        row["rpc_outcome"] = outcome
        if security and not passed:
            row["requires_security_review"] = True
        self.checks.append(row)
        print(f"{row['result']}: {name}" + (f" [HTTP {reply.status}]" if reply else ""))
        if not passed and required:
            raise StopScenario
        return passed

    def as_json(self):
        results = {c["name"]: c["result"] for c in self.checks}
        scenarios = {}
        for name, checks in SCENARIOS.items():
            values = [results.get(check, "NOT_RUN") for check in checks]
            scenarios[name] = (
                "FAIL"
                if "FAIL" in values
                else "PASS"
                if all(value == "PASS" for value in values)
                else "NOT_RUN"
                if all(value == "NOT_RUN" for value in values)
                else "INCOMPLETE"
            )
        return {
            "status": self.status,
            "run_id": self.run_id,
            "checks": self.checks,
            "scenarios": scenarios,
            "fixtures": self.fixtures,
            "warnings": self.warnings,
            "schema_sha256": self.schema_sha256,
            "finished_at": datetime.now(UTC).isoformat(),
            "scope": "Real Auth JWT and PostgREST; no Realtime delivery test or policy changes.",
        }


def read_snapshot(path):
    try:
        if path.stat().st_size > 2_097_152:
            raise ValueError
        raw = path.read_text(encoding="utf-8-sig")
        try:
            value = json.loads(raw)
        except ValueError:
            rows = list(csv.DictReader(io.StringIO(raw)))
            if len(rows) != 1 or "schema_snapshot" not in rows[0]:
                raise ValueError from None
            value = rows[0]
        if isinstance(value, list) and len(value) == 1:
            value = value[0]
        if isinstance(value, dict) and "schema_snapshot" in value:
            value = value["schema_snapshot"]
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict) or value.get("format_version") != 1:
            raise ValueError
        return value
    except OSError, ValueError, TypeError, csv.Error:
        raise SetupError(
            "Export inspect_applied.sql as JSON and set SUPABASE_SCHEMA_FILE."
        ) from None


def verify_contract(config, report):
    snapshot = read_snapshot(config.schema_file)
    migration = (
        Path(__file__).resolve().parents[1] / "migrations/20261117000100_lesson_sessions.sql"
    )
    expected = re.findall(
        r"CREATE FUNCTION (\w+)\.(\w+)\s*\(.*?AS \$function\$(.*?)\$function\$;",
        migration.read_text(),
        re.DOTALL,
    )
    if len(expected) != 6:
        raise SetupError("Cannot derive the six expected function bodies from the migration.")
    functions = snapshot.get("functions")
    if not isinstance(functions, list):
        raise SetupError("Applied schema snapshot does not contain function definitions.")
    for schema, name, body in expected:
        actual = [f for f in functions if f.get("schema") == schema and f.get("name") == name]
        if (
            len(actual) != 1
            or not isinstance(actual[0].get("body"), str)
            or (actual[0]["body"].replace("\r\n", "\n").strip() != body.strip())
        ):
            raise SetupError(
                "Applied RPC/helper definitions differ; inspect the schema before testing."
            )
        if 'search_path=""' not in (actual[0].get("settings") or []):
            raise SetupError("Applied function search_path differs from the reviewed migration.")
    arguments = {
        "create_lesson_session": ["p_title", "p_creator_role", "p_invitation_ttl"],
        "join_lesson_session": ["p_invitation_code"],
    }
    argument_types = {
        "create_lesson_session": "text, text, interval",
        "join_lesson_session": "text",
    }
    for name, names in arguments.items():
        actual = next(f for f in functions if f["schema"] == "public" and f["name"] == name)
        if actual.get("input_args") != names or actual.get("input_types") != argument_types[name]:
            raise SetupError("Applied RPC argument names differ from the reviewed definitions.")
    expected_columns = {
        "lesson_sessions": set(SESSION_COLUMNS.split(",")) | {"invitation_code_hash"},
        "lesson_members": set(MEMBER_COLUMNS.split(",")) | {"joined_at"},
        "lesson_notes": set(NOTE_COLUMNS.split(",")) | {"created_at", "updated_at"},
    }
    for name, names in expected_columns.items():
        matches = [
            t
            for t in snapshot.get("tables", [])
            if t.get("schema") == "public" and t.get("name") == name
        ]
        if len(matches) != 1 or {c["name"] for c in matches[0]["columns"]} != names:
            raise SetupError("Applied table columns differ from the reviewed migration.")
    report.schema_sha256 = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode("utf-8")
    ).hexdigest()
    report.check("applied RPC bodies, arguments and table columns match reviewed migration", True)


def one_row(reply):
    return (
        reply.body[0]
        if isinstance(reply.body, list) and len(reply.body) == 1 and isinstance(reply.body[0], dict)
        else {}
    )


def identifier(value):
    try:
        return str(uuid.UUID(value))
    except ValueError, TypeError, AttributeError:
        raise SetupError(
            "Server returned an invalid fixture identifier; stopping safely."
        ) from None


def denied(reply):
    return reply.status == 403 and reply.code == "42501"


def run_scenario(config, report, actors):
    for label in ("A", "B", "C"):
        actor = Client(config, label)
        actors.append(actor)
        body = {"data": {"englishnotes_security_test": report.run_id, "actor": label}}
        captcha = os.environ.get("SUPABASE_CAPTCHA_TOKEN_" + label)
        if captcha:
            body["gotrue_meta_security"] = {"captcha_token": captcha}
        response = actor.request("POST", "/auth/v1/signup", payload=body)
        value = response.body if isinstance(response.body, dict) else {}
        token = value.get("access_token")
        if response.status not in (200, 201) or not isinstance(token, str) or not token:
            report.check(label + " anonymous sign-in", False, response)
            raise SetupError(
                "Anonymous sign-in blocked: check Auth settings, CAPTCHA or rate limits."
            )
        # Use exactly the access token returned by Auth. Never construct/decode/alter a JWT.
        actor.token = token
        user = value.get("user") or {}
        actor.uid = identifier(user.get("id"))
        report.fixtures["users"][label] = actor.uid
        report.check(
            label + " anonymous sign-in", user.get("is_anonymous") is True, response, required=True
        )
        identity = actor.request("GET", "/auth/v1/user")
        current = identity.body if isinstance(identity.body, dict) else {}
        report.check(
            label + " JWT accepted by Auth for the same anonymous identity",
            identity.status == 200
            and current.get("id") == actor.uid
            and current.get("is_anonymous") is True,
            identity,
            required=True,
        )
    a, b, c = actors
    report.check(
        "three distinct user IDs and Auth-issued access tokens",
        len({a.uid, b.uid, c.uid}) == 3 and len({a.token, b.token, c.token}) == 3,
        required=True,
    )

    created = a.rpc(
        "create_lesson_session",
        {
            "p_title": report.run_id,
            "p_creator_role": "student",
            "p_invitation_ttl": "30 minutes",
        },
    )
    row = one_row(created)
    report.check(
        "A creates a lesson through the actual RPC",
        created.status == 200 and row.get("outcome") == "ok",
        created,
        required=True,
    )
    lesson = identifier(row.get("lesson_id"))
    report.fixtures["lesson_id"] = lesson
    code = row.get("invitation_code")
    if not isinstance(code, str) or re.fullmatch("[0-9a-f]{64}", code) is None:
        raise SetupError("RPC invitation format differs from the inspected definition.")
    filters = {"id": "eq." + lesson}
    own = a.table("GET", "lesson_sessions", filters=filters, columns=SESSION_COLUMNS)
    report.check(
        "A is recorded as the creator",
        own.status == 200 and one_row(own).get("created_by") == a.uid,
        own,
        required=True,
    )

    note_id = str(uuid.uuid4())
    seed_text = report.run_id + " original A note"
    note = a.table(
        "POST",
        "lesson_notes",
        columns=NOTE_COLUMNS,
        payload={
            "id": note_id,
            "lesson_id": lesson,
            "title": "A security fixture",
            "content": seed_text,
            "position": 0,
        },
    )
    report.check(
        "A creates a real canary note before outsider probes",
        note.status == 201
        and one_row(note).get("id") == note_id
        and one_row(note).get("author_id") == a.uid,
        note,
        required=True,
    )
    note_filters = {"id": "eq." + note_id, "lesson_id": "eq." + lesson}

    joined = b.rpc("join_lesson_session", {"p_invitation_code": code})
    report.check(
        "B joins the lesson with its one-time invitation",
        joined.status == 200
        and one_row(joined).get("outcome") == "ok"
        and one_row(joined).get("lesson_id") == lesson,
        joined,
        required=True,
    )
    wrong = secrets.token_hex(32)
    while wrong == code:
        wrong = secrets.token_hex(32)
    refused = c.rpc("join_lesson_session", {"p_invitation_code": wrong})
    report.check(
        "C wrong invitation is rejected without revealing a lesson ID",
        refused.status == 200
        and one_row(refused).get("outcome") == "invalid_invitation"
        and one_row(refused).get("lesson_id") is None,
        refused,
        security=True,
    )
    hidden = c.table("GET", "lesson_sessions", filters=filters, columns=SESSION_COLUMNS)
    report.check(
        "C cannot read A lesson directly",
        hidden.status == 200 and hidden.body == [],
        hidden,
        security=True,
    )
    hidden_notes = c.table(
        "GET", "lesson_notes", filters={"lesson_id": "eq." + lesson}, columns=NOTE_COLUMNS
    )
    report.check(
        "C cannot read existing notes",
        hidden_notes.status == 200 and hidden_notes.body == [],
        hidden_notes,
        security=True,
    )

    foreign_id = str(uuid.uuid4())
    inserted = c.table(
        "POST",
        "lesson_notes",
        columns=NOTE_COLUMNS,
        payload={
            "id": foreign_id,
            "lesson_id": lesson,
            "title": "Forbidden C fixture",
            "content": "blocked",
        },
    )
    report.check("C cannot insert a note into A lesson", denied(inserted), inserted, security=True)
    no_insert = a.table("GET", "lesson_notes", filters={"id": "eq." + foreign_id}, columns="id")
    report.check(
        "C rejected insert left no row",
        no_insert.status == 200 and no_insert.body == [],
        no_insert,
        security=True,
    )

    for name, method, payload in (
        ("C cannot modify A note", "PATCH", {"content": "C tampered with fixture"}),
        ("C cannot soft-delete A note", "PATCH", {"deleted_at": datetime.now(UTC).isoformat()}),
        ("C cannot hard-delete A note", "DELETE", None),
    ):
        reply = c.table(
            method, "lesson_notes", filters=note_filters, columns=NOTE_COLUMNS, payload=payload
        )
        blocked = denied(reply) if method == "DELETE" else reply.status == 200 and reply.body == []
        report.check(name, blocked, reply, security=True)
    unchanged = a.table("GET", "lesson_notes", filters=note_filters, columns=NOTE_COLUMNS)
    row = one_row(unchanged)
    report.check(
        "A canary survives C update/delete attempts unchanged",
        unchanged.status == 200
        and row.get("content") == seed_text
        and row.get("author_id") == a.uid
        and row.get("deleted_at") is None
        and row.get("revision") == 1,
        unchanged,
        security=True,
    )

    member_filter = {"lesson_id": "eq." + lesson, "user_id": "eq." + a.uid}
    for name, method, payload in (
        (
            "C cannot add itself to the roster",
            "POST",
            {"lesson_id": lesson, "user_id": c.uid, "role": "teacher"},
        ),
        ("C cannot change member roles", "PATCH", {"role": "teacher"}),
        ("C cannot remove the creator", "DELETE", None),
    ):
        reply = c.table(
            method,
            "lesson_members",
            filters=None if method == "POST" else member_filter,
            columns=MEMBER_COLUMNS,
            payload=payload,
        )
        report.check(name, denied(reply), reply, security=True)

    second_id = str(uuid.uuid4())
    second_text = report.run_id + " note written by B"
    second = b.table(
        "POST",
        "lesson_notes",
        columns=NOTE_COLUMNS,
        payload={
            "id": second_id,
            "lesson_id": lesson,
            "title": "B security fixture",
            "content": second_text,
            "position": 1,
        },
    )
    report.check(
        "B can add a note with B as its author",
        second.status == 201 and one_row(second).get("author_id") == b.uid,
        second,
    )
    visible = a.table(
        "GET", "lesson_notes", filters={"id": "eq." + second_id}, columns=NOTE_COLUMNS
    )
    report.check(
        "A can read B note",
        visible.status == 200
        and one_row(visible).get("content") == second_text
        and one_row(visible).get("author_id") == b.uid,
        visible,
    )
    shared = a.table(
        "PATCH",
        "lesson_notes",
        filters={"id": "eq." + second_id},
        columns=NOTE_COLUMNS,
        payload={"content": second_text + " shared edit"},
    )
    report.check(
        "A can edit B note without changing B authorship",
        shared.status == 200
        and one_row(shared).get("author_id") == b.uid
        and one_row(shared).get("content") == second_text + " shared edit"
        and one_row(shared).get("revision") == 2,
        shared,
    )
    shared_b = b.table(
        "PATCH",
        "lesson_notes",
        filters=note_filters,
        columns=NOTE_COLUMNS,
        payload={"content": seed_text + " shared B edit"},
    )
    report.check(
        "B can edit A note without becoming its author",
        shared_b.status == 200
        and one_row(shared_b).get("author_id") == a.uid
        and one_row(shared_b).get("content") == seed_text + " shared B edit"
        and one_row(shared_b).get("revision") == 2,
        shared_b,
    )

    takeover = b.table(
        "PATCH",
        "lesson_sessions",
        filters=filters,
        columns=SESSION_COLUMNS,
        payload={"created_by": b.uid},
    )
    report.check("B cannot take ownership of A lesson", denied(takeover), takeover, security=True)
    role_change = b.table(
        "PATCH",
        "lesson_members",
        filters={"lesson_id": "eq." + lesson, "user_id": "eq." + b.uid},
        columns=MEMBER_COLUMNS,
        payload={"role": "student"},
    )
    report.check("B cannot change its role", denied(role_change), role_change, security=True)
    removal = b.table("DELETE", "lesson_members", filters=member_filter, columns=MEMBER_COLUMNS)
    report.check("B cannot remove A membership", denied(removal), removal, security=True)
    owner = b.table("GET", "lesson_sessions", filters=filters, columns=SESSION_COLUMNS)
    report.check(
        "B still sees A as the creator",
        owner.status == 200 and one_row(owner).get("created_by") == a.uid,
        owner,
        security=True,
    )
    roster = a.table(
        "GET", "lesson_members", filters={"lesson_id": "eq." + lesson}, columns=MEMBER_COLUMNS
    )
    expected = {(a.uid, "student"), (b.uid, "teacher")}
    actual = (
        {(m.get("user_id"), m.get("role")) for m in roster.body if isinstance(m, dict)}
        if isinstance(roster.body, list)
        else set()
    )
    report.check(
        "roster remains exactly A/student and B/teacher",
        roster.status == 200 and actual == expected and len(roster.body) == 2,
        roster,
        security=True,
    )
    hash_read = b.table("GET", "lesson_sessions", filters=filters, columns="invitation_code_hash")
    report.check("B cannot read the invitation hash", denied(hash_read), hash_read, security=True)


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Tokens, invitation, key, provider messages and full HTTP bodies are never serialized.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        json.dump(report.as_json(), file, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=Path("work/supabase-live-report.json"))
    args = parser.parse_args(argv)
    report = Report()
    actors = []
    report_write_failed = False
    try:
        config = Config.from_environment()
        verify_contract(config, report)
        report.status = "RUNNING"
        run_scenario(config, report, actors)
        report.status = "FAIL" if any(c["result"] == "FAIL" for c in report.checks) else "PASS"
        if any(value != "PASS" for value in report.as_json()["scenarios"].values()):
            report.status = "FAIL"
    except SetupError as error:
        report.status = "NOT_RUN" if not actors else "BLOCKED"
        report.warnings.append(str(error))
        print(str(error))
    except NetworkFailure as error:
        report.status = "BLOCKED"
        report.warnings.append(str(error))
        print(str(error))
    except StopScenario:
        report.status = "FAIL"
        report.warnings.append("Setup assertion failed; dependent checks were not executed.")
    except Exception:
        report.status = "BLOCKED"
        report.warnings.append(
            "Unexpected runner error; details suppressed to protect credentials."
        )
    finally:
        for actor in actors:
            if actor.token:
                try:
                    reply = actor.request("POST", "/auth/v1/logout", query={"scope": "local"})
                    if reply.status != 204:
                        report.warnings.append(actor.label + " sign-out was not confirmed.")
                except Exception:
                    report.warnings.append(actor.label + " sign-out was not confirmed.")
                actor.token = None
        if report.fixtures["users"]:
            report.warnings.append(
                "Test accounts/lesson/notes remain for inspection. No admin cleanup was attempted."
            )
        try:
            save_report(args.report, report)
        except OSError:
            print("Could not write the report; no credentials were printed.")
            report_write_failed = True
    if report_write_failed:
        return 2
    print("Live Supabase security result: " + report.status)
    print("Unexecuted checks are not passes. See the sanitized JSON report.")
    return 0 if report.status == "PASS" else 1 if report.status == "FAIL" else 2


if __name__ == "__main__":
    sys.exit(main())
