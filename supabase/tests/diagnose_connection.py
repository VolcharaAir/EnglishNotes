"""One read-only Auth settings request, no users/JWTs/fixtures or raw error output."""

import os
from pathlib import Path
from urllib.request import getproxies

from launch_live_security import load_environment
from live_security import Client, Config, NetworkFailure, SetupError


def main():
    root = Path(__file__).resolve().parents[2]
    try:
        load_environment(root / ".env")
        os.environ.setdefault(
            "SUPABASE_SCHEMA_FILE", str(root / "work/supabase-applied-schema.json")
        )
        config = Config.from_environment()
        print("CONFIG_FORMAT_OK (values hidden)")
        proxies = getproxies()
        print("HTTPS_PROXY_CONFIGURED=" + str(bool(proxies.get("https") or proxies.get("all"))))
        print(
            "CUSTOM_CA_CONFIGURED="
            + str(bool(os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR")))
        )
        reply = Client(config, "read-only connection check").request("GET", "/auth/v1/settings")
        print("HTTP_RESPONSE=" + str(reply.status))
        if reply.code:
            print("AUTH_CODE=" + reply.code)
        print("No users created. No JWTs requested. No database writes.")
        return 0 if reply.status == 200 else 2
    except SetupError as error:
        print(str(error))
    except NetworkFailure as error:
        print(str(error))
    except OSError, ValueError:
        print("LOCAL_CONFIGURATION_ERROR (details hidden)")
    except Exception:
        print("DIAGNOSTIC_ERROR (details hidden)")
    print("No users created. No JWTs requested. No database writes.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
