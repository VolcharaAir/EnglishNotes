import json
import socket
import ssl
import threading

import pytest
import websocket

from englishnotes.cloud.config import CloudConfig
from englishnotes.cloud.realtime import RealtimeHints


@pytest.fixture
def connection(monkeypatch):
    import englishnotes.cloud.realtime as realtime

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
    hints = RealtimeHints(CloudConfig("https://example.com", "sb_publishable_dummy"), lambda: None)
    hints.configure("private-dummy-token", ["s1"])
    yield hints, hints.socket
    hints.close()


def test_join_has_mandatory_phoenix_reference(connection):
    hints, ws = connection
    ws.callbacks["on_open"](ws)
    frame = ws.sent[0]
    assert frame["join_ref"] == frame["ref"] == "1"
    assert frame["payload"]["config"]["private"] is True
    assert hints.diagnostics()["phase"] == "joining"
    ws.callbacks["on_message"](
        ws, json.dumps(dict(event="phx_reply", ref="1", join_ref="1", payload=dict(status="ok")))
    )
    assert hints.connected
    assert hints.diagnostics()["phase"] == "authorized"
    assert hints.diagnostics()["joins_ok"] == 1


def test_http_error_diagnostic_never_contains_headers_url_or_token(connection, caplog):
    hints, ws = connection
    secret = "private-dummy-token-never-print"
    exception = websocket.WebSocketBadStatusException(
        secret, status_code=403, resp_headers={"Authorization": secret}, resp_body=secret
    )
    ws.callbacks["on_error"](ws, exception)
    ws.callbacks["on_close"](ws, 1008, secret)
    diagnostic = hints.diagnostics()
    assert diagnostic["error"] == "http_handshake_failed"
    assert diagnostic["http_status"] == 403
    assert diagnostic["close_code"] == 1008
    assert secret not in json.dumps(diagnostic)
    import logging

    logging.getLogger("websocket").error(secret)
    assert secret not in caplog.text


@pytest.mark.parametrize(
    "error,code",
    [
        (socket.gaierror("private-host-never-print"), "dns_lookup_failed"),
        (ssl.SSLError("private-cert-never-print"), "tls_failed"),
        (TimeoutError("private-url-never-print"), "connection_timeout"),
        (ConnectionRefusedError("private-endpoint-never-print"), "connection_refused"),
        (OSError("private-error-never-print"), "websocket_error"),
    ],
)
def test_transport_errors_are_fixed_labels(connection, error, code):
    hints, ws = connection
    ws.callbacks["on_error"](ws, error)
    assert hints.diagnostics()["error"] == code
    assert "never-print" not in json.dumps(hints.diagnostics())


def test_join_rejection_reports_category_only(connection):
    hints, ws = connection
    ws.callbacks["on_message"](
        ws,
        json.dumps(
            dict(
                event="phx_reply",
                ref="1",
                payload=dict(
                    status="error", response=dict(reason="RLS policy: private-token-never-print")
                ),
            )
        ),
    )
    assert hints.rejected and not hints.connected
    assert hints.diagnostics()["error"] == "rls_authorization_error"
    assert "never-print" not in json.dumps(hints.diagnostics())


def test_stale_connection_callback_cannot_disconnect_new_subscription(connection):
    hints, old = connection
    hints.configure("rotated-dummy-token", ["s1"])
    current = hints.socket
    current.callbacks["on_message"](
        current, json.dumps(dict(event="phx_reply", ref="1", payload=dict(status="ok")))
    )
    old.callbacks["on_close"](old, 1008, "never-print")
    old.callbacks["on_error"](old, OSError("never-print"))
    assert hints.connected
    assert hints.diagnostics()["phase"] == "authorized"


def test_actual_websocket_transport_uses_valid_join_frame(monkeypatch):
    """Local protocol fixture, not a live Supabase/JWT authorization check."""
    import base64
    import hashlib
    import socketserver
    import struct
    import time

    import englishnotes.cloud.realtime as realtime

    frames, failures = [], []
    finished = threading.Event()

    def receive_exact(sock, count):
        result = b""
        while len(result) < count:
            part = sock.recv(count - len(result))
            if not part:
                raise EOFError
            result += part
        return result

    def frame(sock):
        first, second = receive_exact(sock, 2)
        length = second & 127
        if length == 126:
            length = struct.unpack("!H", receive_exact(sock, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", receive_exact(sock, 8))[0]
        assert second & 128 and length < 4096
        mask = receive_exact(sock, 4)
        payload = receive_exact(sock, length)
        return first & 15, bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                self.request.settimeout(5)
                headers = b""
                while b"\r\n\r\n" not in headers:
                    headers += self.request.recv(1024)
                key = next(
                    line.split(b":", 1)[1].strip()
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"sec-websocket-key:")
                )
                accept = base64.b64encode(
                    hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
                )
                self.request.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                    b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
                )
                opcode, raw = frame(self.request)
                assert opcode == 1
                message = json.loads(raw)
                assert message["event"] == "phx_join"
                assert message["join_ref"] == message["ref"]
                assert message["payload"]["config"]["private"] is True
                frames.append(message)
                reply = json.dumps(
                    dict(
                        event="phx_reply",
                        topic=message["topic"],
                        ref=message["ref"],
                        join_ref=message["join_ref"],
                        payload=dict(status="ok", response={}),
                    )
                ).encode()
                header = (
                    bytes([129, len(reply)])
                    if len(reply) < 126
                    else struct.pack("!BBH", 129, 126, len(reply))
                )
                self.request.sendall(header + reply)
                opcode, raw = frame(self.request)
                assert opcode == 8
                self.request.sendall(b"\x88\x02\x03\xe8")
            except Exception as error:
                failures.append(type(error).__name__)
            finally:
                finished.set()

    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    app = websocket.WebSocketApp
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        local = "ws://127.0.0.1:" + str(server.server_address[1]) + "/websocket"
        monkeypatch.setattr(
            realtime.websocket, "WebSocketApp", lambda url, **kwargs: app(local, **kwargs)
        )
        hints = RealtimeHints(
            CloudConfig("https://example.com", "sb_publishable_dummy"), lambda: None
        )
        try:
            hints.configure("private-dummy-token", ["s1"])
            deadline = time.monotonic() + 4
            while not hints.connected and time.monotonic() < deadline:
                finished.wait(0.01)
            assert hints.connected, hints.diagnostics()
            assert len(frames) == 1
        finally:
            hints.close()
            server.shutdown()
            thread.join(2)
        assert not failures
