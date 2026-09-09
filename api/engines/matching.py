"""Mandatory-kit lines -> gear categories, deterministically (§0.5, §24).

A race manual says "Survival blanket 1.4 x 2 m" and the locker holds a category
called `safety`. Something has to connect them, and that something is NOT a
model: mandatory kit is authoritative external data, and a model that quietly
mapped a line to the wrong category would drop a required item off a pack list
without anything looking wrong.

So it is a keyword table. It is dumb, it is inspectable, its failures are
visible, and — the part that matters — when it cannot match a line it says so
and the line stays REQUIRED as an unmatched entry rather than disappearing.

ORDER IS SIGNIFICANT. The first pattern that matches wins, so specific phrases
precede general words: "spare batteries" must reach `electronics` before the
word "spare" reaches anything, and "waterproof jacket" must reach `jacket`
before "waterproof" is considered at all.
"""
from __future__ import annotations

import re
import unicodedata

MATCH_RULESET = "match-v1"

#: (category_key, patterns). Ordered — first hit wins.
#:
#: Patterns are matched against a normalised line: lowercased, accents
#: stripped, punctuation collapsed to single spaces. That is what makes
#: "Headlamp + spare batteries", "headlamp/spare batteries" and "Head lamp -
#: spare batteries" all reach the same place.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("headlamp", ("headlamp", "head lamp", "headtorch", "head torch",
                  "front lamp", "torch")),
    ("jacket", ("waterproof jacket", "waterproof top", "rain jacket",
                "hardshell", "hard shell", "windproof", "wind jacket",
                "waterproof")),
    ("hydration", ("water capacity", "water carrying", "flask", "soft flask",
                   "bladder", "hydration", "water bottle", "litre of water",
                   "liter of water", "litres of water")),
    ("nutrition", ("food reserve", "emergency food", "energy bar", "gel",
                   "nutrition", "calories", "food")),
    ("first_aid", ("first aid", "first-aid", "bandage", "dressing",
                   "blister", "plaster", "antiseptic", "tourniquet")),
    ("safety", ("survival blanket", "space blanket", "emergency blanket",
                "bivvy", "bivy", "whistle", "survival bag", "id card",
                "emergency contact")),
    ("electronics", ("mobile phone", "phone", "spare batteries",
                     "spare battery", "battery", "power bank", "charger",
                     "gps tracker", "tracker")),
    ("navigation", ("gps", "map", "compass", "roadbook", "road book",
                    "watch", "navigation")),
    ("eyewear", ("sunglasses", "glasses", "goggles", "eye protection")),
    ("headwear", ("cap", "hat", "buff", "beanie", "headband", "sun hat")),
    ("gloves", ("gloves", "mitts", "mittens")),
    ("apparel_top", ("long sleeve", "long-sleeve", "base layer", "thermal top",
                     "warm layer", "midlayer", "mid layer", "t-shirt")),
    ("apparel_bottom", ("tights", "long tights", "leggings", "trousers",
                        "shorts")),
    ("poles", ("poles", "trekking poles", "running poles")),
    ("shoes", ("shoes", "trail shoes", "footwear")),
    ("gaiters", ("gaiters", "gaiter")),
    ("vest", ("vest", "pack", "backpack", "rucksack")),
)


def normalise(text: str) -> str:
    """Lowercase, strip accents, collapse punctuation and whitespace.

    The same normaliser is used on kit lines and on gear names, so the two are
    compared on equal terms. Accents are stripped because a French race manual
    writes "réserve alimentaire" and the table is in English — this does not
    translate, but it stops an accent alone from breaking a match that would
    otherwise work.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    collapsed = re.sub(r"[^a-z0-9]+", " ", ascii_only.lower())
    return collapsed.strip()


def category_for(line: str) -> str | None:
    """The category a kit line belongs to, or None when nothing matches.

    None is a real answer and the caller must handle it: the line stays on the
    pack list as REQUIRED and unmatched, because a race mandating something
    this table has never heard of is a gap in the table, not permission to drop
    the requirement.
    """
    text = normalise(line)
    if not text:
        return None
    for category, patterns in KEYWORDS:
        for pattern in patterns:
            if normalise(pattern) in text:
                return category
    return None


def gear_matches_line(gear: dict, line: str) -> bool:
    """Does this specific item satisfy this kit line by NAME?

    A weaker signal than category and used only to break ties — "Petzl Swift
    RL" does not contain the word headlamp, so name matching alone would miss
    almost everything. Category is the primary route; this catches the case
    where a locker holds two items in one category and one of them is literally
    named after the requirement.
    """
    name = normalise(f"{gear.get('brand') or ''} {gear.get('name') or ''}")
    text = normalise(line)
    if not name or not text:
        return False
    words = [w for w in text.split() if len(w) > 3]
    return any(w in name for w in words)


def best_gear_for(line: str, locker: list[dict],
                  exclude: set[str] | None = None) -> tuple[dict | None, str | None]:
    """(gear, category) for a kit line, preferring what is already owned (§8).

    `exclude` holds gear already committed to another line, and passing it is
    NOT optional in practice. A mandatory kit list routinely names several
    things that land in one category — Oman's names a survival blanket AND a
    whistle, both `safety` — and without this the same item answers both. The
    locker holds one safety item; the pack claimed it twice and reported the
    race requirement satisfied. One physical object cannot be in two places,
    and a list that says otherwise is worse than no list: it reports a
    requirement met that will be checked at a kit table.

    Selection among several candidates in the same category is deterministic
    and stated, so the same locker always produces the same pack:

        1. an item whose NAME echoes the requirement
        2. a favourite
        3. the lightest, because every gram is carried the whole way
        4. the oldest record
        5. the id, which is unique and therefore always breaks the tie

    Step 5 is not decoration. Without it, two items matching on every earlier
    key leave the sort tied, and a stable sort then returns whichever arrived
    first — which is row order from PostgREST, which has no ORDER BY and is
    free to change after an UPDATE moves a row. The pack would quietly pick a
    different headlamp on different days with nothing having changed. VoyageOS
    shipped exactly this bug in its kit matcher and only found it with a
    triple-apply check.

    Retired, lost and damaged gear is never offered. It is exactly the case
    where "you already own one" is wrong.
    """
    category = category_for(line)
    if category is None:
        return (None, None)

    taken = exclude or set()
    candidates = [g for g in locker
                  if g.get("category_key") == category
                  and g.get("status") == "active"
                  and g["id"] not in taken]
    if not candidates:
        return (None, category)

    def rank(gear: dict):
        return (
            0 if gear_matches_line(gear, line) else 1,
            0 if gear.get("favorite") else 1,
            gear.get("weight_g") if gear.get("weight_g") is not None else 10**9,
            str(gear.get("created_at") or ""),
            str(gear.get("id") or ""),
        )

    return (sorted(candidates, key=rank)[0], category)
