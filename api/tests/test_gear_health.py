"""Gear health (§12).

The rule this file exists to defend: NEVER PRESENT AN UNCERTAIN ESTIMATE AS A
GUARANTEED FAILURE POINT. Shoe lifespan genuinely varies by foam, mass, terrain
and how wet the shoe has been, and someone deciding whether to start 160 km of
technical limestone on a given pair deserves a range and a prompt rather than a
number that looks measured and is not.
"""
from __future__ import annotations

import pytest

from api.engines import gear_health as gh

SHOE = {"id": "s", "category_key": "shoes", "status": "active",
        "attributes": {"lifespan_km": 800}}


def totals(km: float, sessions: int = 10) -> dict:
    return {"distance_m": int(km * 1000), "sessions": sessions}


# ── the band, not a point ───────────────────────────────────────────────────

def test_the_expected_lifespan_is_a_range():
    low, high, source = gh.expected_band(SHOE)
    assert (low, high) == (640, 960)
    assert source == "item"


def test_an_items_own_lifespan_beats_the_category_default():
    """The owner knows which foam they bought; this module does not."""
    _, _, source = gh.expected_band(SHOE)
    assert source == "item"
    bare = {"category_key": "shoes", "status": "active", "attributes": {}}
    low, high, source = gh.expected_band(bare)
    assert source == "category_default"
    assert low < gh.DEFAULT_LIFESPAN_KM["shoes"] < high


def test_the_message_never_states_a_failure_point():
    """Across the whole range, no output may promise when something will
    break. 'Inspect' and 'plan a replacement' are prompts; 'will fail at
    780 km' is a claim nobody can support."""
    forbidden = ("will fail", "will break", "unsafe", "guaranteed",
                 "km remaining", "remaining km")
    for km in (0, 100, 400, 600, 700, 900, 1200, 5000):
        message = gh.evaluate(SHOE, totals(km)).message.lower()
        for phrase in forbidden:
            assert phrase not in message, f"{km} km: {message!r}"


def test_every_message_names_the_range_it_judged_against():
    """A prompt without its band is just an opinion."""
    for km in (100, 700, 1200):
        result = gh.evaluate(SHOE, totals(km))
        assert "640" in result.message and "960" in result.message


# ── states ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("km,state", [
    (0, gh.STATE_OK),
    (100, gh.STATE_OK),
    (479, gh.STATE_OK),        # just under 75% of the 640 low edge
    (480, gh.STATE_INSPECT),   # exactly 75% of the low edge
    (700, gh.STATE_INSPECT),
    (959, gh.STATE_INSPECT),
    (960, gh.STATE_PAST),      # the high edge itself
    (2000, gh.STATE_PAST),
])
def test_state_thresholds(km, state):
    assert gh.evaluate(SHOE, totals(km)).state == state


def test_inspect_fires_against_the_low_edge_not_the_midpoint():
    """The point of a band is that its early end is as plausible as its late
    one. A prompt that waits for the midpoint has already passed the case it
    exists to catch."""
    low, high, _ = gh.expected_band(SHOE)
    midpoint = (low + high) / 2
    assert gh.evaluate(SHOE, totals(low * gh.INSPECT_AT)).state == gh.STATE_INSPECT
    assert low * gh.INSPECT_AT < midpoint


def test_needs_attention_covers_inspect_and_past_only():
    assert not gh.evaluate(SHOE, totals(10)).needs_attention
    assert gh.evaluate(SHOE, totals(700)).needs_attention
    assert gh.evaluate(SHOE, totals(1500)).needs_attention


# ── condition_pct ───────────────────────────────────────────────────────────

def test_condition_is_clamped_and_never_negative():
    assert gh.evaluate(SHOE, totals(0)).condition_pct == 100
    assert gh.evaluate(SHOE, totals(10_000)).condition_pct == 0


def test_condition_falls_monotonically_with_use():
    values = [gh.evaluate(SHOE, totals(km)).condition_pct
              for km in (0, 100, 300, 600, 900)]
    assert values == sorted(values, reverse=True)


def test_condition_is_none_when_unknown_not_zero():
    """Zero would render as 'worn out' for a brand new item whose lifespan
    nobody has recorded — the exact false statement §12 forbids."""
    bare = {"category_key": "vest", "status": "active", "attributes": {}}
    result = gh.evaluate(bare, totals(0))
    assert result.state == gh.STATE_UNKNOWN
    assert result.condition_pct is None


# ── unknown is a real answer ────────────────────────────────────────────────

def test_a_category_that_does_not_accumulate_distance_is_unknown():
    lamp = {"category_key": "headlamp", "status": "active", "attributes": {}}
    result = gh.evaluate(lamp, totals(500))
    assert result.state == gh.STATE_UNKNOWN
    assert result.detail["reason"] == "not_distance_tracked"


def test_no_lifespan_and_no_default_is_unknown_and_says_what_is_missing():
    socks = {"category_key": "socks", "status": "active", "attributes": {}}
    result = gh.evaluate(socks, totals(400))
    assert result.state == gh.STATE_UNKNOWN
    assert result.detail["reason"] == "no_lifespan"
    assert "expected lifespan" in result.message


def test_defaults_exist_only_where_there_is_a_real_number_behind_them():
    """A default invented for a category nobody has measured is a guess wearing
    a threshold's clothes. Shoes are the one category with a figure the whole
    sport quotes; the rest deliberately return unknown."""
    assert set(gh.DEFAULT_LIFESPAN_KM) == {"shoes"}


def test_retired_gear_is_not_a_health_question():
    """'Inspect the outsole' on a pair already thrown out is noise, and noise
    is what makes real warnings easy to ignore."""
    for status in ("retired", "lost", "damaged"):
        result = gh.evaluate({**SHOE, "status": status}, totals(900))
        assert result.state == gh.STATE_UNKNOWN
        assert result.detail["reason"] == "not_active"


# ── provenance ──────────────────────────────────────────────────────────────

def test_every_result_carries_its_ruleset_version():
    """A stored condition figure with no ruleset is unrecognisable as stale
    after the thresholds move."""
    assert gh.evaluate(SHOE, totals(100)).ruleset == gh.HEALTH_RULESET


def test_detail_carries_the_numbers_that_were_compared():
    detail = gh.evaluate(SHOE, totals(640)).detail
    assert detail["used_km"] == 640
    assert detail["band_low_km"] == 640 and detail["band_high_km"] == 960
    assert detail["band_source"] == "item"


def test_no_usage_at_all_is_handled():
    assert gh.evaluate(SHOE, {}).state == gh.STATE_OK
