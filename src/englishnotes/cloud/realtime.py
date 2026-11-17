import json
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

    def configure(self, token, sessions):
        signature = (token, tuple(sorted(sessions)))
        if self.signature == signature and self.thread and self.thread.is_alive():
            return
        self.close()
        self.rejected = False
        self.signature = signature
        if not sessions:
            return
        self.stop_event = threading.Event()
        stopping = self.stop_event
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
            for index, session in enumerate(sorted(sessions), 1):
                ws.send(
                    json.dumps(
                        {
                            "topic": "realtime:lesson:" + session,
                            "event": "phx_join",
                            "ref": str(index),
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
                if (
                    value.get("event") == "phx_reply"
                    and value.get("ref") in join_refs
                    and payload.get("status") == "ok"
                ):
                    accepted.add(value["ref"])
                    self.connected = accepted == join_refs
                if value.get("event") in ("broadcast", "system"):
                    self.wake()
            except ValueError, TypeError:
                pass

        def closed(*args):
            self.connected = False
            stopping.set()
            self.wake()

        websocket.enableTrace(False)
        self.socket = websocket.WebSocketApp(
            url, on_open=opened, on_message=message, on_close=closed, on_error=lambda *args: None
        )
        self.thread = threading.Thread(target=self.socket.run_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.socket:
            self.socket.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
        self.connected = False
        self.signature = None
