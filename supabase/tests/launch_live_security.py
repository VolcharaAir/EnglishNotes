"""Local convenience launcher: explicit .env -> child process environment, no evaluation."""

import os
from pathlib import Path

from live_security import main

ALLOWED = {
    "SUPABASE_URL",
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_SCHEMA_FILE",
    "SUPABASE_CAPTCHA_TOKEN_A",
    "SUPABASE_CAPTCHA_TOKEN_B",
    "SUPABASE_CAPTCHA_TOKEN_C",
}


def load_environment(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        if name not in ALLOWED:
            continue
        if not separator:
            raise ValueError("Invalid environment assignment.")
        value = value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError("Invalid quoted environment value.")
            value = value[1:-1]
        else:
            # A whitespace-prefixed # starts a comment; no variable interpolation/evaluation.
            value = value.split(" #", 1)[0].rstrip()
        if not os.environ.get(name):
            os.environ[name] = value


def launch():
    root = Path(__file__).resolve().parents[2]
    try:
        load_environment(root / ".env")
    except OSError, ValueError:
        print("Cannot load .env. Check access and simple KEY=value syntax; values were not logged.")
        return 2
    snapshot = root / "work/supabase-applied-schema.json"
    csv_snapshot = snapshot.with_suffix(".csv")
    if not snapshot.exists() and csv_snapshot.exists():
        snapshot = csv_snapshot
    os.environ.setdefault("SUPABASE_SCHEMA_FILE", str(snapshot))
    os.chdir(root)
    return main()


if __name__ == "__main__":
    raise SystemExit(launch())
