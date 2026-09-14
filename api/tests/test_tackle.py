"""Tackle compatibility — the gear↔gear rules, and the dispatch that guards them.

THE FIRST TEST IN THIS FILE IS THE POINT OF PHASE 7. Before the activity
dispatch existed, a fishing expedition to an uninhabited island was told it was
missing running shoes. It was unreachable in production — the adventures router
refuses an unbuilt activity — but it became reachable the moment fishing was
marked built, which is why the fix and the flag ship together.

Every threshold these assert against is an ASSUMED DEFAULT (§0.5), not a
measured fact: standard tackle practice, written down so it can be corrected by
somebody holding the gear.
"""
import pytest

from api.engines import pack, tackle
from api.engines.compatibility import (
    COMPATIBLE, NOT_RECOMMENDED, POSSIBLY, UNKNOWN,
)


def gear(gid, name, category, **attrs):
    return {"id": gid, "name": name, "category_key": category,
            "status": "active", "attributes": attrs}


# The Abd al Kuri kit. USER-SUPPLIED specs, unverified — see the module note.
STELLA = gear("reel1", "Stella 18000HG", "reel", size="18000",
              size_class="extra_heavy", drag_kg=25.0, pe_capacity=8.0,
              technique=["popping", "jigging"])
POP_ROD = gear("rod1", "GT popping rod", "rod", technique=["popping"],
               length_ft=8.0, pe_min=6.0, pe_max=10.0,
               cast_weight_min_g=100.0, cast_weight_max_g=150.0)
JIG_ROD = gear("rod2", "Jigging rod", "rod", technique=["jigging"],
               length_ft=5.9, pe_min=4.0, pe_max=6.0, jig_weight_max_g=300.0)
PE8 = gear("line1", "PE8 braid", "line", kind="braid", pe=8.0, lb_test=100.0)
LEADER = gear("lead1", "130 lb fluoro", "leader", kind="fluoro", lb_test=130.0)
POPPER = gear("lure1", "Popper 130 g", "lure", technique=["popping"],
              weight_g=130.0, kind="popper")

ABD_AL_KURI = {
    "id": "f1", "title": "Abd al Kuri", "activity_key": "fishing",
    "attributes": {"trip_type": "camp_shore", "days": 8, "remote": True,
                   "water": "reef", "technique": ["popping", "jigging"],
                   "target_species": ["Giant trevally"], "boat_hours": 40},
}


def states(verdicts):
    return {v.rule_key: v.state for v in verdicts}


# ── the regression this phase exists to prevent ─────────────────────────────

def test_a_fishing_trip_is_never_told_it_is_missing_running_shoes():
    """The bug, written down. pack.generate() called the trail-running rule
    table unconditionally, so every activity got it."""
    result = pack.generate(ABD_AL_KURI, [], [])
    blob = " ".join(f"{ln.name} {ln.reason}" for ln in result.lines).lower()
    assert "running" not in blob
    assert "shoes" not in blob
    assert not any(ln.rule_key.startswith("shoes_") for ln in result.lines)


def test_trail_running_rules_are_unchanged_by_the_dispatch():
    trail = {"id": "t1", "activity_key": "trail_running",
             "attributes": {"distance_km": 160, "expected_hours": 30,
                            "night_hours": 11}}
    result = pack.generate(trail, [], [])
    keys = {ln.rule_key for ln in result.lines}
    assert "shoes_always" in keys
    assert "headlamp_darkness" in keys


def test_an_activity_with_no_rules_says_so_rather_than_looking_sparse():
    """Short and 'the rules decided you need very little' look identical, and
    the second is the most reassuring possible way to be wrong."""
    hiking = {"id": "h1", "activity_key": "hiking", "attributes": {"days": 5}}
    result = pack.generate(hiking, [], [])
    assert any(w.key == "no_rules" for w in result.warnings)
    assert not result.lines


def test_fishing_marks_the_line_and_leader_critical():
    """§24 without an organiser's list: REQUIRED comes from the trip, and the
    parts that fail at the fish end are the critical ones."""
    result = pack.generate(ABD_AL_KURI, [], [])
    critical = {ln.category_key for ln in result.lines if ln.critical}
    assert {"line", "leader", "terminal_tackle"} <= critical


def test_remoteness_is_this_disciplines_self_support():
    near = {**ABD_AL_KURI,
            "attributes": {**ABD_AL_KURI["attributes"], "remote": False}}
    remote_keys = {ln.rule_key for ln in pack.generate(ABD_AL_KURI, [], []).lines}
    near_keys = {ln.rule_key for ln in pack.generate(near, [], []).lines}
    assert "safety_remote" in remote_keys
    assert "safety_remote" not in near_keys


# ── rod ↔ line ──────────────────────────────────────────────────────────────

def test_pe8_on_a_pe6_10_rod_is_fine():
    v = tackle.rod_line_pe({"rod": POP_ROD, "line": PE8})
    assert v.state == COMPATIBLE
    assert v.roles == ("rod", "line")


def test_pe8_on_a_jigging_rod_rated_to_pe6_is_refused():
    v = tackle.rod_line_pe({"rod": JIG_ROD, "line": PE8})
    assert v.state == NOT_RECOMMENDED
    assert "blank" in v.message


def test_half_a_step_over_is_marginal_not_wrong():
    pe65 = gear("l2", "PE6.5", "line", pe=6.5, lb_test=80.0)
    assert tackle.rod_line_pe({"rod": JIG_ROD, "line": pe65}).state == POSSIBLY


def test_too_light_and_too_heavy_are_different_sentences():
    light = gear("l3", "PE2", "line", pe=2.0, lb_test=30.0)
    over = tackle.rod_line_pe({"rod": JIG_ROD, "line": PE8})
    under = tackle.rod_line_pe({"rod": POP_ROD, "line": light})
    assert over.message != under.message
    assert "not load" in under.message


# ── reel ↔ line ─────────────────────────────────────────────────────────────

def test_a_reel_rated_to_pe8_takes_pe8():
    assert tackle.reel_line_pe({"reel": STELLA, "line": PE8}).state == COMPATIBLE


def test_a_small_reel_cannot_hold_heavy_braid():
    small = gear("r2", "4000", "reel", pe_capacity=2.0, drag_kg=11.0)
    v = tackle.reel_line_pe({"reel": small, "line": PE8})
    assert v.state == NOT_RECOMMENDED
    assert "capacity" in v.message


def test_drag_is_judged_against_what_the_line_can_fish():
    """25 kg against 100 lb line, which fishes about 15 kg at a third."""
    v = tackle.drag_vs_line({"reel": STELLA, "line": PE8})
    assert v.state == COMPATIBLE
    assert v.detail["fishable_drag_kg"] == pytest.approx(15.1, abs=0.2)


def test_an_under_gunned_reel_is_the_direction_that_matters():
    """A reel whose maximum exceeds the line is just something you do not wind
    up. A reel that cannot reach fishable drag makes the line's strength
    unreachable."""
    weak = gear("r3", "Small reel", "reel", pe_capacity=8.0, drag_kg=7.0)
    v = tackle.drag_vs_line({"reel": weak, "line": PE8})
    assert v.state == NOT_RECOMMENDED
    assert "stronger than the reel" in v.message


# ── line ↔ leader ───────────────────────────────────────────────────────────

def test_the_standard_gt_rig_is_not_flagged_as_marginal():
    """130 lb fluoro on PE8 braid is the ordinary rig here, not a compromise.
    The threshold was 1.5 until this test called it marginal — a rule that warns
    about standard practice teaches people to ignore the warnings."""
    v = tackle.leader_vs_main({"line": PE8, "leader": LEADER})
    assert v.state == COMPATIBLE
    assert v.detail["ratio"] == pytest.approx(1.3, abs=0.01)


def test_an_equal_leader_holds_but_has_no_margin():
    equal = gear("lead2", "100 lb", "leader", lb_test=100.0)
    v = tackle.leader_vs_main({"line": PE8, "leader": equal})
    assert v.state == POSSIBLY
    assert "abrasion" in v.message


def test_a_lighter_leader_puts_the_weak_point_at_the_fish():
    light = gear("lead3", "60 lb", "leader", lb_test=60.0)
    v = tackle.leader_vs_main({"line": PE8, "leader": light})
    assert v.state == NOT_RECOMMENDED
    assert "fish end" in v.message


# ── rod ↔ lure ──────────────────────────────────────────────────────────────

def test_a_130g_popper_suits_a_100_150g_rod():
    assert tackle.lure_vs_rod({"rod": POP_ROD, "lure": POPPER}).state == COMPATIBLE


def test_a_jig_is_judged_against_the_jig_rating_not_the_casting_window():
    """Weighing a 250 g jig against a casting window is a category error — the
    rod never throws it."""
    jig = gear("lure2", "250 g jig", "lure", weight_g=250.0, kind="jig",
               technique=["jigging"])
    v = tackle.lure_vs_rod({"rod": JIG_ROD, "lure": jig})
    assert v.state == COMPATIBLE
    assert "jig_max_g" in v.detail and "cast_max_g" not in v.detail


def test_too_heavy_breaks_and_too_light_only_casts_short():
    heavy = gear("lure3", "300 g popper", "lure", weight_g=300.0, kind="popper")
    light = gear("lure4", "40 g popper", "lure", weight_g=40.0, kind="popper")
    assert tackle.lure_vs_rod({"rod": POP_ROD, "lure": heavy}).state == NOT_RECOMMENDED
    assert tackle.lure_vs_rod({"rod": POP_ROD, "lure": light}).state == POSSIBLY


# ── technique ───────────────────────────────────────────────────────────────

def test_a_jigging_rod_on_a_popping_only_trip_is_flagged():
    popping_only = {**ABD_AL_KURI,
                    "attributes": {**ABD_AL_KURI["attributes"],
                                   "technique": ["popping"]}}
    v = tackle.technique_match({"rod": JIG_ROD}, popping_only)
    assert v.state == NOT_RECOMMENDED
    assert "jigging" in v.message


def test_a_trip_doing_both_accepts_either_rod():
    for rod in (POP_ROD, JIG_ROD):
        v = tackle.technique_match({"rod": rod}, ABD_AL_KURI)
        assert v.state == COMPATIBLE


def test_gear_with_no_technique_recorded_is_unknown_not_wrong():
    plain = gear("rod9", "Unlabelled rod", "rod", length_ft=8.0)
    v = tackle.technique_match({"rod": plain}, ABD_AL_KURI)
    assert v.state == UNKNOWN
    assert "Unlabelled rod" in v.message


# ── missing data, and partial setups ────────────────────────────────────────

def test_a_missing_spec_names_the_field_rather_than_guessing():
    bare = gear("line9", "Some braid", "line", kind="braid")
    v = tackle.rod_line_pe({"rod": POP_ROD, "line": bare})
    assert v.state == UNKNOWN
    assert "line PE" in v.message


def test_a_half_built_setup_produces_no_verdict_for_the_missing_part():
    """'You have not chosen a leader yet' is not a verdict about a leader.
    Reporting it as one fills a new setup with warnings before the person has
    finished building it."""
    verdicts = tackle.evaluate_setup({"rod": POP_ROD, "line": PE8}, ABD_AL_KURI)
    assert "leader_vs_main" not in states(verdicts)
    assert "rod_line_pe" in states(verdicts)


def test_the_whole_abd_al_kuri_setup_comes_back_clean():
    setup = {"rod": POP_ROD, "reel": STELLA, "line": PE8,
             "leader": LEADER, "lure": POPPER}
    verdicts = tackle.evaluate_setup(setup, ABD_AL_KURI)
    assert not any(v.is_problem for v in verdicts), \
        [v.message for v in verdicts if v.is_problem]
    assert len(verdicts) == 6          # five pair rules plus technique


# ── building setups from a locker ───────────────────────────────────────────

def test_setups_are_built_per_rod_not_as_a_cross_product():
    locker = [POP_ROD, JIG_ROD, STELLA, PE8, LEADER, POPPER]
    setups = tackle.build_setups(locker)
    assert len(setups) == 2            # one per rod, not 2x1x1x1x1 permutations
    assert {s["rod"]["id"] for s in setups} == {"rod1", "rod2"}


def test_a_setup_prefers_gear_that_shares_the_rods_technique():
    jig_lure = gear("lure5", "200 g jig", "lure", weight_g=200.0, kind="jig",
                    technique=["jigging"])
    locker = [POP_ROD, JIG_ROD, STELLA, PE8, LEADER, POPPER, jig_lure]
    setups = {s["rod"]["id"]: s for s in tackle.build_setups(locker)}
    assert setups["rod1"]["lure"]["id"] == "lure1"     # popper to the popping rod
    assert setups["rod2"]["lure"]["id"] == "lure5"     # jig to the jigging rod


def test_building_setups_from_an_empty_locker_is_empty_not_an_error():
    assert tackle.build_setups([]) == []


def test_retired_gear_never_enters_a_setup():
    retired = {**STELLA, "status": "retired"}
    setups = tackle.build_setups([POP_ROD, retired])
    assert "reel" not in setups[0]

# ── pairing by fit, which a green suite did not catch ───────────────────────
#
# THE BUG THESE EXIST FOR. build_setups filtered candidates on `technique` and
# then sorted by id. Lines and leaders carry no technique field — the registry
# gives them kind/pe/lb_test/metres — so the filter matched nothing, every role
# fell through to the id sort, and every rod got the SAME line and the SAME
# leader. Against a real locker that handed a PE6-10 popping rod a PE5 braid
# while the PE8 braid sat in the same locker, then reported the pairing it had
# invented as a problem with the person's tackle.
#
# The suite was green throughout. The one pairing test that existed asserted on
# LURES, which do carry technique, so it passed for the wrong reason and proved
# nothing about the three roles that were broken.
#
# WHY THE IDS BELOW LOOK BACKWARDS. `_tie_break` ends in `str(id)`, so a fixture
# whose correct answer also happens to sort first passes on the broken engine
# too. Written the obvious way, eight of these ten tests did exactly that. Every
# id here is therefore chosen so ALPHABETICAL ORDER IS THE WRONG ANSWER: the
# only way to pass is to have actually scored the fit.

# PE8 sorts last, PE2 first — the reverse of what a PE6-10 rod wants.
F_PE8 = gear("z-line-pe8", "PE8 braid", "line", kind="braid", pe=8.0,
             lb_test=100.0)
F_PE5 = gear("m-line-pe5", "PE5 braid", "line", kind="braid", pe=5.0,
             lb_test=65.0)
F_PE2 = gear("a-line-pe2", "PE2 braid", "line", kind="braid", pe=2.0,
             lb_test=30.0)
# The correct heavy leader sorts after the wrong light one.
F_LEADER_130 = gear("z-lead-130", "130 lb fluoro", "leader", kind="fluoro",
                    lb_test=130.0)
F_LEADER_40 = gear("a-lead-40", "40 lb fluoro", "leader", kind="fluoro",
                   lb_test=40.0)
# The reel that fits sorts after the one that does not.
F_BIG_REEL = gear("z-reel-18000", "Stella 18000HG", "reel", size="18000",
                  size_class="extra_heavy", drag_kg=25.0, pe_capacity=8.0,
                  technique=["popping", "jigging"])
F_SMALL_REEL = gear("a-reel-4000", "4000 spinning", "reel", size="4000",
                    size_class="light", drag_kg=8.0, pe_capacity=2.0,
                    technique=["popping", "jigging"])


def test_each_rod_gets_the_line_inside_its_own_pe_window():
    """The regression, stated as the thing a person would notice: a correct rig
    being called wrong."""
    locker = [POP_ROD, JIG_ROD, F_BIG_REEL, F_PE8, F_PE5, F_LEADER_130, POPPER]
    setups = {s["rod"]["id"]: s for s in tackle.build_setups(locker)}
    assert setups["rod1"]["line"]["id"] == "z-line-pe8"   # PE8 to the PE6-10 rod
    assert setups["rod2"]["line"]["id"] == "m-line-pe5"   # PE5 to the PE4-6 rod


def test_a_correctly_equipped_rod_reports_no_problems():
    """Pairing and judging together. Each half was right on its own; the bug
    lived in the seam, which is why no unit test saw it."""
    locker = [POP_ROD, JIG_ROD, F_BIG_REEL, F_PE8, F_PE5, F_LEADER_130, POPPER]
    setups = {s["rod"]["id"]: s for s in tackle.build_setups(locker)}
    problems = [v.message for v in tackle.evaluate_setup(setups["rod1"])
                if v.is_problem]
    assert problems == []


def test_the_leader_is_chosen_against_the_line_that_was_chosen():
    """Leader fit depends on the main line, so line must resolve first. With
    the order reversed this picks by id and the dependency is invisible."""
    locker = [JIG_ROD, F_PE5, F_PE8, F_LEADER_130, F_LEADER_40]
    setup = tackle.build_setups(locker)[0]
    assert setup["line"]["id"] == "m-line-pe5"            # matching PE4-6
    # 65 lb main: the 130 lb leader is 2.0x and the 40 lb is 0.6x. Only one of
    # them is above the main line at all.
    assert setup["leader"]["id"] == "z-lead-130"


def test_a_reel_is_chosen_for_the_line_class_the_rod_is_built_around():
    locker = [POP_ROD, F_BIG_REEL, F_SMALL_REEL, F_PE8]
    setup = tackle.build_setups(locker)[0]
    assert setup["reel"]["id"] == "z-reel-18000"          # PE8 capacity, not PE2


def test_nothing_suitable_still_gets_paired_and_still_gets_judged():
    """A picker that only ever chose a good fit would answer 'no problems' for
    a locker that cannot equip the rod at all. 'You own no line this rod can
    use' is the useful answer; silence is the dangerous one."""
    locker = [POP_ROD, F_SMALL_REEL, F_PE2, F_LEADER_40]
    setup = tackle.build_setups(locker)[0]
    assert setup["line"]["id"] == "a-line-pe2"            # paired despite the misfit
    problems = {v.rule_key for v in tackle.evaluate_setup(setup) if v.is_problem}
    assert "rod_line_pe" in problems


def test_a_line_with_no_pe_recorded_is_still_eligible():
    """Unknown is a state the rules report, not a reason to drop a candidate.
    Skipping it here would substitute a different line silently and answer a
    question about gear the person did not pair."""
    blank = gear("z-line-blank", "Unlabelled braid", "line", kind="braid")
    setup = tackle.build_setups([POP_ROD, blank])[0]
    assert setup["line"]["id"] == "z-line-blank"
    assert states(tackle.evaluate_setup(setup))["rod_line_pe"] == UNKNOWN


def test_a_recorded_fit_beats_a_blank_one():
    """The blank sorts FIRST here, so id order argues for it and fit argues
    against — which is the only arrangement that tests anything."""
    blank = gear("a-line-blank", "Unlabelled braid", "line", kind="braid")
    setup = tackle.build_setups([POP_ROD, blank, F_PE8])[0]
    assert setup["line"]["id"] == "z-line-pe8"


def test_a_near_miss_is_preferred_to_a_wild_one():
    """When nothing fits, the verdict should name the closest thing the locker
    actually holds. PE5 is one step under a PE6-10 rod; PE2 is four."""
    setup = tackle.build_setups([POP_ROD, F_PE2, F_PE5])[0]
    assert setup["line"]["id"] == "m-line-pe5"


def test_pairing_is_stable_across_two_identical_calls():
    """A setup that changed between two screens with nothing having changed is
    worse than one that is merely arbitrary."""
    locker = [POP_ROD, JIG_ROD, F_BIG_REEL, F_SMALL_REEL, F_PE8, F_PE5, F_PE2,
              F_LEADER_130, F_LEADER_40, POPPER]
    first = tackle.build_setups(locker)
    second = tackle.build_setups(list(reversed(locker)))
    assert [{r: s[r]["id"] for r in s} for s in first] \
        == [{r: s[r]["id"] for r in s} for s in second]


def test_technique_still_wins_where_it_is_recorded():
    """The fix must not trade one bug for another: a jigging rod should not be
    handed the popping reel because its PE capacity scored a hair better. The
    popping reel sorts first AND has the better raw fit, so technique is the
    only thing that can produce the right answer."""
    jig_reel = gear("z-reel-jig", "Jigging reel 8000", "reel", size="8000",
                    size_class="medium", drag_kg=10.0, pe_capacity=6.0,
                    technique=["jigging"])
    pop_only = gear("a-reel-pop", "Popping reel 14000", "reel", size="14000",
                    size_class="heavy", drag_kg=20.0, pe_capacity=5.0,
                    technique=["popping"])
    setup = tackle.build_setups([JIG_ROD, jig_reel, pop_only, F_PE5])[0]
    assert setup["reel"]["id"] == "z-reel-jig"


# ── a pair that is backwards while every field in it is legal ───────────────
#
# Found by throwing malformed bodies at the live endpoint, not by the suite.
# pe_min 10 with pe_max 2 passed every check the validator had — both numbers
# sit inside the registry's 0.4-20 — and then made this rule answer, for ANY
# line, "heavier than this rod is rated for (to PE2)". One transposed pair of
# digits turned into confident advice.

def test_a_backwards_pe_rating_is_reported_as_a_typo_not_a_mismatch():
    broken = gear("rodx", "Rod with a transposed rating", "rod",
                  technique=["popping"], pe_min=10.0, pe_max=2.0)
    v = tackle.rod_line_pe({"rod": broken, "line": PE8})
    assert v.state == UNKNOWN
    assert "backwards" in v.message
    assert v.detail["inverted"] is True


def test_a_backwards_casting_range_is_reported_the_same_way():
    broken = gear("rody", "Rod with a transposed window", "rod",
                  technique=["popping"], cast_weight_min_g=150.0,
                  cast_weight_max_g=60.0)
    v = tackle.lure_vs_rod({"rod": broken, "lure": POPPER})
    assert v.state == UNKNOWN
    assert "backwards" in v.message


def test_a_backwards_window_is_never_reported_as_a_problem():
    """UNKNOWN, not NOT_RECOMMENDED. 'Your line is wrong' and 'your rod's
    rating is typed wrong' send a person to two different places, and only one
    of them is the truth."""
    broken = gear("rodz", "Rod with a transposed rating", "rod",
                  technique=["popping"], pe_min=10.0, pe_max=2.0,
                  cast_weight_min_g=150.0, cast_weight_max_g=60.0)
    verdicts = tackle.evaluate_setup(
        {"rod": broken, "line": PE8, "lure": POPPER})
    assert not any(v.is_problem for v in verdicts), \
        [v.message for v in verdicts if v.is_problem]
