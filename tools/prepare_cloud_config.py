"""Embed only public Supabase settings; never load arbitrary .env or privileged keys."""

import argparse
import json
from pathlib import Path

from englishnotes.cloud.config import CloudConfig


def prepare(destination, local=False):
    config = None if local else CloudConfig.load()
    if config is None and not local:
        raise ValueError("Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY, or choose --local.")
    value = dict(
        supabase_url=config.url if config else "", publishable_key=config.key if config else ""
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true", help="Explicitly build a local-only app")
    args = parser.parse_args()
    try:
        prepare(Path(__file__).resolve().parents[1] / "work" / "bundle" / "cloud.json", args.local)
    except ValueError, OSError:
        raise SystemExit("Public cloud configuration invalid/missing; no values printed.") from None
    print("Public build configuration prepared (values hidden).")
