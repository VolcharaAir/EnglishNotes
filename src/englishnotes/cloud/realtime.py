import json
import logging
import socket
import ssl
import threading
from urllib.parse import urlencode, urlsplit, urlunsplit

import websocket


class RealtimeHints:
    """Private Phoenix Broadcast hints. All note data is fetched through metered RPC."""

    def __init__(self, config, wake):
        self.config = config
        self.wake = wake
        self.socket = None
        self.connected = False
        self.rejected = False
        self.signature = None
        self.stop_event = threading.Event()
        self.thread = None
        self._diagnostic = self._new_diagnostic()

    @staticmethod
    def _new_diagnostic():
        # Only fixed labels and integers: never URLs, tokens, frames or raw errors.
        return dict(
            phase="idle",
            error=None,
            http_status=None,
            close_code=None,
            joins_sent=0,
            joins_ok=0,
            joins_rejected=0,
            messages_received=0,
        )

    def diagnostics(self):
        return dict(self._diagnostic)

    @staticmethod
    def _reason_code(payload):
        response = payload.get("response", {})
        if isinstance(response, dict):
            reason = response.get("reason", response.get("message", ""))
        else:
            reason = response
        text = str(reason).lower()
        for words, code in (
            (("permission denied",), "database_permission_denied"),
            (("rls", "policy", "policies"), "rls_authorization_error"),
            (("jwt", "token", "expired"), "jwt_rejected"),
            (("not authorized", "unauthorized", "not allowed"), "authorization_denied"),
            (("too many", "rate", "limit"), "realtime_limit"),
            (("tenant",), "tenant_error"),
        ):
            if any(word in text for word in words):
                return code
        return "join_rejected"

    def configure(self, token, sessions):
        signature = (token, tuple(sorted(sessions)))
        if self.signature == signature and self.thread and self.thread.is_alive():
            return
        self.close()
        self.rejected = False
        self._diagnostic = self._new_diagnostic()
        self.signature = signature
        if not sessions:
            return
        self.stop_event = threading.Event()
        stopping = self.stop_event
        diagnostic = self._diagnostic
        diagnostic["phase"] = "connecting"
        accepted = set()
        join_refs = {str(index) for index in range(1, len(sessions) + 1)}
        origin = urlsplit(self.config.url)
        url = urlunsplit(
            (
                "wss",
                origin.netloc,
                "/realtime/v1/websocket",
                urlencode({"apikey": self.config.key, "vsn": "1.0.0"}),
                "",
            )
        )

        def opened(ws):
            if self.stop_event is not stopping or stopping.is_set():
                return
            diagnostic["phase"] = "joining"
            for index, session in enumerate(sorted(sessions), 1):
                ws.send(
                    json.dumps(
                        {
                            "topic": "realtime:lesson:" + session,
                            "event": "phx_join",
                            "ref": str(index),
                            "join_ref": str(index),
                            "payload": {
                                "config": {
                                    "private": True,
                                    "broadcast": {"ack": False, "self": False},
                                    "presence": {"enabled": False},
                                    "postgres_changes": [],
                                },
                                "access_token": token,
                            },
                        }
                    )
                )
                diagnostic["joins_sent"] += 1

            def heartbeat():
                count = 1000
                while not stopping.wait(20):
                    try:
                        count += 1
                        ws.send(
                            json.dumps(
                                {
                                    "topic": "phoenix",
                                    "event": "heartbeat",
                                    "payload": {},
                                    "ref": str(count),
                                }
                            )
                        )
                    except Exception:
                        break

            threading.Thread(target=heartbeat, daemon=True).start()

        def message(ws, raw):
            if self.stop_event is not stopping or stopping.is_set():
                return
            diagnostic["messages_received"] += 1
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    return
                payload = value.get("payload", {})
                if not isinstance(payload, dict):
                    return
                if (
                    value.get("event") == "phx_reply"
                    and value.get("ref") in join_refs
                    and payload.get("status") == "error"
                ):
                    self.rejected = True
                    self.connected = False
                    diagnostic["phase"] = "join_rejected"
                    diagnostic["joins_rejected"] += 1
                    diagnostic["error"] = self._reason_code(payload)
                if (
                    value.get("event") == "phx_reply"
                    and value.get("ref") in join_refs
                    and payload.get("status") == "ok"
                ):
                    accepted.add(value["ref"])
                    self.connected = accepted == join_refs and not self.rejected
                    diagnostic["joins_ok"] = len(accepted)
                    if self.connected:
                        diagnostic["phase"] = "authorized"
                if value.get("event") in ("phx_error", "phx_close"):
                    self.connected = False
                    diagnostic["phase"] = "channel_closed"
                    diagnostic["error"] = "channel_closed"
                    ws.close()
                if value.get("event") in ("broadcast", "system"):
                    self.wake()
            except ValueError, TypeError:
                pass

        def error(ws, exception):
            if self.stop_event is not stopping or stopping.is_set():
                return
            self.connected = False
            diagnostic["phase"] = "transport_error"
            status = getattr(exception, "status_code", None)
            if isinstance(status, int) and 100 <= status <= 599:
                diagnostic["http_status"] = status
                code = "http_handshake_failed"
            elif isinstance(exception, socket.gaierror):
                code = "dns_lookup_failed"
            elif isinstance(exception, ssl.SSLError):
                code = "tls_failed"
            elif isinstance(exception, (TimeoutError, websocket.WebSocketTimeoutException)):
                code = "connection_timeout"
            elif isinstance(exception, ConnectionRefusedError):
                code = "connection_refused"
            else:
                code = "websocket_error"
            diagnostic["error"] = code
            self.wake()

        def closed(ws, code=None, reason=None):
            if self.stop_event is not stopping:
                return
            self.connected = False
            if isinstance(code, int):
                diagnostic["close_code"] = code
            if not diagnostic["error"]:
                diagnostic["phase"] = "closed"
            stopping.set()
            self.wake()

        websocket.enableTrace(False)
        # websocket-client otherwise propagates raw handshake bodies to root loggers.
        logging.getLogger("websocket").disabled = True
        self.socket = websocket.WebSocketApp(
            url, on_open=opened, on_message=message, on_close=closed, on_error=error
        )
        self.thread = threading.Thread(target=self.socket.run_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if not self._diagnostic["error"]:
            self._diagnostic["phase"] = "closed"
        if self.socket:
            self.socket.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.connected = False
        self.signature = None
