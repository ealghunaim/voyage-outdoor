"""Discover — what your own record already says, aggregated (§14).

DETERMINISTIC AND PURE, like every other engine here. Adventures, their packs
and the locker go in; a set of findings comes out. No model, no clock, no I/O.

WHY THIS IS AN AGGREGATOR AND NOT A FEED. §0.4 says there is no live product
database in V1 — admin-entered records only, seeded with gear you own plus a
small curated set. A discovery feed built on that would be a shop window with
four things in it. §14 independently says Discover must be personalised from the
user's own activities, locker, adventures and equipment age, and explicitly
"not a generic outdoor-news feed". Those two constraints point at the same
build: the interesting signal is already in this database, spread across
adventures nobody looks at side by side.

Three findings, and the third is the one that matters:

    GAPS        categories your packs keep reporting MISSING, counted across
                every adventure rather than one at a time.
    ATTENTION   gear the health engine has flagged, which is §14's "equipment
                age" without pretending to know a failure date (§12).
    SETTLED     things you do NOT need, said out loud.

SETTLED IS NOT PADDING. §14 makes the willingness to recommend *not* buying the
trust anchor of the whole product and says to keep it non-negotiable when this
ships. A Discover screen that only ever lists what is absent is a shop, whatever
its buttons say. So a category no upcoming adventure argues for is a finding in
its own right, with the same weight as a gap.

AND THE CATALOG LINE IS DRAWN HERE (§8, §14). Curated products are offered for
REQUIRED gaps only — an item a race mandates or a rule insists on is a thing you
must have, and pointing at what exists is answering the question. For a merely
suggested category the honest answer is that plenty of people finish without it,
so nothing is offered and the note says so. That is the difference between a
tool and a storefront, and it is one `if` rather than a policy document.
"""
from __future__ import annotations

from dataclasses import dataclass, field

DISCOVER_RULESET = "discover-v1"

#: Classifications that mean "this is absent and something argued for it".
MISSING = "missing"
#: Where an unowned RECOMMENDED category is reported. The pack engine folds
#: these into one note per pack rather than emitting MISSING lines — see
#: engines/pack.py on why a recommendation you do not own is not a missing item.
COULD_HELP = "could_help"


@dataclass(frozen=True)
class Finding:
    kind: str                       # gap · attention · settled
    category_key: str | None
    title: str
    detail: str
    #: Adventure titles this finding is drawn from. Named rather than counted:
    #: "needed for Oman by UTMB and Jebel Shams ridge" is checkable, and "needed
    #: for 2 adventures" is a number the reader has to take on trust.
    adventures: list[str] = field(default_factory=list)
    required: bool = False
    critical: bool = False
    mandatory: bool = False         # came off a race's kit list (§24)
    gear_item_id: str | None = None
    #: Only ever populated for required gaps. See the module docstring.
    catalog: list[dict] = field(default_factory=list)


@dataclass
class DiscoverResult:
    findings: list[Finding]
    snapshot: dict
    ruleset: str = DISCOVER_RULESET


def _label(category: str) -> str:
    return category.replace("_", " ").capitalize()


def generate(adventures: list[dict], packs: dict[str, dict],
             locker: list[dict], attention: list[dict],
             catalog: list[dict] | None = None) -> DiscoverResult:
    """Aggregate one user's record.

    `packs` is keyed by adventure id and holds what packing.service.read
    returns. `attention` is what the gear-health engine already flagged.
    `catalog` is the curated product list, which in V1 is usually tiny and
    frequently empty — every path below has to read correctly at zero.
    """
    catalog = catalog or []
    owned_categories = {g.get("category_key") for g in locker
                        if g.get("status") == "active" and g.get("category_key")}
    titles = {a["id"]: a.get("title") or "Untitled" for a in adventures}

    # ── gaps ───────────────────────────────────────────────────────────────
    gaps: dict[str, dict] = {}
    for adventure_id, pack in packs.items():
        for item in pack.get("items") or []:
            if item.get("classification") != MISSING:
                continue
            category = item.get("category_key")
            # An unmatched mandatory line has no category — it is still a real
            # gap, so it is keyed on its own name rather than dropped.
            key = category or f"name:{item.get('name')}"
            bucket = gaps.setdefault(key, {
                "category_key": category,
                "title": _label(category) if category else str(item.get("name")),
                "adventures": [], "critical": False, "mandatory": False,
                "reason": item.get("reason") or "",
            })
            title = titles.get(adventure_id)
            if title and title not in bucket["adventures"]:
                bucket["adventures"].append(title)
            bucket["critical"] = bucket["critical"] or bool(item.get("critical"))
            bucket["mandatory"] = (bucket["mandatory"]
                                   or item.get("source") == "mandatory")

    # ── suggestions the packs gathered but did not insist on ───────────────
    suggested: dict[str, dict] = {}
    for adventure_id, pack in packs.items():
        for warning in pack.get("warnings") or []:
            if warning.get("key") != COULD_HELP:
                continue
            detail = warning.get("detail") or {}
            for category in detail.get("categories") or []:
                if category in gaps or category in owned_categories:
                    continue
                bucket = suggested.setdefault(category, {
                    "category_key": category,
                    "title": _label(category),
                    "adventures": [],
                    "reason": (detail.get("reasons") or {}).get(category, ""),
                })
                title = titles.get(adventure_id)
                if title and title not in bucket["adventures"]:
                    bucket["adventures"].append(title)

    findings: list[Finding] = []

    for bucket in sorted(gaps.values(),
                         key=lambda b: (not b["critical"],
                                        -len(b["adventures"]), b["title"])):
        where = _phrase(bucket["adventures"])
        findings.append(Finding(
            kind="gap",
            category_key=bucket["category_key"],
            title=bucket["title"],
            detail=(f"Needed for {where} and not in your locker."
                    + (" This one is on a race's mandatory kit list."
                       if bucket["mandatory"] else "")),
            adventures=bucket["adventures"],
            required=True,
            critical=bucket["critical"],
            mandatory=bucket["mandatory"],
            catalog=_catalog_for(bucket["category_key"], catalog),
        ))

    for bucket in sorted(suggested.values(),
                         key=lambda b: (-len(b["adventures"]), b["title"])):
        where = _phrase(bucket["adventures"])
        findings.append(Finding(
            kind="gap",
            category_key=bucket["category_key"],
            title=bucket["title"],
            # NO CATALOG, and the sentence says why rather than leaving a
            # conspicuous absence. §8: do not turn every recommendation into a
            # purchase recommendation.
            detail=(f"Conditions on {where} would suit one. Not required — "
                    f"plenty of people finish without."),
            adventures=bucket["adventures"],
            required=False,
        ))

    # ── attention: what the health engine already said ─────────────────────
    for item in attention:
        findings.append(Finding(
            kind="attention",
            category_key=item.get("category_key"),
            title=item.get("name") or "Gear",
            # The engine's own wording, band and all. Restating it as a
            # deadline here would undo §12 at the last step.
            detail=item.get("message") or "Worth a look.",
            gear_item_id=item.get("id"),
        ))

    # ── settled: what you do not need ──────────────────────────────────────
    findings.extend(_settled(packs, titles))

    return DiscoverResult(findings=findings, snapshot={
        "ruleset": DISCOVER_RULESET,
        "adventures": len(adventures),
        "packs": len(packs),
        "locker_size": len([g for g in locker if g.get("status") == "active"]),
        "gaps": len(gaps),
        "suggested": len(suggested),
        "attention": len(attention),
        "catalog_size": len(catalog),
    })


def _settled(packs: dict[str, dict], titles: dict[str, str]) -> list[Finding]:
    """Categories a rule actively ruled out, and gear already verified.

    §14's trust anchor, made into rows. Both halves are things the record can
    say with certainty and that nobody would otherwise be told: a rule decided
    you can leave the headlamp, or you have already checked everything a race
    demands. Neither is an absence of news.
    """
    out: list[Finding] = []
    ruled: dict[str, list[str]] = {}
    for adventure_id, pack in packs.items():
        for item in pack.get("items") or []:
            if item.get("classification") != "not_needed":
                continue
            category = item.get("category_key")
            if not category:
                continue
            where = ruled.setdefault(category, [])
            title = titles.get(adventure_id)
            if title and title not in where:
                where.append(title)

    for category, where in sorted(ruled.items()):
        out.append(Finding(
            kind="settled",
            category_key=category,
            title=_label(category),
            detail=f"Nothing you need for {_phrase(where)} — a rule ruled it out.",
            adventures=where,
        ))

    for adventure_id, pack in packs.items():
        readiness = pack.get("readiness") or {}
        if readiness.get("ready"):
            out.append(Finding(
                kind="settled", category_key=None,
                title=titles.get(adventure_id, "An adventure"),
                detail="Everything required is packed and every critical item "
                       "verified. Nothing to do for this one.",
                adventures=[titles.get(adventure_id, "")],
            ))
    return out


def _catalog_for(category: str | None, catalog: list[dict]) -> list[dict]:
    """Curated products in a category, for REQUIRED gaps only.

    Deliberately no price and no link — `products.specs` is objective fact
    (§28) and this returns fact. The moment a price appears here the screen
    starts answering a different question from the one the runner asked.
    """
    if not category:
        return []
    return [{
        "id": p["id"], "brand": p.get("brand"), "model": p.get("model"),
        "generation": p.get("generation"), "specs": p.get("specs") or {},
    } for p in catalog if p.get("category_key") == category][:5]


def _phrase(names: list[str]) -> str:
    """'Oman by UTMB' · 'Oman and Jebel Shams' · 'Oman, Jebel Shams and 2 more'."""
    clean = [n for n in names if n]
    if not clean:
        return "an upcoming adventure"
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return f"{clean[0]}, {clean[1]} and {len(clean) - 2} more"
