"""The activity registry — the one source of truth for what fields an activity has.

WHY THIS IS PYTHON AND NOT SQL
------------------------------
`activities.attribute_schema` in the database is a COPY, pushed by
scripts/seed_reference.py. This module is the original, because it is what
pydantic validates against on every write. A schema that lives in both places
and is authoritative in neither will disagree with itself within a month; a
schema that lives only in SQL cannot be imported by the validator.

WHY FOUR ACTIVITIES WHEN ONE IS BUILT
-------------------------------------
Master Prompt §3 says hiking, fishing and fly fishing must not require rework
to add later. That claim is untestable while trail running is the only consumer
— any shape holds for a sample of one. So all four schemas exist, and
test_activity_schemas.py exercises the loader, the validator and the serialiser
against every one of them.

As of Phase 7 TWO are built — trail_running and fishing — which is the first
point at which the claim above is tested rather than asserted. What it cost is
recorded in engines/tackle.py and in the activity dispatch in engines/pack.py:
the attribute model held without a structural change, and the two ENGINES did
not. hiking and fly_fishing remain defined and unreachable.

FIELD SPEC
----------
    {"type": ..., "label": ..., "unit": ..., "options": [...],
     "required": bool, "min": n, "max": n}

types: string · text · int · number · bool · enum · multi_enum · string_list

`min`/`max` bound numbers. `options` is required for enum and multi_enum and is
ignored otherwise. `required` applies only where the field is offered — a
required shoe field is not required of a headlamp.
"""
from __future__ import annotations

SCHEMA_VERSION = "1"

TERRAIN = ["mountain", "technical", "forest", "desert", "road", "mixed", "snow"]


# ── trail running — THE ONE THAT IS BUILT ───────────────────────────────────

TRAIL_RUNNING = {
    "version": SCHEMA_VERSION,
    "gear": {
        "shoes": {
            # No size_eu here — `size` is a built-in column on gear_items and
            # shoes are in SIZED_CATEGORIES. Two size fields on one form is the
            # poles bug wearing different clothes.
            "stack_height_mm":  {"type": "int", "label": "Stack height", "unit": "mm", "min": 0, "max": 60},
            "drop_mm":          {"type": "int", "label": "Drop", "unit": "mm", "min": 0, "max": 20},
            "lug_depth_mm":     {"type": "number", "label": "Lug depth", "unit": "mm", "min": 0, "max": 12},
            "outsole":          {"type": "string", "label": "Outsole"},
            "plate":            {"type": "bool", "label": "Rock plate / carbon"},
            "waterproof":       {"type": "bool", "label": "Waterproof"},
            "cushioning":       {"type": "enum", "label": "Cushioning",
                                 "options": ["minimal", "moderate", "max"]},
            "terrain":          {"type": "multi_enum", "label": "Best for", "options": TERRAIN},
            # The mileage threshold this pair is judged against. Null means "use
            # the category default" — see engines/gear_health.py. It is here and
            # not a column because it is a property of the shoe's foam, which is
            # exactly the kind of thing only this activity knows about.
            "lifespan_km":      {"type": "int", "label": "Expected lifespan", "unit": "km", "min": 100, "max": 2000},
        },
        "socks": {
            "height":  {"type": "enum", "label": "Height", "options": ["no_show", "ankle", "crew", "calf"]},
            "cushion": {"type": "enum", "label": "Cushion", "options": ["none", "light", "medium", "heavy"]},
        },
        "vest": {
            "capacity_l":   {"type": "number", "label": "Capacity", "unit": "L", "min": 0, "max": 40},
            "flask_slots":  {"type": "int", "label": "Flask slots", "min": 0, "max": 6},
            "bladder_ready": {"type": "bool", "label": "Bladder compatible"},
            "pole_carry":   {"type": "bool", "label": "Pole carry"},
        },
        "poles": {
            "length_cm": {"type": "int", "label": "Length", "unit": "cm", "min": 90, "max": 140},
            "folding":   {"type": "enum", "label": "Type", "options": ["fixed", "telescopic", "z_fold"]},
            "material":  {"type": "enum", "label": "Material", "options": ["aluminium", "carbon", "composite"]},
            "sections":  {"type": "int", "label": "Sections", "min": 1, "max": 5},
        },
        "hydration": {
            "volume_ml": {"type": "int", "label": "Volume", "unit": "ml", "min": 0, "max": 3000},
            "kind":      {"type": "enum", "label": "Type", "options": ["soft_flask", "hard_bottle", "bladder"]},
        },
        "nutrition": {
            "kind":       {"type": "enum", "label": "Type",
                           "options": ["gel", "bar", "chew", "drink_mix", "real_food", "salt"]},
            "calories":   {"type": "int", "label": "Calories", "min": 0, "max": 1000},
            "carbs_g":    {"type": "number", "label": "Carbs", "unit": "g", "min": 0, "max": 200},
            "sodium_mg":  {"type": "int", "label": "Sodium", "unit": "mg", "min": 0, "max": 2000},
            "caffeine_mg": {"type": "int", "label": "Caffeine", "unit": "mg", "min": 0, "max": 400},
        },
        "headlamp": {
            "lumens":       {"type": "int", "label": "Max output", "unit": "lm", "min": 0, "max": 3000},
            "burn_time_h":  {"type": "number", "label": "Burn time at usable output", "unit": "h", "min": 0, "max": 200},
            "battery_wh":   {"type": "number", "label": "Battery", "unit": "Wh", "min": 0, "max": 100},
            "rechargeable": {"type": "bool", "label": "Rechargeable"},
            "reactive":     {"type": "bool", "label": "Reactive lighting"},
        },
        "jacket": {
            "waterproof":            {"type": "bool", "label": "Waterproof"},
            "hydrostatic_head_mm":   {"type": "int", "label": "Hydrostatic head", "unit": "mm", "min": 0, "max": 40000},
            "taped_seams":           {"type": "bool", "label": "Taped seams"},
            "hood":                  {"type": "bool", "label": "Hood"},
            # Race kit lists name this specifically, so it is a field rather
            # than something to infer from the two above.
            "race_legal":            {"type": "bool", "label": "Meets race waterproof spec"},
        },
        "apparel_top": {
            "sleeve": {"type": "enum", "label": "Sleeve", "options": ["vest", "short", "long"]},
            "fabric": {"type": "string", "label": "Fabric"},
            "uv_rating": {"type": "int", "label": "UPF", "min": 0, "max": 100},
        },
        "apparel_bottom": {
            "cut":     {"type": "enum", "label": "Cut", "options": ["short", "half_tight", "tight", "3_4", "long"]},
            "pockets": {"type": "int", "label": "Pockets", "min": 0, "max": 12},
            "liner":   {"type": "bool", "label": "Built-in liner"},
        },
        "navigation": {
            "gps":            {"type": "bool", "label": "GPS"},
            "maps":           {"type": "bool", "label": "On-device maps"},
            "battery_life_h": {"type": "number", "label": "Battery in GPS mode", "unit": "h", "min": 0, "max": 200},
        },
        "gaiters": {
            "height": {"type": "enum", "label": "Height", "options": ["low", "mid", "high"]},
            "attachment": {"type": "string", "label": "Attachment"},
        },
    },
    "adventure": {
        "distance_km":       {"type": "number", "label": "Distance", "unit": "km",
                              "required": True, "min": 0, "max": 1000},
        "elevation_gain_m":  {"type": "int", "label": "Elevation gain", "unit": "m", "min": 0, "max": 30000},
        "elevation_loss_m":  {"type": "int", "label": "Elevation loss", "unit": "m", "min": 0, "max": 30000},
        "expected_hours":    {"type": "number", "label": "Expected duration", "unit": "h", "min": 0, "max": 300},
        "cutoff_hours":      {"type": "number", "label": "Cutoff", "unit": "h", "min": 0, "max": 300},
        "night_hours":       {"type": "number", "label": "Expected hours in darkness", "unit": "h", "min": 0, "max": 200},
        "terrain":           {"type": "multi_enum", "label": "Terrain", "options": TERRAIN},
        "technicality":      {"type": "enum", "label": "Technicality",
                              "options": ["easy", "moderate", "technical", "very_technical"]},
        "aid_stations":      {"type": "int", "label": "Aid stations", "min": 0, "max": 100},
        "self_supported":    {"type": "bool", "label": "Self-supported"},
        "max_altitude_m":    {"type": "int", "label": "Max altitude", "unit": "m", "min": -500, "max": 9000},
        # AUTHORITATIVE EXTERNAL DATA (§24, audit risk #5). Entered by the
        # runner from the race manual, never generated. The pack engine treats
        # every entry as REQUIRED and non-negotiable.
        "mandatory_kit":     {"type": "string_list", "label": "Mandatory kit"},
        "race_name":         {"type": "string", "label": "Race"},
    },
}


# ── defined, not built ──────────────────────────────────────────────────────
# These exist to prove the model generalises. No UI reaches them. See the
# module docstring and test_activity_schemas.py.

HIKING = {
    "version": SCHEMA_VERSION,
    "gear": {
        "pack":    {"capacity_l": {"type": "number", "label": "Capacity", "unit": "L", "min": 0, "max": 120},
                    "frame": {"type": "enum", "label": "Frame", "options": ["frameless", "internal", "external"]}},
        "boots":   {"height": {"type": "enum", "label": "Height", "options": ["low", "mid", "high"]},
                    "waterproof": {"type": "bool", "label": "Waterproof"}},
        "shelter": {"season": {"type": "enum", "label": "Season", "options": ["1", "2", "3", "4"]},
                    "capacity": {"type": "int", "label": "Sleeps", "min": 1, "max": 8}},
        "sleep":   {"comfort_temp_c": {"type": "number", "label": "Comfort rating", "unit": "°C", "min": -40, "max": 30},
                    "fill": {"type": "enum", "label": "Fill", "options": ["down", "synthetic"]}},
    },
    "adventure": {
        "distance_km":      {"type": "number", "label": "Distance", "unit": "km", "required": True, "min": 0, "max": 5000},
        "days":             {"type": "int", "label": "Days", "min": 1, "max": 200},
        "elevation_gain_m": {"type": "int", "label": "Elevation gain", "unit": "m", "min": 0, "max": 30000},
        "max_altitude_m":   {"type": "int", "label": "Max altitude", "unit": "m", "min": -500, "max": 9000},
        "terrain":          {"type": "multi_enum", "label": "Terrain", "options": TERRAIN},
        "shelter_type":     {"type": "enum", "label": "Shelter",
                             "options": ["none", "tent", "tarp", "hut", "bivy"]},
    },
}

# ── fishing — THE SECOND ONE THAT IS BUILT (Phase 7) ────────────────────────
#
# TECHNIQUE IS A PROPERTY OF THE GEAR, and that is the thing trail running never
# needed. A trail shoe is not "for" a race type; it is a shoe. A rod IS for
# popping or for jigging, and the two are different tools — a popping rod is
# eight feet and more, throwing 100-150 g lures on the surface; a jigging rod is
# nearer six, working 150-300 g vertically under the boat. Put the wrong one in
# the wrong hand and it is not a preference, it is a broken blank.
#
# It drops into the attribute model without a structural change, which is the
# claim §0.4 made and the thing this phase exists to test. `technique` is a
# multi_enum because a rod genuinely can be rated for both.
#
# THE PE SCALE. Japanese braid sizing, and the number every rod, reel and line
# in this discipline is labelled with. It is a diameter standard, not a strength
# one — PE8 is roughly 80-100 lb depending on the maker — which is exactly why
# the compatibility rules below reason in PE where the tackle does and in pounds
# where the tackle does, rather than converting between them and pretending the
# result is exact.

TECHNIQUES = ["popping", "jigging", "casting", "trolling", "bottom"]

FISHING = {
    "version": SCHEMA_VERSION,
    "gear": {
        "rod": {
            "technique":     {"type": "multi_enum", "label": "Technique", "options": TECHNIQUES},
            "length_ft":     {"type": "number", "label": "Length", "unit": "ft", "min": 3, "max": 15},
            "pe_min":        {"type": "number", "label": "PE rating from", "min": 0.4, "max": 20},
            "pe_max":        {"type": "number", "label": "PE rating to", "min": 0.4, "max": 20},
            "cast_weight_min_g": {"type": "number", "label": "Casts from", "unit": "g", "min": 0, "max": 500},
            "cast_weight_max_g": {"type": "number", "label": "Casts to", "unit": "g", "min": 0, "max": 500},
            "jig_weight_max_g":  {"type": "number", "label": "Max jig", "unit": "g", "min": 0, "max": 1000},
            "pieces":        {"type": "int", "label": "Pieces", "min": 1, "max": 6},
            "action":        {"type": "enum", "label": "Action",
                              "options": ["slow", "moderate", "fast", "extra_fast"]},
        },
        "reel": {
            "technique":     {"type": "multi_enum", "label": "Technique", "options": TECHNIQUES},
            # A STRING, not a number, and deliberately. Shimano's 18000 and
            # Daiwa's 6500 describe similar reels; the number means something
            # only inside one maker's range. `size_class` below is what the
            # rules actually reason over.
            "size":          {"type": "string", "label": "Size"},
            "size_class":    {"type": "enum", "label": "Class",
                              "options": ["light", "medium", "heavy", "extra_heavy"]},
            "gear_ratio":    {"type": "string", "label": "Gear ratio"},
            "drag_kg":       {"type": "number", "label": "Max drag", "unit": "kg", "min": 0, "max": 40},
            "pe_capacity":   {"type": "number", "label": "Rated for PE", "min": 0.4, "max": 20},
            "line_capacity": {"type": "string", "label": "Line capacity"},
            "sealed":        {"type": "bool", "label": "Sealed body"},
        },
        "line": {
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["braid", "mono", "fluoro"]},
            "pe":            {"type": "number", "label": "PE", "min": 0.4, "max": 20},
            "lb_test":       {"type": "number", "label": "Breaking strain", "unit": "lb", "min": 0, "max": 400},
            "metres":        {"type": "int", "label": "Length", "unit": "m", "min": 0, "max": 2000},
        },
        # ITS OWN CATEGORY, not a variant of line. §11 names LINE↔LEADER as a
        # relationship in its own right, and the leader is the part that touches
        # the fish — for GT it is the difference between landing one and being
        # cut off on the first run.
        "leader": {
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["fluoro", "mono", "wire"]},
            "lb_test":       {"type": "number", "label": "Breaking strain", "unit": "lb", "min": 0, "max": 500},
            "metres":        {"type": "number", "label": "Length", "unit": "m", "min": 0, "max": 50},
        },
        "lure": {
            "technique":     {"type": "multi_enum", "label": "Technique", "options": TECHNIQUES},
            "weight_g":      {"type": "number", "label": "Weight", "unit": "g", "min": 0, "max": 1000},
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["popper", "stickbait", "jig", "minnow",
                                          "soft_plastic", "spoon"]},
            "hook_size":     {"type": "string", "label": "Hook size"},
        },
        "terminal_tackle": {
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["hook", "split_ring", "swivel", "assist_hook", "sinker"]},
            "rated_lb":      {"type": "number", "label": "Rated", "unit": "lb", "min": 0, "max": 500},
            "size":          {"type": "string", "label": "Size"},
        },
        "tools": {
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["pliers", "cutters", "gaff", "gloves",
                                          "scale", "release_tool", "knife"]},
        },
        "sun_protection": {
            "kind":          {"type": "enum", "label": "Type",
                              "options": ["hat", "buff", "sunglasses", "long_sleeve", "sunscreen"]},
            "polarised":     {"type": "bool", "label": "Polarised"},
            "upf":           {"type": "int", "label": "UPF", "min": 0, "max": 100},
        },
    },
    "adventure": {
        # TRIP TYPE, not "water type". A camp-based shore expedition and a
        # liveaboard are different trips with different kit, and the old
        # shore/inshore/offshore/boat enum conflated where you stand with how
        # you got there.
        "trip_type":      {"type": "enum", "label": "Trip", "required": True,
                           "options": ["day", "liveaboard", "camp_shore"]},
        "days":           {"type": "int", "label": "Days", "min": 1, "max": 60},
        "technique":      {"type": "multi_enum", "label": "Technique", "options": TECHNIQUES},
        "target_species": {"type": "string_list", "label": "Target species"},
        "water":          {"type": "enum", "label": "Water",
                           "options": ["shore", "inshore", "offshore", "reef"]},
        "depth_m":        {"type": "number", "label": "Depth", "unit": "m", "min": 0, "max": 2000},
        "boat_hours":     {"type": "number", "label": "Hours afloat", "unit": "h", "min": 0, "max": 500},
        # REMOTENESS IS THE SAFETY DIMENSION. §24 says distinguish mandatory
        # from recommended and display authoritative rules "where available" —
        # for an expedition to an uninhabited island there is no organiser and
        # no published list, so the REQUIRED lines come from this field and from
        # `mandatory_kit` typed in by the person going.
        "remote":         {"type": "bool", "label": "Remote / no quick evacuation"},
        "mandatory_kit":  {"type": "string_list", "label": "Required kit"},
        "trip_name":      {"type": "string", "label": "Trip"},
    },
}

FLY_FISHING = {
    "version": SCHEMA_VERSION,
    "gear": {
        "fly_rod":  {"length_ft": {"type": "number", "label": "Length", "unit": "ft", "min": 6, "max": 15},
                     "line_weight": {"type": "int", "label": "Line weight", "min": 0, "max": 16},
                     "pieces": {"type": "int", "label": "Pieces", "min": 1, "max": 7},
                     "action": {"type": "enum", "label": "Action",
                                "options": ["slow", "medium", "medium_fast", "fast"]}},
        "fly_reel": {"size": {"type": "string", "label": "Size"},
                     "backing_yd": {"type": "int", "label": "Backing", "unit": "yd", "min": 0, "max": 600},
                     "sealed_drag": {"type": "bool", "label": "Sealed drag"}},
        "fly_line": {"taper": {"type": "enum", "label": "Taper",
                               "options": ["wf", "dt", "level", "shooting"]},
                     "density": {"type": "enum", "label": "Density",
                                 "options": ["floating", "intermediate", "sinking", "sink_tip"]},
                     "weight": {"type": "int", "label": "Line weight", "min": 0, "max": 16}},
        "waders":   {"kind": {"type": "enum", "label": "Type", "options": ["stocking", "boot_foot"]},
                     "breathable": {"type": "bool", "label": "Breathable"}},
    },
    "adventure": {
        "water":          {"type": "enum", "label": "Water", "required": True,
                           "options": ["freshwater", "saltwater"]},
        "approach":       {"type": "enum", "label": "Approach",
                           "options": ["shore", "wading", "boat"]},
        "target_species": {"type": "string_list", "label": "Target species"},
        "rod_weight":     {"type": "int", "label": "Rod weight", "min": 0, "max": 16},
    },
}


# ── how a category records use ──────────────────────────────────────────────
#
# "Log a run" on a life jacket is what happens when a screen assumes every
# piece of gear wears out the way a shoe does. It does not: a headlamp is used
# for hours, a first aid kit is carried and never opened, a gel is eaten. Only
# some categories have a distance at all, and asking for one everywhere
# produces a locker full of zeroes that mean nothing.
#
# So it is a property of the category, declared here, and the app renders what
# it is told. §28 — no activity-specific hardcoded logic in the UI.
#
#   distance  the thing wears out by kilometre; log a run, sum a total
#   sessions  it wears out by outing; log a use, count them
#   none      consumed rather than used; there is nothing to accumulate

USAGE_DISTANCE, USAGE_SESSIONS, USAGE_NONE = "distance", "sessions", "none"

#: Shared across activities, so the universal categories (headlamp, safety,
#: first aid) are declared once rather than four times — the same reason
#: gear_categories.activity_key is nullable.
CATEGORY_USAGE = {
    # wears out by kilometre
    "shoes":          USAGE_DISTANCE,
    "socks":          USAGE_DISTANCE,
    "vest":           USAGE_DISTANCE,
    "poles":          USAGE_DISTANCE,
    "apparel_top":    USAGE_DISTANCE,
    "apparel_bottom": USAGE_DISTANCE,
    "gaiters":        USAGE_DISTANCE,
    # wears out by outing — a headlamp's burn hours are not the run's distance,
    # and a shell carried in a vest all day and never worn has covered the
    # distance without being used at all
    "jacket":       USAGE_SESSIONS,
    "headlamp":     USAGE_SESSIONS,
    "hydration":    USAGE_SESSIONS,
    "navigation":   USAGE_SESSIONS,
    "electronics":  USAGE_SESSIONS,
    "eyewear":      USAGE_SESSIONS,
    "headwear":     USAGE_SESSIONS,
    "gloves":       USAGE_SESSIONS,
    "accessories":  USAGE_SESSIONS,
    # carried, rarely used, and a count of times opened is worth having
    "first_aid":    USAGE_SESSIONS,
    "safety":       USAGE_SESSIONS,
    # consumed
    "nutrition":    USAGE_NONE,

    # ── fishing (Phase 7) ───────────────────────────────────────────────────
    # SESSIONS THROUGHOUT, and nothing new was needed. The natural unit here is
    # the fishing day, not a continuous metric: a reel is serviced on an
    # interval measured in trips and months, not in metres of line retrieved.
    # `sessions` already counts days out, so the accumulator that exists is the
    # right one — see the note above DEFAULT_USAGE.
    "rod":             USAGE_SESSIONS,
    "reel":            USAGE_SESSIONS,
    # Braid genuinely degrades with use, and the count of days on it is what a
    # person actually knows. Metres retrieved is not a number anyone has.
    "line":            USAGE_SESSIONS,
    "lure":            USAGE_SESSIONS,
    "tools":           USAGE_SESSIONS,
    "sun_protection":  USAGE_SESSIONS,
    # Consumed and replaced, usually every trip. A leader tied on Tuesday and
    # re-tied Wednesday has no history worth keeping, and asking for one would
    # be the life-jacket-reading-0-km bug in a different discipline.
    "leader":          USAGE_NONE,
    "terminal_tackle": USAGE_NONE,
}

#: An unknown category records sessions. Sessions is the safe default because
#: it asks for nothing the user has to measure — a date is always knowable,
#: a distance is not.
DEFAULT_USAGE = USAGE_SESSIONS


def usage_for(category_key: str | None) -> str:
    return CATEGORY_USAGE.get(category_key or "", DEFAULT_USAGE)


# ── which built-in columns a category actually has ──────────────────────────
#
# gear_items carries `size` for every row, and the form showed it for every
# row — so a pair of poles asked for a SIZE, and the owner typed "120cm" into
# it while the registry was rendering a proper LENGTH field (cm, 90–140) two
# rows below. Two fields for one measurement, one of them in the wrong
# vocabulary.
#
# Size is a property of things you WEAR. A headlamp has no size; a pole has a
# length; a flask has a volume — and each of those already exists as a typed,
# bounded, unit-carrying field in the schema above. The generic column is for
# the cases where "EU 45" or "M" is genuinely the answer.
#
# Same shape as CATEGORY_USAGE and for the same reason: the screen should not
# be deciding this, and a category that grows a size later changes here.
SIZED_CATEGORIES = frozenset({
    "shoes", "socks", "apparel_top", "apparel_bottom", "jacket",
    "gloves", "headwear", "vest", "gaiters",
    # Fishing: a rod has a LENGTH and a reel has a SIZE, both of which are their
    # own typed fields — putting a generic size box beside them is the poles bug
    # again. Only what a person actually wears is sized.
    "sun_protection",
    # future activities, declared with their schemas
    "boots", "waders",
})


def is_sized(category_key: str | None) -> bool:
    return (category_key or "") in SIZED_CATEGORIES


ACTIVITIES: dict[str, dict] = {
    "trail_running": TRAIL_RUNNING,
    "hiking": HIKING,
    "fishing": FISHING,
    "fly_fishing": FLY_FISHING,
}

# Merged in at import so there is ONE place a category's usage is declared and
# every consumer — the schema endpoint, the seed script's copy in the database,
# the app — sees the same answer. A per-activity `usage` key overrides, which
# nothing needs yet and fishing may when a rod's wear is counted in casts.
for _schema in ACTIVITIES.values():
    _schema["usage"] = {**CATEGORY_USAGE, **_schema.get("usage", {})}
    # Served so the form knows which built-in columns to offer. A category
    # absent from this list has no `size`, and the screen must not ask for one.
    _schema["sized"] = sorted(
        c for c in set(_schema.get("gear", {})) | set(CATEGORY_USAGE)
        if c in SIZED_CATEGORIES)

#: The only one with a UI. Everything else is schema-only until Phase 7.
#: Which activities the app will actually offer. The adventures router refuses
#: anything outside this set at the API boundary, and engines/pack.py dispatches
#: its rule table on the same key.
#:
#: ADDING TO THIS SET IS WHAT MAKES A LATENT BUG REACHABLE. Until Phase 7 the
#: pack engine ran the trail-running rules for every activity — harmless while
#: nothing else could be created, and the reason a fishing expedition would have
#: been told it was missing running shoes the moment fishing appeared here. The
#: dispatch and this line changed in the same commit, deliberately.
BUILT = ("trail_running", "fishing")


def schema_for(activity_key: str) -> dict | None:
    return ACTIVITIES.get(activity_key)


def gear_fields(activity_key: str, category_key: str | None) -> dict:
    """Field specs for one activity/category pair. Empty dict when either is
    unknown — an unrecognised category is a category with no extra fields, not
    an error. That is what lets a universal category (headlamp, navigation) be
    used by an activity that never declared it."""
    schema = ACTIVITIES.get(activity_key) or {}
    return (schema.get("gear") or {}).get(category_key or "", {})


def adventure_fields(activity_key: str) -> dict:
    schema = ACTIVITIES.get(activity_key) or {}
    return schema.get("adventure") or {}
