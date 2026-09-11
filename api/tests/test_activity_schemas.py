"""THE LOAD-BEARING TEST OF PHASE 1.

Master Prompt §3 claims the attribute system will not need rework when hiking,
fishing and fly fishing are added in Phase 7. That claim is untestable while
trail running is the only consumer — every shape holds for a sample of one, and
the rework only shows up eighteen months later when it is expensive.

So all four schemas exist now, and this file drives the registry, the validator
and the serialiser over every one of them. Nothing in the app reaches the three
unbuilt activities; this test does, which is the point.

If someone later adds an activity whose fields do not survive these assertions,
that is the architecture failing while it is still cheap to change.
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from api.activities.registry import (ACTIVITIES, BUILT, CATEGORY_USAGE,
                                     SCHEMA_VERSION, USAGE_DISTANCE, USAGE_NONE,
                                     USAGE_SESSIONS, SIZED_CATEGORIES, adventure_fields,
                                     gear_fields, is_sized, schema_for, usage_for)
from api.activities.validate import (validate_adventure_attributes,
                                     validate_gear_attributes)

FIELD_TYPES = {"string", "text", "int", "number", "bool",
               "enum", "multi_enum", "string_list"}

ALL = sorted(ACTIVITIES)


def _every_field():
    """(activity, where, field_name, spec) for every field in every schema."""
    for activity, schema in ACTIVITIES.items():
        for category, fields in (schema.get("gear") or {}).items():
            for name, spec in fields.items():
                yield activity, f"gear.{category}", name, spec
        for name, spec in (schema.get("adventure") or {}).items():
            yield activity, "adventure", name, spec


# ── the registry is well-formed ─────────────────────────────────────────────

@pytest.mark.parametrize("activity", ALL)
def test_schema_has_required_sections(activity):
    schema = schema_for(activity)
    assert schema is not None
    assert schema["version"] == SCHEMA_VERSION
    assert isinstance(schema.get("gear"), dict) and schema["gear"]
    assert isinstance(schema.get("adventure"), dict) and schema["adventure"]


def test_the_built_set_is_exactly_what_has_screens():
    """A built activity has screens behind it. Two of these do not, and the app
    must not offer them — an option that leads nowhere is worse than no option.
    Guards against someone flipping a flag to 'try it out'."""
    assert BUILT == ("trail_running", "fishing")
    assert "hiking" not in BUILT and "fly_fishing" not in BUILT


def test_every_built_activity_has_a_packing_rule_table():
    """THE INVARIANT THAT WOULD HAVE CAUGHT PHASE 7'S BUG. Before the activity
    dispatch existed, pack.generate() ran the trail-running rules for whatever
    it was given — so marking fishing built would have told an expedition to an
    uninhabited island that it was missing running shoes. Adding a key to BUILT
    without a rule table is now a failing test rather than a surprise on a
    screen."""
    from api.engines.pack import ACTIVITY_RULES
    for key in BUILT:
        assert key in ACTIVITY_RULES, f"{key} is built but has no packing rules"


def test_every_field_declares_a_known_type():
    for activity, where, name, spec in _every_field():
        assert spec.get("type") in FIELD_TYPES, f"{activity}.{where}.{name}"
        assert spec.get("label"), f"{activity}.{where}.{name} has no label"


def test_enums_carry_options_and_others_do_not_need_them():
    for activity, where, name, spec in _every_field():
        if spec["type"] in ("enum", "multi_enum"):
            options = spec.get("options")
            assert options, f"{activity}.{where}.{name} is an enum with no options"
            assert len(set(options)) == len(options), \
                f"{activity}.{where}.{name} has duplicate options"


def test_numeric_bounds_are_ordered():
    for activity, where, name, spec in _every_field():
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None and hi is not None:
            assert lo < hi, f"{activity}.{where}.{name} has min >= max"


def test_schema_is_json_serialisable():
    """It is copied into activities.attribute_schema (jsonb) by the seed script.
    A tuple or a set in here fails at the database rather than at the edit."""
    for activity, schema in ACTIVITIES.items():
        round_tripped = json.loads(json.dumps(schema))
        assert round_tripped == schema, activity


# ── the validator handles all four, not just the built one ──────────────────

REPRESENTATIVE_GEAR = {
    "trail_running": ("shoes", {"stack_height_mm": 33, "drop_mm": 6,
                                "lug_depth_mm": 4.5, "waterproof": False,
                                "cushioning": "max",
                                "terrain": ["technical", "mountain"]}),
    "hiking":        ("pack", {"capacity_l": 45, "frame": "internal"}),
    # A real GT popping reel rather than a plausible-looking one. The specs
    # here are USER-SUPPLIED and unverified (§0.5) — they came from the owner,
    # not from a catalogue and not from the brief, which does not contain them.
    "fishing":       ("reel", {"size": "18000", "size_class": "extra_heavy",
                               "drag_kg": 25.0, "gear_ratio": "5.7:1",
                               "pe_capacity": 8.0, "sealed": True,
                               "technique": ["popping", "jigging"]}),
    "fly_fishing":   ("fly_rod", {"length_ft": 9.0, "line_weight": 8,
                                  "pieces": 4, "action": "fast"}),
}

REPRESENTATIVE_ADVENTURE = {
    "trail_running": {"distance_km": 160, "elevation_gain_m": 9000,
                      "expected_hours": 30, "technicality": "technical",
                      "terrain": ["mountain", "technical"],
                      "mandatory_kit": ["Headlamp", "Space blanket", "Whistle"]},
    "hiking":        {"distance_km": 82, "days": 5, "shelter_type": "tent"},
    # Abd al Kuri — a real trip, used here the way Oman 100M is used above.
    "fishing":       {"trip_type": "camp_shore", "days": 8, "remote": True,
                      "water": "reef", "technique": ["popping", "jigging"],
                      "target_species": ["Giant trevally", "Dogtooth tuna"],
                      "trip_name": "Abd al Kuri"},
    "fly_fishing":   {"water": "saltwater", "approach": "wading",
                      "rod_weight": 9},
}


@pytest.mark.parametrize("activity", ALL)
def test_gear_attributes_validate_for_every_activity(activity):
    category, payload = REPRESENTATIVE_GEAR[activity]
    out = validate_gear_attributes(activity, category, payload)
    assert out == payload, f"{activity}/{category} did not round-trip"


@pytest.mark.parametrize("activity", ALL)
def test_adventure_attributes_validate_for_every_activity(activity):
    payload = REPRESENTATIVE_ADVENTURE[activity]
    out = validate_adventure_attributes(activity, payload)
    for key, value in payload.items():
        assert out[key] == value, f"{activity}.{key}"


@pytest.mark.parametrize("activity", ALL)
def test_every_activity_declares_exactly_one_required_adventure_field(activity):
    """Each activity needs the one number its whole plan hangs off — distance
    for the land activities, trip type for fishing and water for fly fishing.
    More than one
    required field makes the create form refuse a half-known plan, which is how
    most adventures start."""
    required = [k for k, spec in adventure_fields(activity).items()
                if spec.get("required")]
    assert len(required) == 1, f"{activity} requires {required}"


# ── the universal-category rule ─────────────────────────────────────────────

def test_unknown_category_yields_no_fields_rather_than_an_error():
    """A universal category (headlamp, navigation) is declared by trail_running
    but not by fishing. Asking fishing for headlamp fields must be empty, not a
    crash — otherwise every activity would have to redeclare the whole
    universal taxonomy, which is the duplication the null activity_key exists
    to prevent."""
    assert gear_fields("fishing", "headlamp") == {}
    assert validate_gear_attributes("fishing", "headlamp", {"lumens": 400}) == {}


def test_unknown_activity_is_empty_not_an_error():
    assert gear_fields("bikepacking", "shoes") == {}
    assert adventure_fields("bikepacking") == {}


# ── required-field semantics ────────────────────────────────────────────────

def test_required_field_is_enforced_on_a_full_write():
    with pytest.raises(HTTPException) as e:
        validate_adventure_attributes("trail_running", {"elevation_gain_m": 500})
    assert "distance_km" in e.value.detail


def test_required_field_is_not_enforced_on_a_patch():
    """A PATCH sends a subset by definition. A required field absent from the
    payload is absent from THIS REQUEST, not missing from the record — only a
    full write can judge that."""
    out = validate_adventure_attributes("trail_running", {"elevation_gain_m": 500},
                                        partial=True)
    assert out == {"elevation_gain_m": 500}


# ── how a category records use ──────────────────────────────────────────────
#
# "Log a run" appeared on a life jacket, which is what happens when a screen
# assumes every category wears out by the kilometre. These pin the fix down:
# usage is a property of the CATEGORY, declared once, and every activity's
# schema carries the answer.

def test_every_activity_schema_carries_a_usage_map():
    for activity, schema in ACTIVITIES.items():
        assert isinstance(schema.get("usage"), dict) and schema["usage"], activity


def test_usage_values_are_known():
    for activity, schema in ACTIVITIES.items():
        for category, kind in schema["usage"].items():
            assert kind in (USAGE_DISTANCE, USAGE_SESSIONS, USAGE_NONE), \
                f"{activity}.{category} = {kind!r}"


def test_universal_categories_are_declared_once_and_reach_every_activity():
    """headlamp, safety and first_aid belong to no activity in particular. If
    each activity had to declare them, three of the four would eventually
    forget one and the app would fall back to a default nobody chose."""
    for activity, schema in ACTIVITIES.items():
        for category in ("headlamp", "safety", "first_aid", "electronics"):
            assert category in schema["usage"], f"{activity} is missing {category}"


def test_safety_gear_does_not_record_distance():
    """The bug, as a test. A life jacket carried on a boat has no kilometres,
    and asking for them produces a locker full of zeroes that mean nothing."""
    for category in ("safety", "first_aid", "headlamp", "electronics", "eyewear"):
        assert usage_for(category) == USAGE_SESSIONS, category


def test_shoes_record_distance():
    """The other half: mileage is the number this app is judged on, and the
    gear-health engine in Phase 3 reads it."""
    assert usage_for("shoes") == USAGE_DISTANCE


def test_consumables_accumulate_nothing():
    assert usage_for("nutrition") == USAGE_NONE


def test_unknown_category_defaults_to_sessions():
    """Sessions asks for nothing the user has to measure — a date is always
    knowable, a distance is not. Defaulting the other way would put an empty
    kilometre field in front of gear that has none."""
    assert usage_for("trebuchet") == USAGE_SESSIONS
    assert usage_for(None) == USAGE_SESSIONS


def test_every_seeded_gear_category_has_a_usage_kind():
    """The categories in 0002 and the usage map must not drift apart. A
    category seeded into the database with no entry here renders under a
    default that nobody chose for it."""
    seeded = {
        "headlamp", "navigation", "electronics", "first_aid", "safety",
        "eyewear", "headwear", "gloves", "jacket", "accessories",
        "shoes", "socks", "vest", "poles", "hydration", "nutrition",
        "apparel_top", "apparel_bottom", "gaiters",
    }
    missing = seeded - set(CATEGORY_USAGE)
    assert not missing, f"no usage kind for {sorted(missing)}"


# ── which built-in columns a category has ───────────────────────────────────
#
# Seen on screen: the gear form asked a pair of poles for a SIZE, and the owner
# typed "120cm" into it while the schema was rendering a proper LENGTH field
# (cm, 90-140) two rows below. Two fields for one measurement, one of them in
# the wrong vocabulary.

def test_every_schema_lists_its_sized_categories():
    for activity, schema in ACTIVITIES.items():
        assert isinstance(schema.get("sized"), list), activity


def test_worn_things_have_a_size():
    for category in ("shoes", "socks", "jacket", "gloves", "vest"):
        assert is_sized(category), category


def test_things_that_are_measured_some_other_way_do_not():
    """Each of these already has a typed, bounded, unit-carrying field for the
    dimension that matters — poles a length, hydration a volume, headlamps a
    burn time. A generic size box beside those asks the same question twice."""
    for category in ("poles", "headlamp", "hydration", "nutrition",
                     "navigation", "electronics", "first_aid", "safety"):
        assert not is_sized(category), category


def test_the_sized_list_only_names_categories_that_exist():
    known = set(CATEGORY_USAGE) | {"boots", "waders"}
    assert SIZED_CATEGORIES <= known, SIZED_CATEGORIES - known


def test_trail_running_serves_its_sized_list():
    sized = set(schema_for("trail_running")["sized"])
    assert "shoes" in sized and "poles" not in sized


def test_no_sized_category_also_declares_its_own_size_field():
    """A category cannot have both the built-in `size` column and a size
    attribute — the form would ask for the same thing twice, which is the poles
    bug in a different shape. shoes carried `size_eu`, vest and waders carried
    `size`, boots carried `size_eu`."""
    duplicates = []
    for activity, schema in ACTIVITIES.items():
        for category, fields in (schema.get("gear") or {}).items():
            if not is_sized(category):
                continue
            for name in fields:
                if "size" in name.lower():
                    duplicates.append(f"{activity}.{category}.{name}")
    assert not duplicates, duplicates


def test_a_category_measured_by_an_attribute_is_not_also_sized():
    """The inverse: anything whose defining dimension is a typed schema field
    must not be offered the generic size box beside it."""
    measured = {"poles": "length_cm", "hydration": "volume_ml",
                "headlamp": "burn_time_h"}
    fields = ACTIVITIES["trail_running"]["gear"]
    for category, field in measured.items():
        assert field in fields[category], f"{category}.{field} went missing"
        assert not is_sized(category), category
