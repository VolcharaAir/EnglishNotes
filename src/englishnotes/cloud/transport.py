import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class CloudError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SupabaseHTTP:
    def __init__(self, config):
        self.config = config
        self.opener = build_opener(NoRedirect())

    def request(self, path, body, token=None):
        headers = {"apikey": self.config.key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(
            self.config.url + path, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with self.opener.open(req, timeout=8) as response:
                raw = response.read(16_777_217)
            if len(raw) > 16_777_216:
                raise CloudError("response_limit")
            return json.loads(raw)
        except HTTPError as error:
            # Do not log URLs, headers, provider messages or bodies.
            if error.code == 401:
                raise CloudError("unauthorized") from None
            if error.code == 429:
                raise CloudError("rate_limited") from None
            if error.code == 400 and path.startswith("/auth/"):
                raise CloudError("auth_rejected") from None
            raise CloudError("server_unavailable") from None
        except URLError, OSError, ValueError:
            raise CloudError("offline") from None

    def rpc(self, name, payload, token):
        value = self.request("/rest/v1/rpc/" + name, payload, token)
        if not isinstance(value, dict):
            raise CloudError("protocol_error")
        return value
