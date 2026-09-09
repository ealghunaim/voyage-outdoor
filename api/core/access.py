"""The one place ownership is decided.

VoyageOS answered this question in fifteen routes before it was pulled into one
function, and the fifteen agreed only by coincidence. Starting with the seam
costs nothing now and is the difference between adding sharing in Phase 7 and
auditing every route for it.

WHY 404 AND NOT 403, for a row that exists but is not yours: a 403 confirms the
row exists, which turns any endpoint into an oracle for other people's ids. The
two cases stay indistinguishable from outside.

V1 IS SINGLE-PLAYER. There is no membership table and no role — `user_id` on
the row is the whole rule. The signature below still takes the shape sharing
would need (a scope, a writing flag) so that when Phase 7 adds roles, this file
changes and the call sites do not.
"""
from __future__ import annotations

import re

from fastapi import HTTPException

#: What a write is trying to do. Unused while V1 is single-player; present so
#: the vocabulary exists before there are forty call sites to retrofit.
PLAN = "plan"          # changes what the adventure WILL BE
RECORD = "record"      # writes down what happened — usage, maintenance, reviews
LIFECYCLE = "lifecycle"  # the row's existence: delete, archive

NOT_FOUND = {"gear_items": "Gear not found",
             "adventures": "Adventure not found"}


#: uuid, in the only shape Postgres accepts for a uuid column.
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _owned(db, table: str, row_id: str, user_id: str) -> dict:
    # A MALFORMED ID IS A 404, NOT A 500.
    #
    # Postgres refuses a non-uuid on a uuid column with "invalid input syntax
    # for type uuid", supabase-py raises, and without this the error escapes as
    # a 500 carrying the database's own wording. Wrong twice over: the caller
    # asked for something that does not exist, which is a 404, and a 500 says
    # the server broke when it did not.
    #
    # Checked in the client rather than caught from the database, because
    # catching it would mean a round trip to learn something a regex knows.
    if not _UUID.match(row_id or ""):
        raise HTTPException(404, NOT_FOUND.get(table, "Not found"))
    rows = (db.table(table).select("*")
            .eq("id", row_id).eq("user_id", user_id).limit(1).execute().data)
    if not rows:
        raise HTTPException(404, NOT_FOUND.get(table, "Not found"))
    return rows[0]


def owned_gear(db, gear_id: str, user_id: str, *,
               writing: bool = False, scope: str = PLAN) -> dict:
    """The caller's gear item, or 404. `writing`/`scope` are accepted and not
    yet consulted — see the module docstring."""
    return _owned(db, "gear_items", gear_id, user_id)


def owned_adventure(db, adventure_id: str, user_id: str, *,
                    writing: bool = False, scope: str = PLAN) -> dict:
    return _owned(db, "adventures", adventure_id, user_id)


def owned_gear_child(db, table: str, row_id: str, user_id: str) -> dict:
    """A usage or maintenance row, reached through the gear item that owns it.

    Two queries rather than a join, deliberately: PostgREST's embedded filters
    would express this as one request, but the failure mode when the embed
    returns nothing is a 200 with an empty list, and the caller then has to
    decide whether that meant "no such row" or "not yours". Two explicit reads
    give one 404 for both, which is the answer this file exists to give.
    """
    if not _UUID.match(row_id or ""):
        raise HTTPException(404, "Not found")
    rows = db.table(table).select("*").eq("id", row_id).limit(1).execute().data
    if not rows:
        raise HTTPException(404, "Not found")
    owned_gear(db, rows[0]["gear_item_id"], user_id)
    return rows[0]
