"""Do the three places that name the Supabase project agree?

    .venv/bin/python -m scripts.check_config

WHY THIS EXISTS. The project URL lives in three files — .env for the server,
app/app.json for the client, render.yaml for the deploy — and moving from the
Tokyo project to the Frankfurt one updated two of them. render.yaml kept a
hostname that no longer resolves, which nothing would have caught until a
deploy failed with a DNS error that names no cause.

Three copies of one value is a fact of the setup rather than a mistake: each is
read by a different process, and none can import the others. What was missing
was anything that compares them.

Exits non-zero on a mismatch, so it can go in front of a deploy.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def from_env() -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    m = re.search(r"^SUPABASE_URL=(.+)$", path.read_text(), re.M)
    return m.group(1).strip() if m else None


def from_app_json() -> str | None:
    extra = json.loads((ROOT / "app/app.json").read_text())["expo"]["extra"]
    return extra.get("supabaseUrl") or None


def from_render() -> str | None:
    text = (ROOT / "render.yaml").read_text()
    m = re.search(r"key:\s*SUPABASE_URL\s*\n\s*value:\s*(\S+)", text)
    return m.group(1).strip() if m else None


def main() -> int:
    sources = {
        ".env (server)": from_env(),
        "app/app.json (client)": from_app_json(),
        "render.yaml (deploy)": from_render(),
    }

    for label, value in sources.items():
        print(f"  {label:26} {value or '<missing>'}")

    # .env is gitignored and absent on a fresh clone, which is normal rather
    # than a failure — it is skipped instead of counted as a disagreement.
    present = {k: v for k, v in sources.items() if v}
    distinct = set(present.values())

    print()
    if len(distinct) <= 1:
        print(f"agreed: {distinct.pop() if distinct else '<nothing configured>'}")
        return 0

    print("MISMATCH — these name different Supabase projects:")
    for label, value in present.items():
        print(f"  {label:26} {value}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
