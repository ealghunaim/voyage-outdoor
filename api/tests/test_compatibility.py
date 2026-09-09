"""The compatibility engine (§11).

The rule this file defends: UNKNOWN IS NOT A SOFT YES. A headlamp with no
recorded burn time is not "probably fine for eleven hours of darkness" — it is
a headlamp nobody has measured. Every rule that would have to guess returns
`unknown` and names the field it needed.
"""
from __future__ import annotations

import pytest

from api.engines import compatibility as compat


def adv(**attrs) -> dict:
    return {"attributes": attrs}


def gear(category: str, **attrs) -> dict:
    return {"id": "g", "category_key": category, "status": "active",
            "attributes": attrs}


# ── shoe ↔ terrain ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("lug,state", [
    (5.0, compat.COMPATIBLE),
    (3.5, compat.COMPATIBLE),      # exactly the threshold
    (3.0, compat.POSSIBLY),
    (2.5, compat.POSSIBLY),        # exactly the marginal edge
    (2.4, compat.NOT_RECOMMENDED),
    (1.0, compat.NOT_RECOMMENDED),
])
def test_lug_depth_against_technical_terrain(lug, state):
    verdict = compat.shoe_terrain(gear("shoes", lug_depth_mm=lug),
                                  adv(terrain=["mountain", "technical"]))
    assert verdict.state == state
    assert verdict.detail["lug_depth_mm"] == lug


def test_non_technical_terrain_does_not_care_about_tread():
    """A road shoe on a canal path is not a compatibility problem, and
    flagging it would train people to ignore the ones that are."""
    verdict = compat.shoe_terrain(gear("shoes", lug_depth_mm=1.0),
                                  adv(terrain=["road"]))
    assert verdict.state == compat.COMPATIBLE


def test_no_terrain_recorded_is_unknown_not_a_pass():
    verdict = compat.shoe_terrain(gear("shoes", lug_depth_mm=1.0), adv())
    assert verdict.state == compat.UNKNOWN
    assert "adventure.terrain" in verdict.detail["missing"]


def test_no_lug_depth_recorded_is_unknown_and_names_the_field():
    verdict = compat.shoe_terrain(gear("shoes"), adv(terrain=["technical"]))
    assert verdict.state == compat.UNKNOWN
    assert verdict.detail["missing"] == ["gear.lug_depth_mm"]


# ── headlamp ↔ darkness ─────────────────────────────────────────────────────

def test_burn_time_must_beat_darkness_by_a_margin():
    """Batteries fade in the cold and burn time is quoted at a brightness
    nobody runs at. The margin is a discount on the manufacturer's number, not
    padding."""
    assert compat.headlamp_night(gear("headlamp", burn_time_h=15),
                                 adv(night_hours=11)).state == compat.COMPATIBLE
    # 11 h needs 13.75 h to clear the margin; 12 covers the hours with nothing
    # spare, which is the case `possibly` exists for.
    assert compat.headlamp_night(gear("headlamp", burn_time_h=12),
                                 adv(night_hours=11)).state == compat.POSSIBLY
    assert compat.headlamp_night(gear("headlamp", burn_time_h=10),
                                 adv(night_hours=11)).state == compat.NOT_RECOMMENDED


def test_the_marginal_case_says_carry_a_spare():
    verdict = compat.headlamp_night(gear("headlamp", burn_time_h=11.5),
                                    adv(night_hours=11))
    assert verdict.state == compat.POSSIBLY
    assert "spare" in verdict.message.lower()


def test_no_darkness_is_compatible_with_any_lamp():
    assert compat.headlamp_night(gear("headlamp", burn_time_h=2),
                                 adv(night_hours=0)).state == compat.COMPATIBLE


def test_unrecorded_burn_time_is_unknown_not_optimism():
    verdict = compat.headlamp_night(gear("headlamp", lumens=1100),
                                    adv(night_hours=11))
    assert verdict.state == compat.UNKNOWN
    assert verdict.detail["missing"] == ["gear.burn_time_h"]


def test_the_verdict_shows_the_arithmetic():
    verdict = compat.headlamp_night(gear("headlamp", burn_time_h=10),
                                    adv(night_hours=11))
    assert verdict.detail["needed_h"] == 13.8
    assert verdict.detail["burn_time_h"] == 10
    assert verdict.detail["night_hours"] == 11


# ── vest ↔ required kit ─────────────────────────────────────────────────────

def test_capacity_against_a_kit_list():
    seven = ["a", "b", "c", "d", "e", "f", "g"]          # 4.2 L needed
    assert compat.vest_capacity(gear("vest", capacity_l=12),
                                adv(mandatory_kit=seven)).state == compat.COMPATIBLE
    assert compat.vest_capacity(gear("vest", capacity_l=2),
                                adv(mandatory_kit=seven)).state == compat.NOT_RECOMMENDED


def test_self_support_adds_required_volume():
    """Two kit items need 1.2 L; carrying your own food and water for the day
    adds 3 L on top. A 3 L vest is fine for the first and short for the
    second, which is the whole point of the rule."""
    kit = ["a", "b"]
    loose = compat.vest_capacity(gear("vest", capacity_l=3), adv(mandatory_kit=kit))
    tight = compat.vest_capacity(gear("vest", capacity_l=3),
                                 adv(mandatory_kit=kit, self_supported=True))
    assert loose.detail["needed_l"] == 1.2
    assert tight.detail["needed_l"] == 4.2
    assert loose.state == compat.COMPATIBLE
    assert tight.state == compat.NOT_RECOMMENDED


def test_nothing_to_carry_is_unknown_rather_than_a_pass():
    """No kit list and no self-support means there is no required volume — so
    the rule has nothing to check, which is not the same as approving."""
    assert compat.vest_capacity(gear("vest", capacity_l=4),
                                adv()).state == compat.UNKNOWN


# ── waterproof ↔ race rules ─────────────────────────────────────────────────

WET_KIT = ["Waterproof jacket, taped seams"]


def test_an_explicit_race_legal_flag_wins_over_any_inference():
    """That flag is the owner having read their own race manual, which beats
    anything this rule could infer from a spec sheet."""
    verdict = compat.jacket_race_legal(
        gear("jacket", race_legal=True, hydrostatic_head_mm=5000),
        adv(mandatory_kit=WET_KIT))
    assert verdict.state == compat.COMPATIBLE


def test_race_legal_false_is_refused_even_with_a_good_spec():
    verdict = compat.jacket_race_legal(
        gear("jacket", race_legal=False, hydrostatic_head_mm=30000),
        adv(mandatory_kit=WET_KIT))
    assert verdict.state == compat.NOT_RECOMMENDED


@pytest.mark.parametrize("head,state", [
    (20000, compat.COMPATIBLE),
    (10000, compat.COMPATIBLE),          # exactly the usual minimum
    (9000, compat.NOT_RECOMMENDED),
    (5000, compat.NOT_RECOMMENDED),
])
def test_hydrostatic_head_against_the_usual_race_minimum(head, state):
    verdict = compat.jacket_race_legal(gear("jacket", hydrostatic_head_mm=head),
                                       adv(mandatory_kit=WET_KIT))
    assert verdict.state == state


def test_a_shell_with_no_spec_and_a_mandated_waterproof_is_unknown():
    verdict = compat.jacket_race_legal(gear("jacket"), adv(mandatory_kit=WET_KIT))
    assert verdict.state == compat.UNKNOWN
    assert "gear.hydrostatic_head_mm" in verdict.detail["missing"]


def test_a_jacket_marked_not_waterproof_is_refused_outright():
    verdict = compat.jacket_race_legal(gear("jacket", waterproof=False),
                                       adv(mandatory_kit=WET_KIT))
    assert verdict.state == compat.NOT_RECOMMENDED


def test_no_waterproof_mandated_means_nothing_to_enforce():
    verdict = compat.jacket_race_legal(gear("jacket"), adv(mandatory_kit=["Whistle"]))
    assert verdict.state == compat.COMPATIBLE


# ── the shape of the engine ─────────────────────────────────────────────────

def test_a_category_with_no_rules_produces_no_verdicts():
    """Silence is not approval, and nothing downstream reads an absent verdict
    as a pass."""
    assert compat.evaluate(gear("nutrition", calories=100),
                           adv(terrain=["technical"])) == []


def test_every_verdict_carries_a_ruleset_and_a_message():
    verdicts = compat.evaluate(gear("shoes", lug_depth_mm=4),
                               adv(terrain=["technical"]))
    assert verdicts
    for verdict in verdicts:
        assert verdict.ruleset == compat.COMPAT_RULESET
        assert verdict.message and verdict.rule_key


def test_evaluate_all_skips_items_with_no_applicable_rule():
    locker = [gear("shoes", lug_depth_mm=4), {**gear("nutrition"), "id": "n"}]
    out = compat.evaluate_all(locker, adv(terrain=["technical"]))
    assert set(out) == {"g"}


def test_booleans_are_not_accepted_as_numbers():
    """True == 1 in Python, so an unguarded comparison would read a boolean as
    a 1 mm lug depth and produce a confident wrong answer."""
    verdict = compat.shoe_terrain(gear("shoes", lug_depth_mm=True),
                                  adv(terrain=["technical"]))
    assert verdict.state == compat.UNKNOWN


def test_is_problem_flags_only_refusals():
    bad = compat.headlamp_night(gear("headlamp", burn_time_h=1), adv(night_hours=11))
    unknown = compat.headlamp_night(gear("headlamp"), adv(night_hours=11))
    assert bad.is_problem
    assert not unknown.is_problem
