"""Discover — the aggregation, and the line where it stops being a shop.

The interesting assertions here are not "does it find the gap". They are the
two §14 rules that are one `if` away from being violated at any time: a merely
suggested category must not be offered products, and what you do NOT need has
to appear as a finding rather than as silence.
"""
from api.engines import discover

ADVENTURES = [
    {"id": "a1", "title": "Oman by UTMB", "start_date": "2026-12-10"},
    {"id": "a2", "title": "Jebel Shams ridge", "start_date": "2026-09-13"},
    {"id": "a3", "title": "Wadi night run", "start_date": "2026-10-02"},
]

CATALOG = [
    {"id": "p1", "brand": "Norda", "model": "005", "category_key": "shoes",
     "generation": None, "specs": {"lug_mm": 4.0}},
    {"id": "p2", "brand": "Arc'teryx", "model": "Norvan Shell",
     "category_key": "jacket", "generation": None,
     "specs": {"hydrostatic_head_mm": 20000}},
    {"id": "p3", "brand": "Black Diamond", "model": "Distance Z",
     "category_key": "poles", "generation": None, "specs": {}},
]


def pack(items, warnings=(), ready=False):
    return {"list": {"id": "l1"}, "items": items, "warnings": list(warnings),
            "readiness": {"ready": ready}}


def missing(name, category, critical=False, source="rule"):
    return {"name": name, "classification": "missing", "category_key": category,
            "critical": critical, "source": source,
            "reason": f"Nothing in your locker fits."}


def test_a_gap_is_counted_across_adventures_not_one_at_a_time():
    """The whole reason this screen exists. 'No waterproof jacket' looks like a
    fact about Oman until you notice it is also true of the other two."""
    packs = {
        "a1": pack([missing("Jacket", "jacket", critical=True, source="mandatory")]),
        "a2": pack([missing("Jacket", "jacket")]),
        "a3": pack([missing("Jacket", "jacket")]),
    }
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    jacket = [f for f in result.findings if f.category_key == "jacket"][0]
    assert jacket.kind == "gap"
    assert len(jacket.adventures) == 3
    assert jacket.critical is True
    assert jacket.mandatory is True
    assert "Oman by UTMB" in jacket.detail


def test_a_required_gap_may_point_at_the_catalog():
    packs = {"a1": pack([missing("Jacket", "jacket", critical=True)])}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    jacket = [f for f in result.findings if f.category_key == "jacket"][0]
    assert [c["model"] for c in jacket.catalog] == ["Norvan Shell"]


def test_a_SUGGESTED_gap_may_not(monkeypatch):
    """§8 and §14. A category no rule insisted on is where a tool turns into a
    storefront, and the difference is one `if`. The sentence has to say so out
    loud too — a conspicuously empty space reads as an omission."""
    packs = {"a1": pack([], warnings=[{
        "key": "could_help", "severity": "note",
        "message": "Conditions would suit poles.",
        "detail": {"categories": ["poles"],
                   "reasons": {"poles": "1800 m of climbing."}},
    }])}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    poles = [f for f in result.findings if f.category_key == "poles"][0]
    assert poles.required is False
    assert poles.catalog == []          # the catalog HAS poles; they are withheld
    assert "Not required" in poles.detail
    assert "finish without" in poles.detail


def test_nothing_anywhere_says_buy():
    """The same assertion the pack engine carries. §14 calls the willingness to
    recommend not buying the trust anchor; this is what keeps it true as the
    wording gets edited."""
    packs = {
        "a1": pack([missing("Jacket", "jacket", critical=True)],
                   warnings=[{"key": "could_help",
                              "detail": {"categories": ["poles"], "reasons": {}}}]),
    }
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    blob = " ".join(f.title + " " + f.detail for f in result.findings).lower()
    for word in ("buy", "purchase", "shop", "deal", "price", "%off"):
        assert word not in blob


def test_what_you_do_not_need_is_a_finding_not_silence():
    """A Discover screen that only ever lists what is absent is a shop whatever
    its buttons say."""
    packs = {"a1": pack([
        {"name": "Headlamp", "classification": "not_needed",
         "category_key": "headlamp", "critical": False, "source": "rule",
         "reason": "No darkness expected."},
    ])}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    settled = [f for f in result.findings if f.kind == "settled"]
    assert any(f.category_key == "headlamp" for f in settled)
    assert "ruled it out" in settled[0].detail


def test_a_ready_pack_is_reported_as_done():
    packs = {"a2": pack([], ready=True)}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    done = [f for f in result.findings if f.kind == "settled"]
    assert done and "Nothing to do" in done[0].detail
    assert done[0].title == "Jebel Shams ridge"


def test_health_wording_is_carried_not_rewritten():
    """§12 survives this layer or it does not survive at all. The engine emits a
    band; restating it here as a deadline would undo it at the last step."""
    attention = [{"id": "g1", "name": "Norda 005", "category_key": "shoes",
                  "state": "inspect",
                  "message": "640-960 km expected; 710 km on them — worth a look."}]
    result = discover.generate(ADVENTURES, {}, [], attention, CATALOG)
    flagged = [f for f in result.findings if f.kind == "attention"][0]
    assert flagged.detail == attention[0]["message"]
    assert "640-960" in flagged.detail


def test_an_unmatched_mandatory_line_still_counts_as_a_gap():
    """A kit line the matcher could not place has no category. Keying gaps on
    category alone would drop it, and it is mandatory."""
    packs = {"a1": pack([{
        "name": "Ceremonial trebuchet", "classification": "missing",
        "category_key": None, "critical": True, "source": "mandatory",
        "reason": "On the race's mandatory kit list.",
    }])}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    assert any(f.title == "Ceremonial trebuchet" for f in result.findings)


def test_an_empty_record_produces_nothing_rather_than_breaking():
    """Every path has to read correctly at zero: §0.4 leaves the catalog
    frequently empty, and a new user has no adventures and no packs."""
    result = discover.generate([], {}, [], [], [])
    assert result.findings == []
    assert result.snapshot["catalog_size"] == 0
    assert result.ruleset == "discover-v1"


def test_owned_categories_are_not_suggested_back_to_you():
    packs = {"a1": pack([], warnings=[{
        "key": "could_help",
        "detail": {"categories": ["poles"], "reasons": {"poles": "climbing"}}}])}
    locker = [{"id": "g9", "category_key": "poles", "status": "active"}]
    result = discover.generate(ADVENTURES, packs, locker, [], CATALOG)
    assert not any(f.category_key == "poles" for f in result.findings)


def test_critical_gaps_sort_above_the_rest():
    packs = {"a1": pack([
        missing("Socks", "socks"),
        missing("Jacket", "jacket", critical=True),
    ])}
    result = discover.generate(ADVENTURES, packs, [], [], CATALOG)
    gaps = [f for f in result.findings if f.kind == "gap"]
    assert gaps[0].category_key == "jacket"
