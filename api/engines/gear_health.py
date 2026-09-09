"""Gear health — deterministic thresholds over logged usage (§12).

NO MODEL IS IN THIS FILE'S DECISION PATH. It is pure: dictionaries in, a
dataclass out, no I/O, no clock beyond what the caller passes. The AI layer in
Phase 4 may take a HealthResult and write a sentence about it; it may never
produce one.

THE HONESTY RULE, and why it shapes the output type
---------------------------------------------------
§12: "Never present uncertain estimates as guaranteed failure points."

Shoe lifespan is genuinely uncertain. 500–800 km is the number everyone
repeats, and it varies by foam compound, runner mass, terrain and how wet the
shoe has been. A single figure — "82% condition" or "180 km remaining" —
states a precision nobody has, and someone deciding whether to run 160 km of
technical Omani limestone on those shoes deserves better than a number that
looks measured and is not.

So the engine emits three things and never a fourth:

  a BAND     the expected range, not a point (560–840 km, not 700 km)
  a STATE    ok / inspect / past_expected / unknown — a prompt, not a verdict
  the FACTS  distance used, the band, the source of the band

`condition_pct` still exists because a list of forty items needs something
sortable, and it is documented at its column as derived. It is deliberately
NOT the headline: the state and the band are what a screen shows.

UNKNOWN IS A REAL ANSWER and the most important one. Gear with no expected
lifespan, or in a category that does not accumulate distance, returns `unknown`
with a note saying what is missing. It never falls back to a default that
someone would then read as a measurement.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.activities.registry import USAGE_DISTANCE, usage_for

HEALTH_RULESET = "health-v1"

#: Expected lifespan in kilometres, by category, when the item does not carry
#: its own `lifespan_km`. Conservative and few on purpose — a default invented
#: for a category nobody has measured is a guess wearing a threshold's clothes,
#: so most categories are simply absent and return `unknown`.
#:
#: Shoes: 700 km is the middle of the range every manufacturer and coach
#: quotes. It is a starting point to be overridden per pair, not a fact.
DEFAULT_LIFESPAN_KM: dict[str, int] = {
    "shoes": 700,
}

#: How wide the band around an expected lifespan is, either side. ±20% turns
#: 700 into 560–840, which is roughly the spread the 500–800 folklore
#: describes and is honest about the fact that the midpoint is not special.
BAND = 0.20

#: Fraction of the LOWER band edge at which inspection is worth prompting.
#: Measured against the low edge rather than the midpoint deliberately: the
#: point of a band is that the early end is as plausible as the late one, and
#: a prompt that waits for the midpoint has already passed the case it exists
#: to catch.
INSPECT_AT = 0.75

STATE_OK = "ok"
STATE_INSPECT = "inspect"
STATE_PAST = "past_expected"
STATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class HealthResult:
    state: str
    #: 0–100, derived from distance against the band's midpoint. None when
    #: unknown — NOT zero, which would render as "worn out" for a brand new
    #: item whose lifespan nobody has recorded.
    condition_pct: int | None
    #: One sentence, written by this module. Never asserts failure.
    message: str
    ruleset: str = HEALTH_RULESET
    detail: dict = field(default_factory=dict)

    @property
    def needs_attention(self) -> bool:
        return self.state in (STATE_INSPECT, STATE_PAST)


def _km(metres: int | None) -> float:
    return round((metres or 0) / 1000, 1)


def expected_band(item: dict) -> tuple[int, int, str] | None:
    """(low, high, source) in km, or None when there is nothing to judge against.

    An item's own `lifespan_km` wins over the category default, because the
    owner knows which foam they bought and this module does not.
    """
    attributes = item.get("attributes") or {}
    stated = attributes.get("lifespan_km")
    if isinstance(stated, (int, float)) and stated > 0:
        mid, source = float(stated), "item"
    else:
        default = DEFAULT_LIFESPAN_KM.get(item.get("category_key") or "")
        if not default:
            return None
        mid, source = float(default), "category_default"
    return (int(round(mid * (1 - BAND))), int(round(mid * (1 + BAND))), source)


def evaluate(item: dict, totals: dict) -> HealthResult:
    """Health for one gear item.

    `item`   a gear_items row — category_key, attributes, status
    `totals` its usage rollup — distance_m, sessions
    """
    category = item.get("category_key")

    # Retired or lost gear is not a health question. Reporting "inspect the
    # outsole" on a pair the owner has already thrown out is noise that makes
    # every other warning easier to ignore.
    if item.get("status") not in (None, "active"):
        return HealthResult(
            STATE_UNKNOWN, None,
            f"Not tracked while {item.get('status')}.",
            detail={"reason": "not_active", "status": item.get("status")})

    if usage_for(category) != USAGE_DISTANCE:
        return HealthResult(
            STATE_UNKNOWN, None,
            "This category is not measured by distance.",
            detail={"reason": "not_distance_tracked", "category": category})

    band = expected_band(item)
    if band is None:
        return HealthResult(
            STATE_UNKNOWN, None,
            "No expected lifespan recorded, so wear cannot be judged. "
            "Add one to track it.",
            detail={"reason": "no_lifespan", "category": category})

    low, high, source = band
    used = _km(totals.get("distance_m"))
    mid = (low + high) / 2
    pct = max(0, min(100, int(round(100 * (1 - used / mid)))))

    detail = {"used_km": used, "band_low_km": low, "band_high_km": high,
              "band_source": source, "sessions": totals.get("sessions", 0)}

    if used >= high:
        return HealthResult(
            STATE_PAST, pct,
            f"{used:g} km recorded, past the {low}–{high} km range this pair "
            f"was expected to last. Inspect the outsole and midsole, and plan "
            f"a replacement.",
            detail=detail)

    if used >= low * INSPECT_AT:
        return HealthResult(
            STATE_INSPECT, pct,
            f"{used:g} km recorded against an expected {low}–{high} km. "
            f"Inspect the outsole and midsole before a long day out.",
            detail=detail)

    return HealthResult(
        STATE_OK, pct,
        f"{used:g} km recorded, well inside the expected {low}–{high} km.",
        detail=detail)
