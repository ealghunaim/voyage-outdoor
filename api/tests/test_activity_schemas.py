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

from api.activities.registry import (ACTIVITIES, BUILT, SCHEMA_VERSION,
                                     adventure_fields, gear_fields, schema_for)
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


def test_only_trail_running_is_built():
    """A built activity has screens behind it. Three of these do not, and the
    app must not offer them — an option that leads nowhere is worse than no
    option. Guards against someone flipping a flag to 'try it out'."""
    assert BUILT == ("trail_running",)


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
    "fishing":       ("reel", {"size": "14000", "drag_kg": 25.0,
                               "gear_ratio": "5.7:1"}),
    "fly_fishing":   ("fly_rod", {"length_ft": 9.0, "line_weight": 8,
                                  "pieces": 4, "action": "fast"}),
}

REPRESENTATIVE_ADVENTURE = {
    "trail_running": {"distance_km": 160, "elevation_gain_m": 9000,
                      "expected_hours": 30, "technicality": "technical",
                      "terrain": ["mountain", "technical"],
                      "mandatory_kit": ["Headlamp", "Space blanket", "Whistle"]},
    "hiking":        {"distance_km": 82, "days": 5, "shelter_type": "tent"},
    "fishing":       {"water_type": "offshore", "technique": ["popping", "jigging"],
                      "target_species": ["GT", "Dogtooth tuna"]},
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
    for the land activities, water type for the two fishing ones. More than one
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
