"""Push the activity schemas from the Python registry into the database.

WHY THIS EXISTS. `activities.attribute_schema` is a COPY. The registry in
api/activities/registry.py is the original — it is what pydantic validates
against on every write, so it is the only one that can be authoritative. The
copy is there so the schema is visible in the Supabase console and queryable in
SQL, which matters when debugging a row whose attributes look wrong.

Run it after any registry edit, and after 0002:

    .venv/bin/python -m scripts.seed_reference

Idempotent. Prints what changed and nothing else.
"""
from __future__ import annotations

import json
import sys

from api.activities.registry import ACTIVITIES, BUILT
from api.core.db import get_db


def main() -> int:
    db = get_db()
    rows = db.table("activities").select("key,name,built,attribute_schema").execute().data
    by_key = {r["key"]: r for r in rows}

    if not by_key:
        print("No activity rows. Run supabase/migrations/0002_seed_reference.sql first.")
        return 1

    changed = 0
    for key, schema in ACTIVITIES.items():
        row = by_key.get(key)
        if row is None:
            # The migration seeds the rows; the registry does not create them.
            # A registry entry with no row means the two have drifted, and
            # inventing the row here would hide that rather than report it.
            print(f"  ! {key}: in the registry but not in the database — "
                  f"add it to a migration")
            continue
        want_built = key in BUILT
        if row.get("attribute_schema") == schema and row.get("built") == want_built:
            continue
        db.table("activities").update(
            {"attribute_schema": schema, "built": want_built}
        ).eq("key", key).execute()
        fields = sum(len(v) for v in schema.get("gear", {}).values()) \
            + len(schema.get("adventure", {}))
        print(f"  ✓ {key}: {fields} fields, built={want_built}")
        changed += 1

    orphans = set(by_key) - set(ACTIVITIES)
    for key in sorted(orphans):
        print(f"  ! {key}: in the database but not in the registry")

    print(f"{changed} updated, {len(ACTIVITIES) - changed} already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
