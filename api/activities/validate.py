"""Validate a JSONB attribute payload against the registry.

THIS IS WHERE THE ATTRIBUTE MODEL IS ENFORCED. The database column is plain
jsonb with no constraint, on purpose (see 0001) — a constraint there would have
to be rewritten to add an activity, which is the rework the model exists to
avoid. So the boundary is here, and it must be the only way attributes are
written.

The rules, and why each one is what it is:

  UNKNOWN KEYS ARE DROPPED, not rejected.
      A client one release ahead of the server sends a field this build has
      never heard of. Rejecting the whole write turns a new optional field into
      an outage for older servers; dropping it loses one value. The same
      whitelist-and-clip discipline as VoyageOS's guide sanitize().

  WRONG TYPES ARE REJECTED, loudly, with the field name.
      A silently coerced "" -> 0 is a stack height of zero that nobody typed
      and nobody can explain later.

  NULL CLEARS A FIELD.
      Explicitly passing null removes the key. That is how a user un-sets a
      value; without it, an attribute could be written but never withdrawn.

  RANGES ARE CLAMPED AT THE EDGES OF PLAUSIBILITY, not of possibility.
      max=60mm on stack height is not a claim that 61mm is impossible. It is a
      claim that a 610 came from a typo, and catching it here is cheaper than a
      gear-health engine dividing by it later.
"""
from __future__ import annotations

from fastapi import HTTPException

from api.activities.registry import adventure_fields, gear_fields

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}

#: Per entry in a string_list. Sized for the longest real mandatory-kit line
#: seen in the wild — "Additional Warm Second Layer - A warm second layer top
#: with long sleeves (excluding cotton) weighing at least 180g (men's size M) OR
#: the combination of long-sleeved warm undergarment (excluding cotton)…" from
#: Oman by UTMB, at 230 characters. Generous rather than tight, because the
#: consequence of the limit being wrong is a requirement nobody can read.
STRING_LIST_MAX = 400


def _bad(field: str, why: str) -> HTTPException:
    return HTTPException(422, f"{field}: {why}")


def _coerce(field: str, spec: dict, value):
    kind = spec.get("type", "string")

    if kind in ("string", "text"):
        if not isinstance(value, str):
            raise _bad(field, "expected text")
        v = value.strip()
        return v[:2000] if kind == "text" else v[:200]

    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise _bad(field, "expected a whole number")
        try:
            n = int(float(value))
        except (TypeError, ValueError):
            raise _bad(field, "expected a whole number") from None
        return _bounded(field, spec, n)

    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise _bad(field, "expected a number")
        try:
            n = float(value)
        except (TypeError, ValueError):
            raise _bad(field, "expected a number") from None
        return _bounded(field, spec, round(n, 4))

    if kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value.lower() in _TRUE:
                return True
            if value.lower() in _FALSE:
                return False
        raise _bad(field, "expected true or false")

    if kind == "enum":
        options = spec.get("options") or []
        if value not in options:
            raise _bad(field, f"must be one of {', '.join(map(str, options))}")
        return value

    if kind == "multi_enum":
        if not isinstance(value, list):
            raise _bad(field, "expected a list")
        options = spec.get("options") or []
        out, seen = [], set()
        for item in value:
            if item not in options:
                raise _bad(field, f"'{item}' is not one of {', '.join(map(str, options))}")
            if item not in seen:      # order preserved, duplicates dropped
                seen.add(item)
                out.append(item)
        return out

    if kind == "string_list":
        if not isinstance(value, list):
            raise _bad(field, "expected a list")
        out = []
        for item in value[:100]:
            if not isinstance(item, str):
                raise _bad(field, "expected a list of text")
            s = item.strip()
            # REJECTED, NOT TRUNCATED — the one place this file's own rule about
            # silent coercion had an exception, and mandatory kit is the worst
            # possible field to have it in.
            #
            # This was `item.strip()[:200]`. A kit line imported from Oman by
            # UTMB — "Smartphone - LiveTrail application must be installed and
            # activated with international roaming... Must be reachable at any
            # time before, during and after the race. Keep the pho" — was cut
            # there, stored cut, and shown on the pack as a sentence ending
            # mid-word. Nothing recorded that anything had been dropped.
            #
            # §24 makes this data authoritative and the engine marks every line
            # of it critical. Quietly removing the end of a requirement is how
            # someone arrives at a kit check having packed the first 200
            # characters of it.
            if len(s) > STRING_LIST_MAX:
                raise _bad(field,
                           f"one entry is {len(s)} characters and the limit is "
                           f"{STRING_LIST_MAX}. Shorten it rather than letting "
                           f"it be cut: “{s[:60]}…”")
            if s:
                out.append(s)
        return out

    raise _bad(field, f"unsupported field type {kind!r}")


def _bounded(field: str, spec: dict, n):
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and n < lo:
        raise _bad(field, f"must be at least {lo}")
    if hi is not None and n > hi:
        raise _bad(field, f"must be at most {hi}")
    return n


def _min_max_pairs(fields: dict) -> list[tuple[str, str]]:
    """Field pairs that have to be the right way round, found by name.

    DERIVED, NOT DECLARED. The registry already names these consistently —
    `pe_min`/`pe_max`, `cast_weight_min_g`/`cast_weight_max_g` — so reading the
    convention costs nothing and means the next activity to follow it is
    covered without anyone remembering to add a line here. There are only two
    such pairs today, both on the fishing rod, which is exactly why this is six
    lines of convention rather than a new registry syntax.
    """
    pairs = []
    for name in fields:
        if "_min" not in name:
            continue
        partner = name.replace("_min", "_max", 1)
        if partner != name and partner in fields:
            pairs.append((name, partner))
    return pairs


def _validate(fields: dict, payload: dict | None, *, partial: bool) -> dict:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(422, "attributes must be an object")

    out: dict = {}
    for key, value in payload.items():
        spec = fields.get(key)
        if spec is None:
            continue                     # unknown key — dropped, see docstring
        if value is None:
            continue                     # explicit null clears the field
        out[key] = _coerce(key, spec, value)

    # A PAIR CAN BE BACKWARDS WHILE EVERY FIELD IN IT IS LEGAL. A rod written
    # with pe_min 10 and pe_max 2 passes every check above — both numbers are
    # inside 0.4-20 — and then makes the rod↔line rule produce a confident
    # sentence about gear nobody owns: for any line at all, PE is "heavier than
    # this rod is rated for (to PE2)". A typo in one digit becomes advice.
    #
    # A LIMIT WORTH NAMING: this only fires when both halves are in THIS
    # payload. A PATCH sending pe_min alone cannot be judged here, because
    # _validate never sees the stored record — so tackle.py's rules guard the
    # inverted window again on the way out, which is the check that holds no
    # matter how the data arrived.
    for low, high in _min_max_pairs(fields):
        lo, hi = out.get(low), out.get(high)
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) \
                and lo > hi:
            raise _bad(low, f"is {lo:g} and {high} is {hi:g} — the pair is the "
                            f"wrong way round, so nothing could ever fall "
                            f"inside it")

    # On a PATCH the caller is sending a subset by definition, so a required
    # field absent from the payload is absent from this request — not missing
    # from the record. Only a full write can judge that.
    if not partial:
        for key, spec in fields.items():
            if spec.get("required") and key not in out:
                raise HTTPException(422, f"{key}: required for this activity")
    return out


def validate_gear_attributes(activity_key: str | None, category_key: str | None,
                             payload: dict | None, *, partial: bool = False) -> dict:
    return _validate(gear_fields(activity_key or "", category_key), payload, partial=partial)


def validate_adventure_attributes(activity_key: str, payload: dict | None,
                                  *, partial: bool = False) -> dict:
    return _validate(adventure_fields(activity_key), payload, partial=partial)
