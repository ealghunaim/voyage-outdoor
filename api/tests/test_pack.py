"""Smart Pack classification and the kit matcher (§8, §9, §24).

Three rules this file defends:

  MANDATORY KIT IS NEVER DOWNGRADED. It is typed in from a race manual and no
  rule in the engine may argue with it.

  A LINE IS NEVER SILENTLY DROPPED. A kit requirement the matcher cannot place
  stays on the list, unmatched, because a gap in the keyword table is not
  permission to stop requiring something.

  IT IS NOT A SHOP. Recommendations the locker cannot fill are one note, not a
  column of MISSING rows — the first draft produced eight missing lines against
  five required ones and read like a checkout.
"""
from __future__ import annotations

import pytest

from api.engines import matching
from api.engines import pack
from api.engines.gear_health import HealthResult

OMAN_KIT = ["Headlamp + spare batteries", "Waterproof jacket, taped seams",
            "Survival blanket 1.4 x 2 m", "Whistle", "Mobile phone",
            "1 litre water capacity", "Elastic bandage"]


def item(id_, name, category, **attrs):
    extra = {k: attrs.pop(k) for k in ("favorite", "weight_g", "status", "brand")
             if k in attrs}
    return {"id": id_, "name": name, "category_key": category,
            "status": extra.get("status", "active"),
            "favorite": extra.get("favorite", False),
            "weight_g": extra.get("weight_g"), "brand": extra.get("brand"),
            "created_at": "2026-01-01", "attributes": attrs}


def adventure(**attrs):
    return {"id": "a", "attributes": attrs}


DAY = [{"forecast_date": "2027-02-04", "temp_min": 9, "temp_max": 26,
        "precip_prob": 15, "wind_kph": 22, "uv": 7, "provider": "open-meteo"}]


# ── the matcher ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line,category", [
    ("Headlamp + spare batteries", "headlamp"),
    ("Head torch", "headlamp"),
    ("Waterproof jacket, taped seams", "jacket"),
    ("Survival blanket 1.4 x 2 m", "safety"),
    ("Whistle", "safety"),
    ("Mobile phone", "electronics"),
    ("1 litre water capacity", "hydration"),
    ("Elastic bandage", "first_aid"),
    ("Emergency food reserve", "nutrition"),
    ("Compass", "navigation"),
])
def test_kit_lines_reach_the_right_category(line, category):
    assert matching.category_for(line) == category


def test_punctuation_and_case_do_not_change_the_match():
    for variant in ("HEADLAMP", "head-lamp", "Head  lamp / spare", "headlamp!"):
        assert matching.category_for(variant) == "headlamp"


def test_accents_are_stripped_before_matching():
    assert matching.category_for("Téléphone mobile phone") == "electronics"


def test_order_puts_the_specific_phrase_first():
    """'Waterproof jacket' must reach `jacket` rather than being caught by a
    looser pattern elsewhere in the table."""
    assert matching.category_for("Waterproof jacket") == "jacket"
    assert matching.category_for("Elastic bandage") == "first_aid"


def test_an_unrecognised_line_returns_none_rather_than_a_guess():
    assert matching.category_for("Ceremonial trebuchet") is None
    assert matching.category_for("") is None


def test_gear_selection_prefers_a_name_that_echoes_the_requirement():
    locker = [item("a", "Generic lamp", "headlamp", weight_g=50),
              item("b", "Whistle", "safety", weight_g=5)]
    gear, _ = matching.best_gear_for("Whistle", locker)
    assert gear["id"] == "b"


def test_gear_selection_prefers_favourites_then_the_lightest():
    locker = [item("heavy", "Heavy lamp", "headlamp", weight_g=300),
              item("light", "Light lamp", "headlamp", weight_g=90),
              item("fav", "Fav lamp", "headlamp", weight_g=200, favorite=True)]
    gear, _ = matching.best_gear_for("Headlamp", locker)
    assert gear["id"] == "fav"
    gear, _ = matching.best_gear_for("Headlamp",
                                     [g for g in locker if g["id"] != "fav"])
    assert gear["id"] == "light"


def test_retired_gear_is_never_offered():
    """'You already own one' is exactly wrong for a pair thrown out last year."""
    locker = [item("r", "Old lamp", "headlamp", status="retired", weight_g=50)]
    gear, category = matching.best_gear_for("Headlamp", locker)
    assert gear is None and category == "headlamp"


def test_selection_is_stable_across_row_order():
    a = item("a", "Lamp A", "headlamp", weight_g=100)
    b = item("b", "Lamp B", "headlamp", weight_g=100)
    first, _ = matching.best_gear_for("Headlamp", [a, b])
    second, _ = matching.best_gear_for("Headlamp", [b, a])
    assert first["id"] == second["id"]


# ── mandatory kit is untouchable ────────────────────────────────────────────

def test_every_mandatory_line_appears_and_is_critical():
    locker = [item("1", "Norda 005", "shoes", lug_depth_mm=4.5)]
    result = pack.generate(adventure(mandatory_kit=OMAN_KIT, distance_km=160),
                           locker, DAY)
    mandatory = [ln for ln in result.lines if ln.source == "mandatory"]
    assert len(mandatory) == len(OMAN_KIT)
    assert all(ln.critical for ln in mandatory)
    assert all(ln.classification in (pack.REQUIRED, pack.MISSING)
               for ln in mandatory)


def test_a_mandatory_line_the_matcher_cannot_place_still_appears():
    """A gap in the keyword table is not permission to drop a requirement."""
    result = pack.generate(
        adventure(mandatory_kit=["Ceremonial trebuchet"], distance_km=10), [], [])
    names = [ln.name for ln in result.lines]
    assert "Ceremonial trebuchet" in names
    line = next(ln for ln in result.lines if ln.name == "Ceremonial trebuchet")
    assert line.classification == pack.REQUIRED and line.critical
    assert any(w.key == "kit_unmatched" for w in result.warnings)


def test_mandatory_kit_is_not_downgraded_by_a_rule():
    """No darkness would normally mark a headlamp NOT NEEDED. The race says
    carry one, so the race wins."""
    locker = [item("h", "Swift RL", "headlamp", burn_time_h=10)]
    result = pack.generate(
        adventure(mandatory_kit=["Headlamp"], night_hours=0, distance_km=20),
        locker, [])
    line = next(ln for ln in result.lines if ln.gear_item_id == "h")
    assert line.classification == pack.REQUIRED
    assert line.critical


def test_a_mandatory_item_you_do_not_own_is_missing_and_warned():
    result = pack.generate(adventure(mandatory_kit=["Whistle"], distance_km=10),
                           [], [])
    line = next(ln for ln in result.lines if ln.category_key == "safety")
    assert line.classification == pack.MISSING and line.critical
    assert any(w.severity == "critical" and "Whistle" in w.message
               for w in result.warnings)


# ── it is not a shop ────────────────────────────────────────────────────────

def test_unowned_recommendations_are_one_note_not_a_column_of_missing_rows():
    """§8 and §14. The first draft of this engine listed every unowned
    recommendation as MISSING and read like a checkout."""
    locker = [item("1", "Norda 005", "shoes", lug_depth_mm=4.5)]
    result = pack.generate(
        adventure(distance_km=100, elevation_gain_m=4000, expected_hours=20,
                  technicality="technical", terrain=["mountain"]),
        locker, DAY)
    missing = [ln for ln in result.lines if ln.classification == pack.MISSING]
    # Poles and navigation are recommended and unowned; neither may be a line.
    assert not any(ln.category_key in ("poles", "navigation") for ln in missing)
    note = next(w for w in result.warnings if w.key == "could_help")
    assert "poles" in note.message and note.severity == "note"


def test_no_line_or_warning_ever_says_buy():
    """§14: the willingness to say 'you do not need to buy this' is the trust
    anchor, and it does not survive an engine that says 'buy' anywhere."""
    result = pack.generate(
        adventure(mandatory_kit=OMAN_KIT, distance_km=160, expected_hours=30,
                  night_hours=11, elevation_gain_m=9000, terrain=["mountain"]),
        [item("1", "Norda 005", "shoes", lug_depth_mm=4.5)], DAY)
    text = " ".join([ln.reason for ln in result.lines]
                    + [w.message for w in result.warnings]).lower()
    for word in ("buy", "purchase", "shop", "order one", "£", "$"):
        assert word not in text, f"found {word!r}"


def test_a_required_rule_you_cannot_fill_is_still_missing():
    """The shop rule applies to recommendations, not requirements. If the
    engine says you must carry water, not owning any is a real gap."""
    result = pack.generate(adventure(distance_km=40, expected_hours=6), [], [])
    missing = {ln.category_key for ln in result.lines
               if ln.classification == pack.MISSING}
    assert "hydration" in missing


# ── the rules ───────────────────────────────────────────────────────────────

def test_darkness_requires_a_headlamp_and_marks_it_critical():
    locker = [item("h", "Swift RL", "headlamp", burn_time_h=15)]
    result = pack.generate(adventure(distance_km=80, night_hours=6), locker, [])
    line = next(ln for ln in result.lines if ln.gear_item_id == "h")
    assert line.classification == pack.REQUIRED and line.critical
    assert "6 h" in line.reason


def test_no_darkness_marks_an_owned_headlamp_not_needed():
    """A rule that actively says 'leave it' is worth as much as one that says
    'bring it' — it is the difference between a pack list and an inventory."""
    locker = [item("h", "Swift RL", "headlamp", burn_time_h=15)]
    result = pack.generate(adventure(distance_km=20, night_hours=0), locker, [])
    line = next(ln for ln in result.lines if ln.gear_item_id == "h")
    assert line.classification == pack.NOT_NEEDED


def test_rain_in_the_forecast_requires_a_shell():
    wet = [{**DAY[0], "precip_prob": 80}]
    locker = [item("j", "Ultra Jacket", "jacket", hydrostatic_head_mm=20000)]
    result = pack.generate(adventure(distance_km=30), locker, wet)
    line = next(ln for ln in result.lines if ln.gear_item_id == "j")
    assert line.classification == pack.REQUIRED
    assert "80" in line.reason


def test_a_null_rain_probability_does_not_fire_or_suppress_the_rule():
    """MET Norway carries no precipitation probability. Reading its absence as
    0% would tell someone it will not rain because the provider had no
    opinion."""
    silent = [{**DAY[0], "precip_prob": None, "provider": "met-no"}]
    locker = [item("j", "Ultra Jacket", "jacket", hydrostatic_head_mm=20000)]
    result = pack.generate(adventure(distance_km=30), locker, silent)
    line = next(ln for ln in result.lines if ln.gear_item_id == "j")
    assert line.classification == pack.OPTIONAL
    assert pack.summarise_weather(silent)["precip_prob"] is None


def test_weather_summary_takes_extremes_across_days_and_skips_nulls():
    days = [{"temp_min": 2, "temp_max": 10, "precip_prob": None, "wind_kph": 10},
            {"temp_min": 8, "temp_max": 25, "precip_prob": 70, "wind_kph": None}]
    wx = pack.summarise_weather(days)
    assert wx["temp_min"] == 2 and wx["temp_max"] == 25
    assert wx["precip_prob"] == 70 and wx["wind_kph"] == 10


def test_no_forecast_at_all_is_said_out_loud():
    result = pack.generate(adventure(distance_km=20), [], [])
    assert any(w.key == "no_forecast" for w in result.warnings)


# ── warnings from the other engines ─────────────────────────────────────────

def test_a_compatibility_refusal_on_packed_gear_becomes_a_warning():
    locker = [item("h", "Swift RL", "headlamp", burn_time_h=10)]
    result = pack.generate(adventure(distance_km=160, night_hours=11), locker, [])
    assert any(w.rule_key == "headlamp_night" and w.severity == "caution"
               for w in result.warnings)


def test_worn_gear_on_the_list_becomes_a_warning():
    locker = [item("s", "Norda 005", "shoes", lug_depth_mm=4.5)]
    health = {"s": HealthResult("inspect", 20, "620 km recorded.",
                                detail={"used_km": 620})}
    result = pack.generate(adventure(distance_km=160), locker, [], health=health)
    assert any(w.rule_key == "gear_health" for w in result.warnings)


def test_health_warnings_are_not_raised_for_gear_not_on_the_list():
    """Warning about a worn pair you are not taking is noise, and noise is
    what makes the real warnings easy to skip."""
    locker = [item("s", "Norda 005", "shoes", lug_depth_mm=4.5),
              item("s2", "Old pair", "shoes", lug_depth_mm=4.5)]
    health = {"s2": HealthResult("past_expected", 0, "Past its range.")}
    result = pack.generate(adventure(distance_km=160), locker, [], health=health)
    assert not any(w.gear_item_id == "s2" for w in result.warnings)


def test_missing_compatibility_data_is_a_note_not_a_caution():
    locker = [item("h", "Swift RL", "headlamp")]
    result = pack.generate(adventure(distance_km=160, night_hours=11), locker, [])
    unknown = [w for w in result.warnings if w.key.startswith("unknown_")]
    assert unknown and all(w.severity == "note" for w in unknown)


# ── shape and provenance ────────────────────────────────────────────────────

def test_every_line_carries_a_rule_key_and_a_reason():
    result = pack.generate(
        adventure(mandatory_kit=OMAN_KIT, distance_km=160, expected_hours=30,
                  night_hours=11), [item("1", "Norda", "shoes")], DAY)
    for line in result.lines:
        assert line.rule_key and line.reason


def test_the_snapshot_records_every_ruleset_version():
    """A list generated three months ago against thresholds that have since
    moved must be recognisable as stale."""
    snapshot = pack.generate(adventure(distance_km=10), [], []).snapshot
    assert snapshot["ruleset"] == pack.PACK_RULESET
    assert snapshot["compat_ruleset"] and snapshot["match_ruleset"]


def test_one_gear_item_is_never_on_the_list_twice():
    locker = [item("h", "Swift RL", "headlamp", burn_time_h=15)]
    result = pack.generate(
        adventure(mandatory_kit=["Headlamp"], night_hours=8, distance_km=50),
        locker, [])
    used = [ln.gear_item_id for ln in result.lines if ln.gear_item_id]
    assert len(used) == len(set(used))


def test_owned_gear_no_rule_mentions_is_offered_as_optional():
    locker = [item("x", "Buff", "headwear")]
    result = pack.generate(adventure(distance_km=10), locker, [])
    line = next(ln for ln in result.lines if ln.gear_item_id == "x")
    assert line.classification == pack.OPTIONAL


def test_retired_gear_never_reaches_the_list():
    locker = [item("r", "Old shoes", "shoes", status="retired")]
    result = pack.generate(adventure(distance_km=10), locker, [])
    assert not any(ln.gear_item_id == "r" for ln in result.lines)


def test_generation_is_deterministic():
    """Same inputs, same pack — the property that makes an engine auditable."""
    args = (adventure(mandatory_kit=OMAN_KIT, distance_km=160, night_hours=11,
                      expected_hours=30),
            [item("1", "Norda", "shoes", lug_depth_mm=4.5),
             item("2", "Swift", "headlamp", burn_time_h=10)], DAY)
    first = pack.generate(*args)
    second = pack.generate(*args)
    assert [ln.__dict__ for ln in first.lines] == [ln.__dict__ for ln in second.lines]


# ── readiness (§9) ──────────────────────────────────────────────────────────

def line(classification, state="not_selected", critical=False):
    return {"classification": classification, "state": state, "critical": critical}


def test_readiness_counts_only_required_items():
    """A percentage that fell because someone declined a spare buff would mean
    nothing at the moment it matters most."""
    items = [line(pack.REQUIRED, "packed"), line(pack.REQUIRED, "not_selected"),
             line(pack.OPTIONAL, "not_selected")]
    r = pack.readiness(items)
    assert r["required_total"] == 2 and r["percent"] == 50


def test_verified_counts_as_packed_but_is_also_counted_separately():
    items = [line(pack.REQUIRED, "verified"), line(pack.REQUIRED, "packed")]
    r = pack.readiness(items)
    assert r["required_packed"] == 2 and r["required_verified"] == 1


def test_critical_items_are_reported_separately_not_folded_in():
    """'43 of 47 packed' and 'one critical item unverified' are different
    facts, and the second is the one that ends a race at a kit check."""
    items = [line(pack.REQUIRED, "packed", critical=True),
             line(pack.REQUIRED, "packed")]
    r = pack.readiness(items)
    assert r["percent"] == 100
    assert r["critical_unverified"] == 1
    assert r["ready"] is False


def test_ready_requires_everything_packed_verified_and_nothing_missing():
    assert pack.readiness([line(pack.REQUIRED, "verified", critical=True)])["ready"]
    assert not pack.readiness([line(pack.REQUIRED, "verified", critical=True),
                               line(pack.MISSING)])["ready"]


def test_an_empty_pack_is_not_a_ready_one():
    """Rendering 100% over an unplanned adventure is the false reassurance §12
    exists to prevent."""
    r = pack.readiness([])
    assert r["percent"] is None and r["ready"] is False
