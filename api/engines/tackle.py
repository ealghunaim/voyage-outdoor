"""Tackle compatibility — the rules that hold between two pieces of gear (§11).

WHY THIS IS A SEPARATE ENGINE, AND THE FINDING OF PHASE 7
---------------------------------------------------------
engines/compatibility.py answers "does this item suit this trip". Every rule in
it has the shape `(gear, adventure) -> Verdict`, and RULES is keyed by the
item's own category. That was enough for trail running, where every question is
about one object and the day: shoe versus terrain, headlamp versus darkness,
vest versus duration, jacket versus the race's rules.

Fishing's questions are not that shape. §11 names them: ROD↔REEL, REEL↔LINE,
LINE↔LEADER, LURE↔HOOK, HOOK↔SPLIT RING. "This reel is too small for this rod"
cannot be expressed by a function that only ever sees one item, however many
rules you add. The claim in §0.4 was that adding an activity would not require
rework — the ATTRIBUTE MODEL held that promise without a change, and the ENGINE
INTERFACE did not. That is the honest result of the experiment, and this file is
the new surface it needed rather than a rewrite of the old one.

A SETUP IS COMPUTED, NEVER STORED. Rod, reel, line, leader and lure are combined
on demand and the verdicts thrown away. There is no `setups` table and no named
"my GT popping setup", because nothing yet needs one and an entity is far harder
to remove than to add — the same discipline the offline queue and the gear-health
accumulator were held to.

THE NUMBERS BELOW ARE ASSUMED DEFAULTS, NOT MEASURED FACTS (§0.5)
-----------------------------------------------------------------
They are standard tackle practice — the drag fraction, the leader ratio, the PE
window — written down so they can be argued with, which is the whole reason
these are constants and not literals buried in branches. Nobody with the gear in
their hands has confirmed them yet. Where a rule would have to invent a
threshold it has none, it returns UNKNOWN and names the field instead, exactly
as the trail-running rules do.

PE IS A DIAMETER STANDARD, NOT A STRENGTH ONE. PE8 is roughly 80-100 lb
depending on the maker. So the rules reason in PE where the tackle is labelled
in PE, and in pounds where it is labelled in pounds, and never convert between
them — a converted number looks exact and is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from api.engines.compatibility import (
    COMPATIBLE, NOT_RECOMMENDED, POSSIBLY, UNKNOWN, _num,
)

TACKLE_RULESET = "tackle-v1"

#: The roles a setup can fill. A setup is a dict of these to gear items; any of
#: them may be absent, and a rule whose parts are missing simply does not run.
ROLES = ("rod", "reel", "line", "leader", "lure")

# ── assumed thresholds (§0.5) ───────────────────────────────────────────────

#: Fraction of a line's breaking strain that gets fished as drag. Standard
#: practice is a quarter to a third; a third is the working figure for heavy
#: popping, where the fish has to be turned before it reaches structure.
DRAG_FRACTION = 1 / 3
LB_TO_KG = 0.45359237

#: A leader below the main line's strength is the weak point at the fish end,
#: which is the one place you cannot afford one. GT practice runs the leader
#: heavier than the braid, partly for strength and partly for abrasion over
#: coral.
#:
#: 1.25, NOT 1.5, AND THE TEST IS WHY. The first draft used 1.5 and then called
#: 130 lb fluoro on PE8 braid "marginal" — which is the single most ordinary
#: rig in this discipline. A threshold that flags standard practice as a problem
#: does not make anyone safer; it teaches them to ignore the warnings. Still an
#: assumed default (§0.5) and still correctable, but calibrated against a real
#: rig rather than against a round number.
LEADER_MIN_RATIO = 1.0
LEADER_COMFORTABLE_RATIO = 1.25

#: How far outside a rod's rated PE window counts as marginal rather than wrong.
#: Rod ratings are conservative and a half-step over is common practice.
PE_MARGIN = 0.5


@dataclass(frozen=True)
class TackleVerdict:
    rule_key: str
    state: str
    message: str
    #: Which roles the rule looked at. Carried so a screen can highlight the two
    #: items a verdict is ABOUT — the thing a one-item verdict never had to say.
    roles: tuple[str, ...] = ()
    ruleset: str = TACKLE_RULESET
    detail: dict = field(default_factory=dict)

    @property
    def is_problem(self) -> bool:
        return self.state == NOT_RECOMMENDED


def _attr(item: dict | None, name: str):
    if not item:
        return None
    return (item.get("attributes") or {}).get(name)


def _unknown(key: str, roles: tuple[str, ...], missing: list[str],
             what: str) -> TackleVerdict:
    return TackleVerdict(
        key, UNKNOWN,
        f"Not enough recorded to judge {what}. Missing: {', '.join(missing)}.",
        roles=roles, detail={"missing": missing})


def _name(item: dict | None) -> str:
    return (item or {}).get("name") or "that item"


# ── rod ↔ line: the PE window ───────────────────────────────────────────────

def rod_line_pe(setup: dict) -> TackleVerdict | None:
    rod, line = setup.get("rod"), setup.get("line")
    if not rod or not line:
        return None
    key = "rod_line_pe"
    roles = ("rod", "line")

    pe = _num(_attr(line, "pe"))
    lo = _num(_attr(rod, "pe_min"))
    hi = _num(_attr(rod, "pe_max"))
    missing = ([] if pe is not None else ["line PE"]) \
        + ([] if lo is not None or hi is not None else ["the rod's PE rating"])
    if missing:
        return _unknown(key, roles, missing, "line against the rod's rating")

    lo = lo if lo is not None else 0.0
    hi = hi if hi is not None else 99.0
    detail = {"line_pe": pe, "rod_pe_min": lo, "rod_pe_max": hi}

    if lo <= pe <= hi:
        return TackleVerdict(key, COMPATIBLE,
                             f"PE{pe:g} is inside {_name(rod)}'s PE{lo:g}-{hi:g} rating.",
                             roles=roles, detail=detail)
    if lo - PE_MARGIN <= pe <= hi + PE_MARGIN:
        return TackleVerdict(
            key, POSSIBLY,
            f"PE{pe:g} is just outside {_name(rod)}'s PE{lo:g}-{hi:g} rating. "
            f"Half a step over is common; it is still the blank taking the load.",
            roles=roles, detail=detail)
    # OVER AND UNDER ARE DIFFERENT FAILURES and the sentence says which. Too
    # heavy risks the blank; too light means the rod cannot load and the line
    # breaks before the rod bends.
    if pe > hi:
        return TackleVerdict(
            key, NOT_RECOMMENDED,
            f"PE{pe:g} is heavier than {_name(rod)} is rated for (to PE{hi:g}). "
            f"The blank is the part that gives way.",
            roles=roles, detail=detail)
    return TackleVerdict(
        key, NOT_RECOMMENDED,
        f"PE{pe:g} is lighter than {_name(rod)} is rated for (from PE{lo:g}). "
        f"The rod will not load and the line goes first.",
        roles=roles, detail=detail)


# ── reel ↔ line: can the spool carry it ─────────────────────────────────────

def reel_line_pe(setup: dict) -> TackleVerdict | None:
    reel, line = setup.get("reel"), setup.get("line")
    if not reel or not line:
        return None
    key = "reel_line_pe"
    roles = ("reel", "line")

    pe = _num(_attr(line, "pe"))
    cap = _num(_attr(reel, "pe_capacity"))
    missing = ([] if pe is not None else ["line PE"]) \
        + ([] if cap is not None else ["the reel's rated PE"])
    if missing:
        return _unknown(key, roles, missing, "line against the reel")

    detail = {"line_pe": pe, "reel_pe": cap}
    if pe <= cap:
        return TackleVerdict(key, COMPATIBLE,
                             f"{_name(reel)} is rated to PE{cap:g}; this is PE{pe:g}.",
                             roles=roles, detail=detail)
    return TackleVerdict(
        key, NOT_RECOMMENDED,
        f"PE{pe:g} on a reel rated to PE{cap:g} — the spool will not hold enough "
        f"of it, and capacity is what a long first run spends.",
        roles=roles, detail=detail)


# ── reel ↔ line: drag against breaking strain ───────────────────────────────

def drag_vs_line(setup: dict) -> TackleVerdict | None:
    reel, line = setup.get("reel"), setup.get("line")
    if not reel or not line:
        return None
    key = "drag_vs_line"
    roles = ("reel", "line")

    drag = _num(_attr(reel, "drag_kg"))
    lb = _num(_attr(line, "lb_test"))
    missing = ([] if drag is not None else ["the reel's max drag"]) \
        + ([] if lb is not None else ["the line's breaking strain"])
    if missing:
        return _unknown(key, roles, missing, "drag against the line")

    fishable = lb * LB_TO_KG * DRAG_FRACTION
    detail = {"drag_kg": drag, "line_lb": lb,
              "fishable_drag_kg": round(fishable, 1),
              "fraction": round(DRAG_FRACTION, 3)}

    if drag >= fishable:
        return TackleVerdict(
            key, COMPATIBLE,
            f"{_name(reel)} delivers {drag:g} kg; {lb:g} lb line fishes at "
            f"about {fishable:.0f} kg at a third of breaking strain.",
            roles=roles, detail=detail)
    # UNDER-GUNNED, and that is the direction that matters. A reel whose maximum
    # exceeds the line is merely something you do not wind all the way up; a
    # reel that cannot reach fishable drag means the line's strength is
    # unreachable and the fish decides where it goes.
    return TackleVerdict(
        key, NOT_RECOMMENDED,
        f"{_name(reel)} tops out at {drag:g} kg, under the {fishable:.0f} kg "
        f"that {lb:g} lb line would fish. The line is stronger than the reel "
        f"can use.",
        roles=roles, detail=detail)


# ── line ↔ leader ───────────────────────────────────────────────────────────

def leader_vs_main(setup: dict) -> TackleVerdict | None:
    line, leader = setup.get("line"), setup.get("leader")
    if not line or not leader:
        return None
    key = "leader_vs_main"
    roles = ("line", "leader")

    main = _num(_attr(line, "lb_test"))
    lead = _num(_attr(leader, "lb_test"))
    missing = ([] if main is not None else ["the main line's breaking strain"]) \
        + ([] if lead is not None else ["the leader's breaking strain"])
    if missing:
        return _unknown(key, roles, missing, "leader against main line")

    ratio = lead / main if main else 0.0
    detail = {"main_lb": main, "leader_lb": lead, "ratio": round(ratio, 2)}

    if ratio >= LEADER_COMFORTABLE_RATIO:
        return TackleVerdict(
            key, COMPATIBLE,
            f"{lead:g} lb leader on {main:g} lb braid — heavier than the main "
            f"line, which is where you want the margin.",
            roles=roles, detail=detail)
    if ratio >= LEADER_MIN_RATIO:
        return TackleVerdict(
            key, POSSIBLY,
            f"{lead:g} lb leader on {main:g} lb braid. It holds, but there is "
            f"no margin for abrasion, and coral is what leaders lose to.",
            roles=roles, detail=detail)
    return TackleVerdict(
        key, NOT_RECOMMENDED,
        f"{lead:g} lb leader is lighter than {main:g} lb main line. The weak "
        f"point is at the fish end, which is the one place it must not be.",
        roles=roles, detail=detail)


# ── rod ↔ lure ──────────────────────────────────────────────────────────────

def lure_vs_rod(setup: dict) -> TackleVerdict | None:
    rod, lure = setup.get("rod"), setup.get("lure")
    if not rod or not lure:
        return None
    key = "lure_vs_rod"
    roles = ("rod", "lure")

    weight = _num(_attr(lure, "weight_g"))
    if weight is None:
        return _unknown(key, roles, ["the lure's weight"], "lure against the rod")

    kind = _attr(lure, "kind")
    # A JIG IS NOT CAST, so it is judged against a different number. Weighing a
    # 250 g jig against a casting window is the category error this rule exists
    # to avoid — the rod never throws it, it just holds it.
    if kind == "jig":
        cap = _num(_attr(rod, "jig_weight_max_g"))
        if cap is None:
            return _unknown(key, roles, ["the rod's maximum jig weight"],
                            "jig against the rod")
        detail = {"lure_g": weight, "jig_max_g": cap}
        if weight <= cap:
            return TackleVerdict(key, COMPATIBLE,
                                 f"{weight:g} g jig, within {_name(rod)}'s {cap:g} g.",
                                 roles=roles, detail=detail)
        return TackleVerdict(
            key, NOT_RECOMMENDED,
            f"{weight:g} g is over {_name(rod)}'s {cap:g} g jig rating.",
            roles=roles, detail=detail)

    lo = _num(_attr(rod, "cast_weight_min_g"))
    hi = _num(_attr(rod, "cast_weight_max_g"))
    if lo is None and hi is None:
        return _unknown(key, roles, ["the rod's cast weight range"],
                        "lure against the rod")
    lo = lo if lo is not None else 0.0
    hi = hi if hi is not None else 10_000.0
    detail = {"lure_g": weight, "cast_min_g": lo, "cast_max_g": hi}

    if lo <= weight <= hi:
        return TackleVerdict(
            key, COMPATIBLE,
            f"{weight:g} g sits in {_name(rod)}'s {lo:g}-{hi:g} g window.",
            roles=roles, detail=detail)
    if weight > hi:
        return TackleVerdict(
            key, NOT_RECOMMENDED,
            f"{weight:g} g is over {_name(rod)}'s {hi:g} g casting limit.",
            roles=roles, detail=detail)
    return TackleVerdict(
        key, POSSIBLY,
        f"{weight:g} g is under {_name(rod)}'s {lo:g} g. It will cast short "
        f"rather than break anything.",
        roles=roles, detail=detail)


# ── the whole setup ↔ the technique being fished ────────────────────────────

def technique_match(setup: dict, adventure: dict) -> TackleVerdict | None:
    """Is this setup the right tool for what the trip is doing?

    The one rule here that reaches the adventure as well as the gear, because
    "a jigging rod on a popping trip" is a question about both.
    """
    wanted = {t for t in (adventure.get("attributes") or {}).get("technique") or []}
    if not wanted:
        return None
    key = "technique_match"

    present = {role: setup[role] for role in ("rod", "reel", "lure") if setup.get(role)}
    if not present:
        return None

    mismatched: list[str] = []
    unstated: list[str] = []
    for role, item in present.items():
        declared = _attr(item, "technique")
        if not declared:
            unstated.append(f"{_name(item)} ({role})")
            continue
        if not (set(declared) & wanted):
            mismatched.append(f"{_name(item)} is for {'/'.join(sorted(declared))}")

    roles = tuple(present)
    detail = {"trip": sorted(wanted), "mismatched": mismatched}
    if mismatched:
        return TackleVerdict(
            key, NOT_RECOMMENDED,
            f"This trip is {'/'.join(sorted(wanted))}, but "
            + "; ".join(mismatched) + ".",
            roles=roles, detail=detail)
    if unstated:
        return _unknown(key, roles, unstated, "the setup against the technique")
    return TackleVerdict(
        key, COMPATIBLE,
        f"Every part of this setup is rated for {'/'.join(sorted(wanted))}.",
        roles=roles, detail=detail)


#: Order matters only for reading — the strongest structural rules first, so a
#: screen that truncates shows the ones that break tackle rather than the ones
#: that cost casting distance.
PAIR_RULES = (rod_line_pe, reel_line_pe, drag_vs_line, leader_vs_main, lure_vs_rod)


def evaluate_setup(setup: dict, adventure: dict | None = None) -> list[TackleVerdict]:
    """Every rule that has both its parts, for one combination of gear.

    `setup` maps ROLES to gear items; anything absent simply means the rules
    that need it do not run. That is the whole reason rules return None rather
    than UNKNOWN for a missing ROLE — "you have not chosen a leader yet" is not
    a verdict about a leader, and reporting it as one would fill a new setup
    with warnings before the person had finished building it.
    """
    out = [verdict for rule in PAIR_RULES
           if (verdict := rule(setup)) is not None]
    if adventure is not None:
        tech = technique_match(setup, adventure)
        if tech is not None:
            out.append(tech)
    return out


def build_setups(locker: list[dict]) -> list[dict]:
    """Every rod in the locker, paired with the obvious rest of the kit.

    NOT A CROSS PRODUCT. Four rods, three reels, three lines and five lures is
    180 combinations, of which the person owns one opinion. So this pairs each
    rod with the gear that shares its technique and stops — enough to say "this
    rod, so this reel and this line", which is the question actually being
    asked, and cheap enough to recompute on every screen.
    """
    active = [g for g in locker if g.get("status") == "active"]
    by_category: dict[str, list[dict]] = {}
    for gear in active:
        by_category.setdefault(gear.get("category_key") or "", []).append(gear)

    def pick(category: str, technique: set[str]) -> dict | None:
        candidates = by_category.get(category) or []
        if technique:
            matching = [c for c in candidates
                        if set(_attr(c, "technique") or []) & technique]
            if matching:
                candidates = matching
        # Same deterministic ordering as the pack engine: favourite, then
        # lightest, then id. A setup that changed between two screens with
        # nothing having changed is worse than one that is merely arbitrary.
        return sorted(candidates, key=lambda g: (
            0 if g.get("favorite") else 1,
            g.get("weight_g") if g.get("weight_g") is not None else 10 ** 9,
            str(g.get("id") or ""),
        ))[0] if candidates else None

    setups = []
    for rod in sorted(by_category.get("rod") or [],
                      key=lambda g: str(g.get("id") or "")):
        technique = set(_attr(rod, "technique") or [])
        setup = {"rod": rod}
        for role in ("reel", "line", "leader", "lure"):
            chosen = pick(role, technique)
            if chosen:
                setup[role] = chosen
        setups.append(setup)
    return setups
