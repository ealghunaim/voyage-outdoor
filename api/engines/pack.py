"""Smart Pack classification — deterministic rules (§8, §0.5).

Pure. Adventure, locker, forecast and the other engines' output go in; a list
of classified lines and a list of warnings come out. Nothing here calls a
model, and the Phase 4 AI layer writes the narrative wrapper — "YOUR PACK
READINESS 87%…" — over exactly this structure without changing a single
classification.

FIVE CLASSIFICATIONS (§8)
    required      you must have this — race rules, or darkness, or distance
    recommended   the conditions argue for it
    optional      you own it and it is plausible; your call
    not_needed    a rule actively says this one can stay home
    missing       required or recommended, and nothing in the locker fits

MISSING IS THE POINT. A pack list assembled only from what you own cannot tell
you what you lack, and the thing that ends a race at a kit check is the item
that was never in the locker to begin with.

AND IT IS NOT A SHOP (§8, §14). A missing line says what is absent and why it
is needed. It does not say "buy" anything, and the engine has no notion of a
product to sell.

MANDATORY KIT OUTRANKS EVERY RULE IN THIS FILE (§24). It is authoritative
external data typed in from a race manual. No rule here may downgrade it, and a
kit line the matcher cannot place stays on the list as unmatched rather than
being dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.engines import compatibility, matching
from api.engines.gear_health import HealthResult

PACK_RULESET = "pack-v1"

REQUIRED = "required"
RECOMMENDED = "recommended"
OPTIONAL = "optional"
NOT_NEEDED = "not_needed"
MISSING = "missing"

#: Higher wins when two rules speak about the same category. Mandatory kit is
#: applied before any of this and is never overwritten.
RANK = {MISSING: 4, REQUIRED: 3, RECOMMENDED: 2, OPTIONAL: 1, NOT_NEEDED: 0}

# ── thresholds, all named and all here ──────────────────────────────────────
# The product spec as data. Every one of these is a number someone can argue
# with, which is the advantage of it being a constant rather than a literal
# buried in a branch.

RAIN_PROB_PCT = 60        # a forecast at or above this argues for a shell
COLD_TEMP_C = 5           # at or below this, hands and head lose function
HOT_TEMP_C = 30           # at or above this, sun and salt become the problem
HIGH_UV = 8
WIND_KPH = 40             # at or above this, a windproof stops being optional
HYDRATION_HOURS = 2       # beyond this you are carrying water, not sipping
NUTRITION_HOURS = 3       # beyond this you are eating
POLES_GAIN_M = 1500       # sustained climbing where poles pay for their weight
ALTITUDE_M = 2500         # where thinner air changes the day


@dataclass(frozen=True)
class PackLine:
    name: str
    classification: str
    rule_key: str
    reason: str
    category_key: str | None = None
    gear_item_id: str | None = None
    critical: bool = False
    source: str = "rule"          # rule · mandatory
    qty: int = 1


@dataclass(frozen=True)
class PackWarning:
    key: str
    severity: str                  # note · caution · critical
    message: str
    rule_key: str
    gear_item_id: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class PackResult:
    lines: list[PackLine]
    warnings: list[PackWarning]
    snapshot: dict
    ruleset: str = PACK_RULESET


# ── the forecast, reduced to the numbers the rules ask about ────────────────

def summarise_weather(days: list[dict]) -> dict:
    """Extremes across the adventure's days.

    NULLS ARE SKIPPED, NEVER TREATED AS ZERO. MET Norway carries no
    precipitation probability at all, and reading its absence as 0% would tell
    someone it will not rain because the provider had no opinion. A rule with
    no number simply does not fire.
    """
    def extreme(key, fn):
        values = [d[key] for d in days
                  if d.get(key) is not None and not isinstance(d[key], bool)]
        return fn(values) if values else None

    return {
        "days": len(days),
        "temp_min": extreme("temp_min", min),
        "temp_max": extreme("temp_max", max),
        "precip_prob": extreme("precip_prob", max),
        "wind_kph": extreme("wind_kph", max),
        "uv": extreme("uv", max),
        "providers": sorted({d.get("provider") for d in days if d.get("provider")}),
    }


def _num(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ── the rule table ──────────────────────────────────────────────────────────
#
# Each entry: (rule_key, category, classification, critical, predicate, reason)
# The predicate receives (attributes, weather) and returns a reason string when
# it fires, or None. A reason is required — a rule that cannot say why it fired
# is a rule nobody can argue with, and §10 makes explainability the point.

def _rules_trail_running(attrs: dict, wx: dict) -> list[tuple]:
    hours = _num(attrs.get("expected_hours"))
    night = _num(attrs.get("night_hours"))
    gain = _num(attrs.get("elevation_gain_m"))
    altitude = _num(attrs.get("max_altitude_m"))
    terrain = set(attrs.get("terrain") or [])
    technical = attrs.get("technicality") in ("technical", "very_technical")
    self_supported = attrs.get("self_supported") is True
    distance = _num(attrs.get("distance_km"))

    out: list[tuple] = []

    def rule(key, category, classification, critical, reason):
        out.append((key, category, classification, critical, reason))

    # Always
    rule("shoes_always", "shoes", REQUIRED, False,
         "You are running; shoes are the one thing without an alternative.")

    # Darkness
    if night is not None and night > 0:
        rule("headlamp_darkness", "headlamp", REQUIRED, True,
             f"{night:g} h of this is in the dark.")
        rule("headlamp_spare_power", "electronics", RECOMMENDED, False,
             f"{night:g} h of darkness — spare cells or a battery pack.")
    elif night is not None:
        rule("headlamp_no_darkness", "headlamp", NOT_NEEDED, False,
             "No darkness expected on this one.")

    # Duration
    if hours is not None and hours >= HYDRATION_HOURS:
        rule("hydration_duration", "hydration", REQUIRED, True,
             f"{hours:g} h out — water has to be carried.")
    if hours is not None and hours >= NUTRITION_HOURS:
        rule("nutrition_duration", "nutrition", REQUIRED, False,
             f"{hours:g} h out — that is a day of eating, not a snack.")
    if hours is not None and hours >= NUTRITION_HOURS:
        rule("vest_duration", "vest", REQUIRED, False,
             f"{hours:g} h of kit, water and food needs something to carry it.")

    # Terrain and climbing
    if gain is not None and gain >= POLES_GAIN_M:
        rule("poles_climbing", "poles", RECOMMENDED, False,
             f"{gain:g} m of climbing is where poles earn their weight.")
    if technical or (terrain & {"mountain", "technical"}):
        rule("navigation_technical", "navigation", RECOMMENDED, False,
             "Technical ground — knowing where the line goes matters.")
    if "snow" in terrain or "desert" in terrain:
        rule("gaiters_debris", "gaiters", RECOMMENDED, False,
             f"{'Snow' if 'snow' in terrain else 'Sand'} gets into shoes.")

    # Self-support and remoteness
    if self_supported:
        rule("first_aid_self_supported", "first_aid", REQUIRED, True,
             "Self-supported — nobody else is carrying the first aid kit.")
        rule("safety_self_supported", "safety", REQUIRED, True,
             "Self-supported — a whistle and a blanket are the difference "
             "between a bad night and a rescue.")
    if distance is not None and distance >= 40:
        rule("phone_distance", "electronics", RECOMMENDED, False,
             f"{distance:g} km out — a phone is how you call for help.")

    # Weather
    rain = wx.get("precip_prob")
    if rain is not None and rain >= RAIN_PROB_PCT:
        rule("rain_shell", "jacket", REQUIRED, False,
             f"{rain:g}% chance of rain in the forecast.")
    wind = wx.get("wind_kph")
    if wind is not None and wind >= WIND_KPH:
        rule("wind_shell", "jacket", REQUIRED, False,
             f"Wind to {wind:g} kph — a shell stops being optional.")
    cold = wx.get("temp_min")
    if cold is not None and cold <= COLD_TEMP_C:
        rule("cold_hands", "gloves", RECOMMENDED, False,
             f"Lows around {cold:g}°C — hands stop working first.")
        rule("cold_head", "headwear", RECOMMENDED, False,
             f"Lows around {cold:g}°C.")
        rule("cold_layer", "apparel_top", RECOMMENDED, False,
             f"Lows around {cold:g}°C — a layer you can put on.")
    hot = wx.get("temp_max")
    if hot is not None and hot >= HOT_TEMP_C:
        rule("heat_sun", "headwear", RECOMMENDED, False,
             f"Highs around {hot:g}°C.")
        rule("heat_eyes", "eyewear", RECOMMENDED, False,
             f"Highs around {hot:g}°C and open ground.")
    uv = wx.get("uv")
    if uv is not None and uv >= HIGH_UV:
        rule("uv_high", "eyewear", RECOMMENDED, False, f"UV index {uv:g}.")

    # Altitude
    if altitude is not None and altitude >= ALTITUDE_M:
        rule("altitude_layer", "apparel_top", RECOMMENDED, False,
             f"Up to {altitude:g} m — it is colder and windier up there than "
             f"the valley forecast says.")

    return out


# ── fishing (Phase 7) ───────────────────────────────────────────────────────
#
# THE SAME SHAPE AS THE TRAIL RULES — (key, category, classification, critical,
# reason) — which is the part of the design that DID generalise. What did not
# was the dispatch: before this phase `generate` called the trail table
# unconditionally, so a fishing trip to an uninhabited island was told it was
# missing running shoes. That was unreachable (the adventures router refuses an
# unbuilt activity) right up until fishing became selectable, which is why the
# dispatch and `built = true` land together.
#
# NO AUTHORITATIVE KIT LIST EXISTS FOR THIS DISCIPLINE. A race publishes its
# mandatory equipment; an expedition to somewhere uninhabited does not. So §24's
# REQUIRED lines come from `remote`, from the trip type, and from `mandatory_kit`
# typed in by the person going — never from an assumed external source.

#: Hours afloat beyond which a spare setup stops being luxury. A broken rod on
#: day one of an eight-day trip with no tackle shop is the trip.
SPARE_SETUP_HOURS = 24
#: Days beyond which line and terminal tackle get consumed rather than carried.
RESUPPLY_DAYS = 3


def _rules_fishing(attrs: dict, wx: dict) -> list[tuple]:
    days = _num(attrs.get("days"))
    hours = _num(attrs.get("boat_hours"))
    techniques = set(attrs.get("technique") or [])
    trip = attrs.get("trip_type")
    remote = attrs.get("remote") is True
    water = attrs.get("water")

    out: list[tuple] = []

    def rule(key, category, classification, critical, reason):
        out.append((key, category, classification, critical, reason))

    # Always — you cannot fish without these three.
    rule("rod_always", "rod", REQUIRED, False,
         "You are fishing; the rod is the one thing with no substitute.")
    rule("reel_always", "reel", REQUIRED, False,
         "A rod without a reel is a stick.")
    rule("line_always", "line", REQUIRED, True,
         "Everything between you and the fish runs through it.")
    rule("leader_always", "leader", REQUIRED, True,
         "The leader is what touches the fish, and what coral cuts first.")

    if techniques:
        rule("lure_technique", "lure", REQUIRED, False,
             f"{'/'.join(sorted(techniques))} — the lure is the technique.")
        rule("terminal_technique", "terminal_tackle", REQUIRED, True,
             "Hooks and split rings are the smallest part of the chain and the "
             "part that straightens.")

    # Sun is not a comfort item on open water. It is the exposure that ends
    # days early, and §24 puts it beside the safety kit rather than below it.
    rule("sun_always", "sun_protection", REQUIRED, False,
         "Open water, all day, with the sea reflecting it back at you.")
    rule("tools_always", "tools", REQUIRED, False,
         "Pliers and cutters — for the fish's sake as much as yours.")

    # Remoteness, which is this discipline's version of self-support.
    if remote:
        rule("first_aid_remote", "first_aid", REQUIRED, True,
             "No quick evacuation from here — nobody else is carrying the "
             "first aid kit.")
        rule("safety_remote", "safety", REQUIRED, True,
             "Remote water. A means of signalling is the difference between a "
             "long wait and a search.")

    if trip in ("liveaboard", "camp_shore"):
        rule("storage_multiday", "accessories", RECOMMENDED, False,
             "Multi-day — tackle needs somewhere dry to live between sessions.")

    if days is not None and days >= RESUPPLY_DAYS:
        rule("spare_line", "line", RECOMMENDED, False,
             f"{days:g} days out with no tackle shop — braid gets cut.")

    if hours is not None and hours >= SPARE_SETUP_HOURS:
        rule("spare_rod", "rod", RECOMMENDED, False,
             f"{hours:g} h afloat. A broken blank on day one is the whole trip "
             f"unless there is a second.")

    if water in ("offshore", "reef"):
        rule("eyewear_glare", "sun_protection", RECOMMENDED, False,
             "Polarised lenses are how you see structure and fish, not just "
             "how you squint less.")

    return out


#: activity_key -> its rule table. The dispatch that did not exist before Phase 7.
#:
#: An activity with no entry contributes NO rules rather than falling back to
#: trail running. Falling back is precisely the bug this replaces, and a pack
#: with only the mandatory kit and the locker on it is a truthful answer for an
#: activity nobody has written rules for yet.
ACTIVITY_RULES = {
    "trail_running": _rules_trail_running,
    "fishing": _rules_fishing,
}


def _rules(adventure: dict, attrs: dict, wx: dict) -> list[tuple]:
    table = ACTIVITY_RULES.get(adventure.get("activity_key") or "")
    return table(attrs, wx) if table else []


# ── the engine ──────────────────────────────────────────────────────────────

def generate(adventure: dict, locker: list[dict], weather: list[dict], *,
             health: dict[str, HealthResult] | None = None) -> PackResult:
    """Classify a pack for one adventure. Pure — no I/O, no clock, no model."""
    attrs = adventure.get("attributes") or {}
    wx = summarise_weather(weather or [])
    health = health or {}
    active = [g for g in locker if g.get("status") == "active"]

    lines: list[PackLine] = []
    warnings: list[PackWarning] = []
    claimed: set[str] = set()          # gear ids already on the list
    decided: dict[str, PackLine] = {}  # category -> best line so far

    # ── 1. mandatory kit, first and untouchable ────────────────────────────
    kit = attrs.get("mandatory_kit") or []
    unmatched = 0
    for position, raw in enumerate(kit):
        line = str(raw).strip()
        if not line:
            continue
        # `claimed` is passed, not just written to. Two kit lines in one
        # category — a survival blanket and a whistle are both `safety` — would
        # otherwise both be answered by the same item.
        gear, category, confident = matching.best_gear_for(line, active, claimed)
        if category is None:
            unmatched += 1
            lines.append(PackLine(
                name=line, classification=REQUIRED, rule_key="mandatory_kit",
                reason="On the race's mandatory kit list.",
                critical=True, source="mandatory"))
            continue
        if gear is not None:
            claimed.add(gear["id"])
            # A CATEGORY-ONLY MATCH IS PHRASED AS A QUESTION.
            #
            # The matcher works at category granularity, so any `safety` item
            # answers any `safety` line. Stating "Mandatory kit: Survival
            # blanket" beside a life jacket asserts a match nobody checked.
            # Where the item's own name echoes the requirement the assertion is
            # earned; where it does not, the line asks the runner to confirm —
            # which is what §24's "allow manual verification" is for, and what
            # the VERIFIED pack state exists to record.
            reason = (f"Mandatory kit: {line}."
                      if confident else
                      f"Matched to the mandatory \u201c{line}\u201d by category — "
                      f"check this is the right item.")
            lines.append(PackLine(
                name=gear["name"], classification=REQUIRED,
                rule_key="mandatory_kit", reason=reason,
                category_key=category, gear_item_id=gear["id"],
                critical=True, source="mandatory"))
        else:
            lines.append(PackLine(
                name=line, classification=MISSING, rule_key="mandatory_kit",
                reason=f"Mandatory kit, and there is no {category.replace('_', ' ')} "
                       f"in your locker.",
                category_key=category, critical=True, source="mandatory"))
            warnings.append(PackWarning(
                key="mandatory_missing", severity="critical",
                message=f"Required by the race and not in your locker: {line}.",
                rule_key="mandatory_kit", detail={"line": line, "category": category}))

    if unmatched:
        warnings.append(PackWarning(
            key="kit_unmatched", severity="note",
            message=f"{unmatched} mandatory item(s) could not be matched to a "
                    f"category, so they are listed as-is. Nothing was dropped.",
            rule_key="mandatory_kit", detail={"count": unmatched}))

    # ── 2. the rules ───────────────────────────────────────────────────────
    mandated_categories = {ln.category_key for ln in lines if ln.category_key}
    #: Recommended categories the locker cannot fill. Reported once, together,
    #: rather than as one MISSING line each — see the note where it is filled.
    suggested: list[tuple[str, str]] = []

    for key, category, classification, critical, reason in _rules(adventure, attrs, wx):
        # A category the race already mandates is settled. A rule here may not
        # add a second line for it and certainly may not downgrade it.
        if category in mandated_categories:
            continue
        existing = decided.get(category)
        if existing and RANK[existing.classification] >= RANK[classification]:
            continue

        gear = _pick(category, active, claimed)
        if gear is None and classification == REQUIRED:
            decided[category] = PackLine(
                name=_label(category), classification=MISSING, rule_key=key,
                reason=f"{reason} Nothing in your locker fits.",
                category_key=category, critical=critical)
        elif gear is None:
            # A RECOMMENDATION YOU DO NOT OWN IS NOT A MISSING ITEM.
            #
            # Listing every unowned recommendation as MISSING turns the pack
            # into a shopping list — the first draft of this engine produced
            # eight missing lines against five required ones, and four of the
            # eight were things no rule insisted on. §8 says prefer what the
            # runner already owns and do not turn every recommendation into a
            # purchase; §14 makes the willingness to say "you do not need to
            # buy this" the trust anchor of the whole product.
            #
            # So it is gathered into one note below, where the information
            # still exists and does not read as a checkout.
            if classification == RECOMMENDED:
                suggested.append((category, reason))
            continue
        else:
            decided[category] = PackLine(
                name=gear["name"], classification=classification, rule_key=key,
                reason=reason, category_key=category,
                gear_item_id=gear["id"], critical=critical)

    for category, line in decided.items():
        if line.gear_item_id:
            claimed.add(line.gear_item_id)
        lines.append(line)

    # ── 3. everything else you own, offered rather than prescribed ─────────
    for gear in active:
        if gear["id"] in claimed:
            continue
        lines.append(PackLine(
            name=gear["name"], classification=OPTIONAL, rule_key="owned",
            reason="In your locker; no rule argues for or against it.",
            category_key=gear.get("category_key"), gear_item_id=gear["id"]))

    # ── 4. warnings from the other engines, for gear that is on the list ───
    on_list = {ln.gear_item_id: ln for ln in lines if ln.gear_item_id
               and ln.classification in (REQUIRED, RECOMMENDED)}
    by_id = {g["id"]: g for g in active}

    for gear_id, line in on_list.items():
        result = health.get(gear_id)
        if result is not None and result.needs_attention:
            warnings.append(PackWarning(
                key=f"health_{result.state}",
                severity="caution" if result.state == "inspect" else "critical",
                message=f"{line.name}: {result.message}",
                rule_key="gear_health", gear_item_id=gear_id,
                detail=result.detail))

        gear = by_id.get(gear_id)
        if gear is None:
            continue
        for verdict in compatibility.evaluate(gear, adventure):
            if verdict.state == compatibility.NOT_RECOMMENDED:
                warnings.append(PackWarning(
                    key=f"compat_{verdict.rule_key}", severity="caution",
                    message=f"{line.name}: {verdict.message}",
                    rule_key=verdict.rule_key, gear_item_id=gear_id,
                    detail=verdict.detail))
            elif verdict.state == compatibility.UNKNOWN:
                warnings.append(PackWarning(
                    key=f"unknown_{verdict.rule_key}", severity="note",
                    message=f"{line.name}: {verdict.message}",
                    rule_key=verdict.rule_key, gear_item_id=gear_id,
                    detail=verdict.detail))

    if suggested:
        names = ", ".join(_label(c).lower() for c, _ in suggested)
        warnings.append(PackWarning(
            key="could_help", severity="note",
            message=f"Conditions would suit {names}, and you do not own any. "
                    f"Not required — plenty of people finish without.",
            rule_key="recommendations_unowned",
            detail={"categories": [c for c, _ in suggested],
                    "reasons": {c: r for c, r in suggested}}))

    # AN ACTIVITY WITH NO RULES SAYS SO. Without this the pack is simply short,
    # and short looks identical to "the rules decided you need very little" —
    # which is the most reassuring possible way to be wrong.
    if (adventure.get("activity_key") or "") not in ACTIVITY_RULES:
        warnings.append(PackWarning(
            key="no_rules", severity="note",
            message=f"No packing rules exist for "
                    f"{adventure.get('activity_key') or 'this activity'} yet, so "
                    f"this list is your mandatory kit and your locker — nothing "
                    f"here was decided by a rule.",
            rule_key="activity_dispatch",
            detail={"activity_key": adventure.get("activity_key")}))

    if not weather:
        warnings.append(PackWarning(
            key="no_forecast", severity="note",
            message="No forecast for these dates, so nothing here is weather-"
                    "driven. Re-generate closer to the day.",
            rule_key="weather_absent"))

    lines.sort(key=lambda ln: (-RANK[ln.classification],
                               0 if ln.critical else 1,
                               ln.category_key or "zz", ln.name))

    counts: dict[str, int] = {}
    for line in lines:
        counts[line.classification] = counts.get(line.classification, 0) + 1

    return PackResult(
        lines=lines, warnings=warnings,
        snapshot={
            "ruleset": PACK_RULESET,
            "compat_ruleset": compatibility.COMPAT_RULESET,
            "match_ruleset": matching.MATCH_RULESET,
            "weather": wx,
            "counts": counts,
            "activity": adventure.get("activity_key"),
        "locker_size": len(active),
            "mandatory_items": len(kit),
            "unmatched_mandatory": unmatched,
        })


def _pick(category: str, locker: list[dict], claimed: set[str]) -> dict | None:
    """The best unclaimed item in a category.

    Same ordering as the matcher, INCLUDING the id as the final key — see
    best_gear_for on why a tie resolved by row order is a pack that changes
    between days with nothing having changed.
    """
    candidates = [g for g in locker
                  if g.get("category_key") == category and g["id"] not in claimed]
    if not candidates:
        return None
    return sorted(candidates, key=lambda g: (
        0 if g.get("favorite") else 1,
        g.get("weight_g") if g.get("weight_g") is not None else 10**9,
        str(g.get("created_at") or ""),
        str(g.get("id") or ""),
    ))[0]


def _label(category: str) -> str:
    return category.replace("_", " ").capitalize()


# ── readiness (§9) ──────────────────────────────────────────────────────────

PACKED_STATES = ("packed", "verified")


def readiness(items: list[dict]) -> dict:
    """The departure check. Counts states; decides nothing else.

    Only REQUIRED counts toward the figure. A percentage that included optional
    gear would fall when someone declined to bring a spare buff, which makes
    the number mean nothing at the moment it matters most.

    Critical items are reported SEPARATELY rather than folded in. "43 of 47
    packed" and "one critical item unverified" are different facts, and the
    second is the one that ends a race at a kit check.
    """
    required = [i for i in items if i.get("classification") == REQUIRED]
    packed = [i for i in required if i.get("state") in PACKED_STATES]
    verified = [i for i in required if i.get("state") == "verified"]
    critical = [i for i in items if i.get("critical")]
    critical_unverified = [i for i in critical if i.get("state") != "verified"]
    missing = [i for i in items if i.get("classification") == MISSING]

    return {
        "required_total": len(required),
        "required_packed": len(packed),
        "required_verified": len(verified),
        "remaining": len(required) - len(packed),
        "critical_total": len(critical),
        "critical_unverified": len(critical_unverified),
        "missing_total": len(missing),
        # None rather than 100 when there is nothing required: an empty pack is
        # not a ready one, and rendering "100%" over an unplanned adventure is
        # the kind of false reassurance §12 exists to prevent.
        "percent": (round(100 * len(packed) / len(required))
                    if required else None),
        "ready": bool(required) and not missing
                 and len(packed) == len(required)
                 and not critical_unverified,
    }
