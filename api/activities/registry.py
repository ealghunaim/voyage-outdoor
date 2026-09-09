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
against every one of them. Only trail_running has `built = True`; nothing in the
app reaches the others.

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
            "size_eu":          {"type": "string", "label": "Size (EU)"},
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
            "size":         {"type": "string", "label": "Size"},
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
                    "waterproof": {"type": "bool", "label": "Waterproof"},
                    "size_eu": {"type": "string", "label": "Size (EU)"}},
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

FISHING = {
    "version": SCHEMA_VERSION,
    "gear": {
        "rod":    {"length_ft": {"type": "number", "label": "Length", "unit": "ft", "min": 3, "max": 15},
                   "cast_weight_g": {"type": "number", "label": "Cast weight", "unit": "g", "min": 0, "max": 500},
                   "pieces": {"type": "int", "label": "Pieces", "min": 1, "max": 6},
                   "action": {"type": "enum", "label": "Action",
                              "options": ["slow", "moderate", "fast", "extra_fast"]}},
        "reel":   {"size": {"type": "string", "label": "Size"},
                   "gear_ratio": {"type": "string", "label": "Gear ratio"},
                   "drag_kg": {"type": "number", "label": "Max drag", "unit": "kg", "min": 0, "max": 40},
                   "line_capacity": {"type": "string", "label": "Line capacity"}},
        "line":   {"kind": {"type": "enum", "label": "Type", "options": ["mono", "fluoro", "braid"]},
                   "lb_test": {"type": "number", "label": "Test", "unit": "lb", "min": 0, "max": 300}},
        "lure":   {"weight_g": {"type": "number", "label": "Weight", "unit": "g", "min": 0, "max": 500},
                   "kind": {"type": "enum", "label": "Type",
                            "options": ["popper", "stickbait", "jig", "minnow", "soft_plastic"]}},
    },
    "adventure": {
        "water_type":     {"type": "enum", "label": "Water", "required": True,
                           "options": ["shore", "inshore", "offshore", "boat"]},
        "technique":      {"type": "multi_enum", "label": "Technique",
                           "options": ["jigging", "popping", "casting", "trolling", "bottom"]},
        "target_species": {"type": "string_list", "label": "Target species"},
        "depth_m":        {"type": "number", "label": "Depth", "unit": "m", "min": 0, "max": 2000},
        "boat_hours":     {"type": "number", "label": "Hours afloat", "unit": "h", "min": 0, "max": 300},
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
                     "size": {"type": "string", "label": "Size"},
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


ACTIVITIES: dict[str, dict] = {
    "trail_running": TRAIL_RUNNING,
    "hiking": HIKING,
    "fishing": FISHING,
    "fly_fishing": FLY_FISHING,
}

#: The only one with a UI. Everything else is schema-only until Phase 7.
BUILT = ("trail_running",)


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
