import hashlib
import json
import os
from dataclasses import dataclass
from importlib.resources import files
from urllib.parse import urlsplit

from englishnotes import resources


@dataclass(frozen=True, repr=False)
class CloudConfig:
    url: str
    key: str

    @classmethod
    def load(cls):
        if os.environ.get("ENGLISHNOTES_DISABLE_CLOUD") == "1":
            return None
        value = json.loads(files(resources).joinpath("cloud.json").read_text())
        url = os.environ.get("SUPABASE_URL", value.get("supabase_url", "")).rstrip("/")
        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", value.get("publishable_key", ""))
        if not url and not key:
            return None
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.path
            or parts.query
            or parts.fragment
            or parts.username
            or parts.password
            or not key.startswith("sb_publishable_")
            or any(c.isspace() for c in key)
        ):
            raise ValueError("Некорректная публичная конфигурация облака.")
        return cls(url, key)

    def credential_service(self, profile):
        digest = hashlib.sha256((self.url + "\n" + str(profile.resolve())).encode()).hexdigest()
        return "EnglishNotes/" + digest
