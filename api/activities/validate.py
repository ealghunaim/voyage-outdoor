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
            s = item.strip()[:200]
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
