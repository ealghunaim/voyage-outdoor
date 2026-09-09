"""The attribute validator — the only way attributes are ever written.

The database column is plain jsonb with no constraint (0001, deliberately), so
these rules are the whole enforcement. Each one is tested because each one is a
decision someone could reasonably reverse without noticing what it protected.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.activities.validate import (validate_adventure_attributes,
                                     validate_gear_attributes)

SHOES = ("trail_running", "shoes")


def gear(payload, **kw):
    return validate_gear_attributes(*SHOES, payload, **kw)


# ── unknown keys ────────────────────────────────────────────────────────────

def test_unknown_keys_are_dropped_not_rejected():
    """A client one release ahead sends a field this build has never heard of.
    Rejecting the write turns a new optional field into an outage for older
    servers; dropping it loses one value."""
    out = gear({"stack_height_mm": 33, "quantum_flux": 9})
    assert out == {"stack_height_mm": 33}


# ── types ───────────────────────────────────────────────────────────────────

def test_numeric_text_is_accepted():
    """Form fields arrive as strings. Refusing "33" would mean every client had
    to know which fields to cast, and one of them would forget."""
    assert gear({"stack_height_mm": "33"}) == {"stack_height_mm": 33}
    assert gear({"lug_depth_mm": "4.5"}) == {"lug_depth_mm": 4.5}


def test_non_numeric_text_is_rejected_with_the_field_name():
    with pytest.raises(HTTPException) as e:
        gear({"stack_height_mm": "quite tall"})
    assert "stack_height_mm" in e.value.detail
    assert e.value.status_code == 422


def test_bool_is_not_a_number():
    """True == 1 in Python, so an unguarded int() accepts it and stores a stack
    height of 1mm that nobody typed."""
    with pytest.raises(HTTPException):
        gear({"stack_height_mm": True})


def test_bool_accepts_the_strings_forms_actually_send():
    assert gear({"waterproof": "true"}) == {"waterproof": True}
    assert gear({"waterproof": "0"}) == {"waterproof": False}
    with pytest.raises(HTTPException):
        gear({"waterproof": "maybe"})


# ── null clears ─────────────────────────────────────────────────────────────

def test_explicit_null_drops_the_key():
    """This is how a value gets un-set. Without it an attribute could be
    written and never withdrawn."""
    assert gear({"stack_height_mm": None, "drop_mm": 6}) == {"drop_mm": 6}


# ── ranges ──────────────────────────────────────────────────────────────────

def test_out_of_range_is_refused_at_both_ends():
    with pytest.raises(HTTPException) as e:
        gear({"stack_height_mm": 610})       # the 61mm typo
    assert "at most" in e.value.detail
    with pytest.raises(HTTPException):
        gear({"drop_mm": -3})


def test_bounds_are_inclusive():
    assert gear({"drop_mm": 0}) == {"drop_mm": 0}
    assert gear({"drop_mm": 20}) == {"drop_mm": 20}


# ── enums ───────────────────────────────────────────────────────────────────

def test_enum_rejects_a_value_outside_its_options():
    with pytest.raises(HTTPException) as e:
        gear({"cushioning": "plush"})
    assert "minimal" in e.value.detail          # the message lists the options


def test_multi_enum_preserves_order_and_drops_duplicates():
    out = gear({"terrain": ["technical", "mountain", "technical"]})
    assert out["terrain"] == ["technical", "mountain"]


def test_multi_enum_rejects_one_bad_member():
    with pytest.raises(HTTPException) as e:
        gear({"terrain": ["mountain", "lava"]})
    assert "lava" in e.value.detail


def test_multi_enum_needs_a_list():
    with pytest.raises(HTTPException):
        gear({"terrain": "mountain"})


# ── string lists ────────────────────────────────────────────────────────────

def test_string_list_trims_and_drops_blanks():
    out = validate_adventure_attributes(
        "trail_running",
        {"distance_km": 42, "mandatory_kit": ["  Headlamp ", "", "Whistle"]})
    assert out["mandatory_kit"] == ["Headlamp", "Whistle"]


def test_string_list_rejects_non_text_members():
    with pytest.raises(HTTPException):
        validate_adventure_attributes(
            "trail_running", {"distance_km": 42, "mandatory_kit": ["Headlamp", 7]})


# ── shape ───────────────────────────────────────────────────────────────────

def test_missing_payload_is_an_empty_dict_not_a_crash():
    assert validate_gear_attributes("trail_running", "shoes", None) == {}


def test_non_object_payload_is_refused():
    with pytest.raises(HTTPException):
        validate_gear_attributes("trail_running", "shoes", ["stack_height_mm"])


def test_strings_are_clipped_rather_than_refused():
    out = gear({"outsole": "x" * 500})
    assert len(out["outsole"]) == 200
