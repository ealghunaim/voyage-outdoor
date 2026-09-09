"""Engine output → the text a model reads. Pure; no I/O, no model.

This file is the actual boundary described in §11. Everything above it is
decided; everything below it is prose. Two properties matter and both are
testable without a network:

  * IT IS LOSSLESS ABOUT DECISIONS. Every classification, every warning, every
    number goes across. A summariser that dropped the `missing` lines to save
    tokens would produce a confident narrative about a pack with a hole in it.
  * IT IS A CLOSED WORLD. What is not written here does not exist as far as the
    narrative is concerned, which is what makes "do not invent gear" enforceable
    rather than merely requested.

Being pure also makes it cheap to check: the tests assert on these strings, so
a regression in what the model is told is caught without spending a token.
"""
from __future__ import annotations

import hashlib
import json

#: How many optional lines to name before summarising the rest by count. The
#: optional list is "everything else you own" — for a 60-item locker that is 50
#: lines of noise that push the required items out of the model's attention.
#: The count still goes across, so nothing is hidden, only un-enumerated.
OPTIONAL_SHOWN = 8


def _num(value, unit: str = "") -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


def adventure_line(adv: dict) -> str:
    attrs = adv.get("attributes") or {}
    bits = [f'"{adv.get("title") or "Untitled"}"']
    if adv.get("start_date"):
        bits.append(f'starts {adv["start_date"]}')
    if adv.get("status"):
        bits.append(str(adv["status"]))
    for key, label, unit in (("distance_km", "distance", " km"),
                             ("elevation_gain_m", "climb", " m"),
                             ("expected_hours", "expected", " h"),
                             ("night_hours", "in darkness", " h"),
                             ("max_altitude_m", "max altitude", " m")):
        if attrs.get(key) is not None:
            bits.append(f"{label} {_num(attrs[key], unit)}")
    if attrs.get("terrain"):
        bits.append("terrain " + "/".join(str(t) for t in attrs["terrain"]))
    if attrs.get("self_supported"):
        bits.append("self-supported")
    if attrs.get("race_name"):
        bits.append(f'race: {attrs["race_name"]}')
    return " · ".join(bits)


def weather_block(weather: list[dict]) -> str:
    if not weather:
        # Stated rather than omitted. Silence reads as "no weather worth
        # mentioning"; this reads as "nobody knows yet", which is the truth and
        # changes what the narrative should say.
        return "Forecast: none stored for these dates."
    lines = []
    for day in weather[:10]:
        parts = [str(day.get("forecast_date"))]
        for key, label, unit in (("temp_min", "low", "°C"), ("temp_max", "high", "°C"),
                                 ("precip_prob", "rain", "%"), ("wind_kph", "wind", " kph"),
                                 ("uv", "UV", "")):
            if day.get(key) is not None:
                parts.append(f"{label} {_num(day[key], unit)}")
        lines.append("  " + " · ".join(parts))
    out = ["Forecast:"] + lines
    if len(weather) > 10:
        out.append(f"  (+{len(weather) - 10} more days)")
    return "\n".join(out)


def pack_context(adventure: dict, stored: dict, weather: list[dict]) -> str:
    """Everything the narrative is allowed to know about one pack."""
    readiness = stored.get("readiness") or {}
    items = stored.get("items") or []
    warnings = stored.get("warnings") or []

    by_class: dict[str, list[dict]] = {}
    for item in items:
        by_class.setdefault(item.get("classification") or "optional", []).append(item)

    out = [f"ADVENTURE: {adventure_line(adventure)}", "", weather_block(weather), ""]

    pct = readiness.get("percent")
    out.append(
        "READINESS: "
        + (f"{pct}% of required items packed "
           f"({readiness.get('required_packed', 0)} of "
           f"{readiness.get('required_total', 0)})"
           if pct is not None else "nothing required on this list yet")
    )
    out.append(f"  critical items: {readiness.get('critical_total', 0)}, of which "
               f"{readiness.get('critical_unverified', 0)} not yet verified")
    out.append(f"  missing entirely: {readiness.get('missing_total', 0)}")
    out.append(f"  departure-ready: {'yes' if readiness.get('ready') else 'no'}")
    out.append("")

    # ORDERED BY CONSEQUENCE, not alphabetically. What is missing comes first
    # because it is what ends a race, and what is merely owned comes last.
    for key, heading in (("missing", "MISSING — needed and not in the locker"),
                         ("required", "REQUIRED"),
                         ("recommended", "RECOMMENDED"),
                         ("not_needed", "RULED OUT by a rule"),
                         ("optional", "OPTIONAL — owned, no rule either way")):
        rows = by_class.get(key) or []
        if not rows:
            continue
        out.append(f"{heading} ({len(rows)}):")
        shown = rows[:OPTIONAL_SHOWN] if key == "optional" else rows
        for item in shown:
            flags = []
            if item.get("critical"):
                flags.append("critical")
            if item.get("source") == "mandatory":
                flags.append("race mandatory kit")
            state = item.get("state") or "not_selected"
            if state != "not_selected":
                flags.append(state)
            suffix = f" [{', '.join(flags)}]" if flags else ""
            reason = (item.get("reason") or "").strip()
            out.append(f"  - {item.get('name')}{suffix}"
                       + (f" — {reason}" if reason else ""))
        if len(rows) > len(shown):
            out.append(f"  - (+{len(rows) - len(shown)} more owned items, "
                       f"none of them required)")
        out.append("")

    if warnings:
        out.append(f"WARNINGS ({len(warnings)}), already computed — repeat their "
                   f"substance, do not invent more:")
        for warning in warnings:
            out.append(f"  - [{warning.get('severity')}] {warning.get('message')}")
        out.append("")
    else:
        out.append("WARNINGS: none.")
        out.append("")

    return "\n".join(out).strip()


def locker_context(locker: list[dict], limit: int = 80) -> str:
    """The gear, compactly, with health as the band the engine produced."""
    if not locker:
        return "GEAR LOCKER: empty."
    out = [f"GEAR LOCKER ({len(locker)} active items):"]
    for gear in locker[:limit]:
        bits = [gear.get("name") or "unnamed"]
        if gear.get("category_key"):
            bits.append(str(gear["category_key"]).replace("_", " "))
        if gear.get("brand"):
            bits.append(str(gear["brand"]))
        if gear.get("weight_g") is not None:
            bits.append(f'{gear["weight_g"]} g')
        detail = gear.get("health_detail") or {}
        if detail.get("message"):
            # The engine's own words, band and all. Re-phrasing "640-960 km"
            # into "about 800 km" here would hand the model a point estimate
            # and make §12 impossible to hold further down.
            bits.append(f'condition: {detail["message"]}')
        out.append("  - " + " · ".join(bits))
    if len(locker) > limit:
        out.append(f"  (+{len(locker) - limit} more)")
    return "\n".join(out)


def adventures_context(adventures: list[dict], limit: int = 10) -> str:
    if not adventures:
        return "ADVENTURES: none planned."
    out = [f"ADVENTURES ({len(adventures)}):"]
    for adv in adventures[:limit]:
        out.append("  - " + adventure_line(adv))
    if len(adventures) > limit:
        out.append(f"  (+{len(adventures) - limit} more)")
    return "\n".join(out)


def fingerprint(stored: dict) -> str:
    """What the narrative was written about, in 16 hex characters.

    A packing list is deleted and recreated on regeneration, so its id already
    changes when the engine re-runs. This covers the other case: ticking items
    off does NOT create a new list, and a narrative that opens "you have four
    items left to pack" is wrong the moment the fourth is packed. Storing this
    lets the screen say the paragraph is out of date instead of quietly
    presenting stale prose as current.

    Deliberately narrow — classification, state, criticality and the readiness
    figure. Renaming an item does not invalidate a paragraph that never named
    it, and re-generating on every edit would spend money to change nothing.
    """
    basis = {
        "readiness": stored.get("readiness") or {},
        "items": sorted(
            [(i.get("id"), i.get("classification"), i.get("state"),
              bool(i.get("critical"))) for i in (stored.get("items") or [])],
            key=lambda row: str(row[0]),
        ),
        "warnings": sorted(w.get("key") or "" for w in (stored.get("warnings") or [])),
    }
    blob = json.dumps(basis, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
