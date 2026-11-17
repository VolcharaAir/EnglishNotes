import time
from dataclasses import dataclass, field

from englishnotes.cloud.transport import CloudError


@dataclass(repr=False)
class Identity:
    uid: str
    access_token: str = field(repr=False)
    expires_at: float


class SessionManager:
    def __init__(self, transport, vault):
        self.transport = transport
        self.vault = vault
        self.identity = None

    def ensure(self):
        if self.identity and self.identity.expires_at > time.time() + 90:
            return self.identity
        stored = self.vault.get("auth")
        if stored:
            if not stored.get("refresh_token") or not stored.get("uid"):
                raise CloudError("credentials_damaged")
            path = "/auth/v1/token?grant_type=refresh_token"
            body = {"refresh_token": stored["refresh_token"]}
        else:
            # Detect a locked/unwritable vault before consuming a signup quota.
            self.vault.put("write-check", {"ready": True})
            self.vault.remove("write-check")
            # The server-side before-user-created hook applies IP/global budgets.
            status = self.transport.rpc("en_status", {}, None)
            if status.get("protocol") != 2:
                raise CloudError("migration_required")
            if not status.get("enabled"):
                raise CloudError("cloud_paused")
            path, body = "/auth/v1/signup", {"data": {"application": "EnglishNotes"}}
        value = self.transport.request(path, body)
        try:
            uid = value["user"]["id"]
            if stored and stored["uid"] != uid:
                raise CloudError("identity_changed")
            refresh, access = value["refresh_token"], value["access_token"]
            if (
                not isinstance(refresh, str)
                or not refresh
                or not isinstance(access, str)
                or not access
            ):
                raise ValueError
            # Persist rotation before allowing any cloud data request.
            self.vault.put("auth", {"uid": uid, "refresh_token": refresh})
            self.identity = Identity(uid, access, time.time() + int(value.get("expires_in", 3600)))
            return self.identity
        except KeyError, TypeError, ValueError:
            raise CloudError("auth_protocol_error") from None

    def invalidate_access(self):
        self.identity = None
