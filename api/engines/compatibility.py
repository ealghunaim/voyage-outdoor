"""Equipment compatibility — versioned rules, not model calls (§11, §0.5).

Pure functions. A rule takes one gear item and one adventure and returns a
Verdict: a state, the facts it compared, and — when it cannot decide — the
names of the fields it needed and did not have.

FOUR STATES, AND WHY THE FOURTH IS THE IMPORTANT ONE
----------------------------------------------------
    compatible           the rule checked and is satisfied
    possibly_compatible  it is marginal; the numbers are close enough that
                         conditions decide it
    not_recommended      the rule checked and is not satisfied
    unknown              THE RULE COULD NOT CHECK

`unknown` is not a soft `compatible`. A headlamp with no burn time recorded is
not "probably fine for eleven hours of darkness" — it is a headlamp nobody has
measured, and saying so tells the owner exactly what to go and find out. Any
rule that would have to guess returns unknown and names what is missing.

EVERY VERDICT EXPLAINS ITSELF IN STRUCTURED FORM. `detail` holds the numbers
that were compared, so the answer can be re-derived by hand and so the Phase 4
AI layer has something to narrate. The engine writes a plain sentence too; the
model may rewrite that sentence and may never change the state.
"""
from __future__ import annotations

from dataclasses import dataclass, field

COMPAT_RULESET = "compat-v1"

COMPATIBLE = "compatible"
POSSIBLY = "possibly_compatible"
NOT_RECOMMENDED = "not_recommended"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Verdict:
    rule_key: str
    state: str
    message: str
    ruleset: str = COMPAT_RULESET
    detail: dict = field(default_factory=dict)

    @property
    def is_problem(self) -> bool:
        return self.state == NOT_RECOMMENDED


def _num(value) -> float | None:
    """A number, or None. Booleans are NOT numbers here: True would otherwise
    sail through as 1.0 and be compared against a lug depth."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _unknown(rule_key: str, missing: list[str], what: str) -> Verdict:
    names = ", ".join(missing)
    return Verdict(rule_key, UNKNOWN,
                   f"Not enough recorded to judge {what}. Missing: {names}.",
                   detail={"missing": missing})


# ── shoe ↔ terrain ──────────────────────────────────────────────────────────

#: Lug depth in mm below which a shoe is not a technical-terrain shoe. 3.5 is
#: where manufacturers' own "trail" and "door-to-trail" lines part company:
#: below it the outsole is a road pattern with a trail badge.
TECHNICAL_LUG_MM = 3.5
#: Marginal band. Between these the shoe will work for someone confident on
#: rock and will not for someone who is not, which is exactly what
#: `possibly_compatible` is for.
MARGINAL_LUG_MM = 2.5

TECHNICAL_TERRAIN = {"technical", "mountain", "snow"}


def shoe_terrain(gear: dict, adventure: dict) -> Verdict:
    key = "shoe_terrain"
    terrain = set((adventure.get("attributes") or {}).get("terrain") or [])
    if not terrain:
        return _unknown(key, ["adventure.terrain"], "grip against terrain")
    if not (terrain & TECHNICAL_TERRAIN):
        return Verdict(key, COMPATIBLE,
                       "No technical terrain recorded, so tread depth is not "
                       "the deciding factor.",
                       detail={"terrain": sorted(terrain)})

    lug = _num((gear.get("attributes") or {}).get("lug_depth_mm"))
    if lug is None:
        return _unknown(key, ["gear.lug_depth_mm"], "grip against terrain")

    facts = {"lug_depth_mm": lug, "terrain": sorted(terrain),
             "technical_threshold_mm": TECHNICAL_LUG_MM}
    hard = sorted(terrain & TECHNICAL_TERRAIN)

    if lug >= TECHNICAL_LUG_MM:
        return Verdict(key, COMPATIBLE,
                       f"{lug:g} mm lugs for {', '.join(hard)} terrain.",
                       detail=facts)
    if lug >= MARGINAL_LUG_MM:
        return Verdict(key, POSSIBLY,
                       f"{lug:g} mm lugs is shallow for {', '.join(hard)} "
                       f"terrain — workable if it stays dry.",
                       detail=facts)
    return Verdict(key, NOT_RECOMMENDED,
                   f"{lug:g} mm lugs on {', '.join(hard)} terrain. "
                   f"Below about {TECHNICAL_LUG_MM:g} mm there is little to "
                   f"bite with.",
                   detail=facts)


# ── headlamp ↔ darkness ─────────────────────────────────────────────────────

#: Burn time must exceed expected darkness by this much. Batteries fade in the
#: cold, "burn time" is quoted at a brightness nobody actually runs at, and
#: running out of light on technical ground at 3am is the failure this whole
#: rule exists to prevent. 1.25 is not padding; it is the honest discount on a
#: manufacturer's figure.
BURN_MARGIN = 1.25


def headlamp_night(gear: dict, adventure: dict) -> Verdict:
    key = "headlamp_night"
    night = _num((adventure.get("attributes") or {}).get("night_hours"))
    if night is None:
        return _unknown(key, ["adventure.night_hours"], "light against darkness")
    if night <= 0:
        return Verdict(key, COMPATIBLE, "No darkness expected.",
                       detail={"night_hours": night})

    burn = _num((gear.get("attributes") or {}).get("burn_time_h"))
    if burn is None:
        return _unknown(key, ["gear.burn_time_h"], "light against darkness")

    needed = round(night * BURN_MARGIN, 1)
    facts = {"burn_time_h": burn, "night_hours": night,
             "needed_h": needed, "margin": BURN_MARGIN}

    if burn >= needed:
        return Verdict(key, COMPATIBLE,
                       f"{burn:g} h of burn time for {night:g} h of darkness.",
                       detail=facts)
    if burn >= night:
        return Verdict(key, POSSIBLY,
                       f"{burn:g} h of burn time against {night:g} h of "
                       f"darkness. It covers the hours on paper with nothing "
                       f"spare — carry a second light or spare cells.",
                       detail=facts)
    return Verdict(key, NOT_RECOMMENDED,
                   f"{burn:g} h of burn time will not cover {night:g} h of "
                   f"darkness. Take a spare light or spare batteries.",
                   detail=facts)


# ── vest ↔ what has to go in it ─────────────────────────────────────────────

#: Litres a mandatory-kit list needs, roughly, per item. Race kit is compact —
#: a folded shell, a blanket, a phone — so this is deliberately small; it is a
#: floor for "does the vest have room at all", not a packing simulation.
LITRES_PER_MANDATORY_ITEM = 0.6
#: A self-supported day adds food and water volume on top.
SELF_SUPPORTED_LITRES = 3.0


def vest_capacity(gear: dict, adventure: dict) -> Verdict:
    key = "vest_capacity"
    attrs = adventure.get("attributes") or {}
    kit = attrs.get("mandatory_kit") or []
    self_supported = attrs.get("self_supported") is True

    if not kit and not self_supported:
        return Verdict(key, UNKNOWN,
                       "No mandatory kit or self-support recorded, so there is "
                       "no required volume to check against.",
                       detail={"missing": ["adventure.mandatory_kit"]})

    capacity = _num((gear.get("attributes") or {}).get("capacity_l"))
    if capacity is None:
        return _unknown(key, ["gear.capacity_l"], "capacity against required kit")

    needed = round(len(kit) * LITRES_PER_MANDATORY_ITEM
                   + (SELF_SUPPORTED_LITRES if self_supported else 0), 1)
    facts = {"capacity_l": capacity, "needed_l": needed,
             "mandatory_items": len(kit), "self_supported": self_supported}

    if capacity >= needed:
        return Verdict(key, COMPATIBLE,
                       f"{capacity:g} L for roughly {needed:g} L of required "
                       f"kit.", detail=facts)
    if capacity >= needed * 0.8:
        return Verdict(key, POSSIBLY,
                       f"{capacity:g} L against roughly {needed:g} L of "
                       f"required kit — it will go in, tightly.",
                       detail=facts)
    return Verdict(key, NOT_RECOMMENDED,
                   f"{capacity:g} L is short of the roughly {needed:g} L this "
                   f"kit list needs.", detail=facts)


# ── waterproof ↔ race rules ─────────────────────────────────────────────────

#: The figure race manuals converge on for a mandatory waterproof. Below it a
#: shell is windproof and showerproof, which is a different garment.
RACE_HYDROSTATIC_MM = 10000

WATERPROOF_WORDS = ("waterproof", "rain jacket", "hardshell", "hard shell", "shell")


def jacket_race_legal(gear: dict, adventure: dict) -> Verdict:
    key = "jacket_race_legal"
    kit = (adventure.get("attributes") or {}).get("mandatory_kit") or []
    demanded = [line for line in kit
                if any(word in line.lower() for word in WATERPROOF_WORDS)]
    if not demanded:
        return Verdict(key, COMPATIBLE,
                       "No waterproof is mandated for this adventure.",
                       detail={"mandatory_kit_matches": []})

    attrs = gear.get("attributes") or {}
    facts: dict = {"mandatory_kit_matches": demanded,
                   "threshold_mm": RACE_HYDROSTATIC_MM}

    # An explicit race_legal flag is the owner reading their own race manual,
    # which beats any inference this rule could make from a spec sheet.
    if attrs.get("race_legal") is True:
        return Verdict(key, COMPATIBLE,
                       "Marked as meeting the race waterproof specification.",
                       detail={**facts, "race_legal": True})
    if attrs.get("race_legal") is False:
        return Verdict(key, NOT_RECOMMENDED,
                       "Marked as NOT meeting the race waterproof "
                       "specification, and the kit list mandates one.",
                       detail={**facts, "race_legal": False})

    head = _num(attrs.get("hydrostatic_head_mm"))
    if head is None:
        if attrs.get("waterproof") is False:
            return Verdict(key, NOT_RECOMMENDED,
                           "Not a waterproof, and the kit list mandates one.",
                           detail={**facts, "waterproof": False})
        return _unknown(key, ["gear.hydrostatic_head_mm", "gear.race_legal"],
                        "this shell against the race's waterproof rule")

    facts["hydrostatic_head_mm"] = head
    if head >= RACE_HYDROSTATIC_MM:
        return Verdict(key, COMPATIBLE,
                       f"{head:g} mm hydrostatic head meets the usual "
                       f"{RACE_HYDROSTATIC_MM} mm race minimum.", detail=facts)
    return Verdict(key, NOT_RECOMMENDED,
                   f"{head:g} mm hydrostatic head is below the usual "
                   f"{RACE_HYDROSTATIC_MM} mm race minimum. Check the race "
                   f"manual — kit checks turn people away for this.",
                   detail=facts)


#: category_key -> the rules that apply to it. A category with no rules simply
#: produces no verdicts, which is correct: silence is not a pass, and nothing
#: downstream reads an absent verdict as approval.
RULES = {
    "shoes": (shoe_terrain,),
    "headlamp": (headlamp_night,),
    "vest": (vest_capacity,),
    "jacket": (jacket_race_legal,),
}


def evaluate(gear: dict, adventure: dict) -> list[Verdict]:
    """Every rule that applies to this item, in declaration order."""
    return [rule(gear, adventure)
            for rule in RULES.get(gear.get("category_key") or "", ())]


def evaluate_all(locker: list[dict], adventure: dict) -> dict[str, list[Verdict]]:
    """gear_item_id -> verdicts, for every item with a rule."""
    out: dict[str, list[Verdict]] = {}
    for gear in locker:
        verdicts = evaluate(gear, adventure)
        if verdicts:
            out[gear["id"]] = verdicts
    return out
