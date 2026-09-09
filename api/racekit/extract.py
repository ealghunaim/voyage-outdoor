"""Reading a race page for its mandatory equipment (§24).

THIS IS THE ONLY PLACE A MODEL PRODUCES FACTS RATHER THAN SENTENCES, and it is
fenced accordingly:

  * The output is schema-constrained, so a malformed kit list is impossible
    rather than merely unlikely. There is no `json.loads` in a retry loop here
    and no regex salvaging a half-written object.
  * The model does not assign categories. Category is what decides whether an
    item is matched to gear you own, which is an engine's job (§0.5) — asking
    the model for it would let a model decision reach a classification.
  * Nothing is written to an adventure by this module. It produces a DRAFT. A
    human accepts it, item by item, and the accepting is what makes it
    authoritative. See router.py.

Everything the model returns is stored with the bytes it read, the URL, and the
date — because a kit list without provenance is a rumour, and next year's
edition changes it.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from api.ai import prompts
from api.ai_gateway import gateway

TASK = "race_kit_extract"

#: How much page text to send. A race page is mostly navigation, sponsors and
#: results; the equipment section is a few hundred words of it. This bounds cost
#: without bounding correctness — see `narrow` for what happens above it.
MAX_CHARS = 60_000
#: Kept around every keyword hit when narrowing. Wide enough that a table which
#: names the section in a heading and lists the items well below it survives.
WINDOW = 6_000
#: Always kept, whatever the keywords say: the top of the page carries the race
#: name and the edition, which are provenance.
HEAD = 4_000

#: Multilingual on purpose. UTMB publishes in French, the Dolomites in Italian,
#: Transgrancanaria in Spanish, and a runner's races are not all in English.
KEYWORDS = re.compile(
    r"mandator|compulsor|required equipment|equipment list|kit list|"
    r"obligatoire|matériel|materiel|obbligatori|attrezzatura|"
    r"obligatorio|obligatoria|material obligatorio|equipamiento|"
    r"pflichtausrüstung|ausrüstung|verplicht|utrustning",
    re.I)


class KitItem(BaseModel):
    """One line off the race's list.

    THREE FIELDS, NOT ONE, and the split is the point. Run against Oman by UTMB
    the first version returned this as a single item name:

        "Smartphone - LiveTrail application must be installed and activated
         with international roaming for its use in Oman. Must be reachable at
         any time before, during and after the race. Keep the phone on, airplane
         mode is forbidden and could give rise to penalties. An external battery
         is highly recommended."

    Faithful to the page and useless as a pack line — the pack list became
    twenty-three paragraphs, and the attribute validator then cut each one at
    200 characters. What a runner ticks off in a hallway is "Smartphone"; the
    rest is why, and it belongs beside the item rather than inside its name.

    No category field, deliberately — see the module docstring.
    """
    text: str = Field(
        description="The item itself, as a checklist line — the noun plus any "
                    "specification or minimum that identifies it. Keep numbers "
                    "and units: 'Waterproof jacket, min 10,000mm', 'Warm second "
                    "layer, min 180g', 'Head torch with spare batteries'. Under "
                    "120 characters. Do NOT put the page's explanation, "
                    "justification, or penalty warnings here.")
    detail: str | None = Field(
        description="The page's own explanation for this item, if it gives one "
                    "— what it is for, how it must be used, what happens "
                    "without it. Verbatim where practical. Null if the page "
                    "just lists the item.")
    condition: str | None = Field(
        description="A SHORT label, at most 8 words, for when this item is "
                    "required — 'cold weather kit', 'over 50km only', 'camp "
                    "bag', 'night section'. Null if it is required "
                    "unconditionally. Do not repeat the page's full "
                    "explanatory sentence here; a runner is reading this "
                    "beside the item on a phone.")


class RaceKit(BaseModel):
    """The extraction. Every field is required and nullable rather than
    optional-with-a-default: a null says the page did not state it, which is
    information, while an absent key would be indistinguishable from the model
    forgetting to answer."""
    race_name: str | None = Field(description="Race name as the page states it.")
    edition: str | None = Field(description="Year or edition, as stated.")
    event: str | None = Field(
        description="Which event or distance this list applies to, if the page "
                    "publishes several.")
    items: list[KitItem] = Field(description="Mandatory items only.")
    recommended: list[str] = Field(
        description="Items the page suggests but does not require.")
    note: str | None = Field(
        description="Anything a runner should know about how this page was "
                    "read: an ambiguity, a list that looked partial, or that "
                    "the page carried no equipment list at all.")


def has_kit_signal(text: str) -> bool:
    """Is there any sign of an equipment list in this text at all?

    ADDED AFTER POINTING THE FETCHER AT REAL RACE SITES. montblanc.utmb.world
    returns 5,087 characters of navigation chrome and a list of event dates —
    the page builds itself in the browser, so the kit list is not in the HTML.
    That sails past the "came back essentially empty" check, and the model then
    correctly reports no equipment list, having been paid to read a menu.

    So this is a deterministic gate in front of a paid call: no keyword in any
    of the languages the narrowing already knows, no extraction. It costs
    nothing and the message it produces is the true one — "this page needs
    JavaScript, paste it instead" — rather than the misleading "no equipment
    list found", which sounds like a fact about the race.

    URL FETCHES ONLY. Someone who has pasted the bullet points of a kit list has
    already decided what it is, and their paste may not contain the heading.
    """
    return bool(KEYWORDS.search(text))


def narrow(text: str) -> tuple[str, dict]:
    """Cut a long page down to the parts that could hold a kit list.

    Head truncation alone would be wrong in the ordinary case: the equipment
    section of a race site is usually near the BOTTOM, under the results and the
    sponsors. So the page is kept where the keywords are, plus the head for the
    race name — and if no keyword appears anywhere, the head is all there is and
    the caller is told so rather than being handed a quiet truncation.
    """
    if len(text) <= MAX_CHARS:
        return text, {"chars": len(text), "narrowed": False, "truncated": False}

    spans: list[tuple[int, int]] = [(0, HEAD)]
    for match in KEYWORDS.finditer(text):
        spans.append((max(0, match.start() - WINDOW // 2),
                      min(len(text), match.start() + WINDOW)))

    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    out, used, truncated = [], 0, False
    for start, end in merged:
        piece = text[start:end]
        if used + len(piece) > MAX_CHARS:
            piece = piece[: MAX_CHARS - used]
            truncated = True
        out.append(piece)
        used += len(piece)
        if truncated:
            break

    return ("\n\n[…]\n\n".join(out),
            {"chars": used, "narrowed": True, "truncated": truncated,
             "keyword_hits": len(merged) - 1})


def read_kit(source_text: str, *, source_label: str,
             db=None, user_id: str | None = None) -> tuple[RaceKit, dict]:
    """Run the extraction. Returns the parsed kit and what it cost to read."""
    body, stats = narrow(source_text)
    result = gateway.extract(
        TASK, prompts.RACE_KIT_EXTRACT,
        f"SOURCE: {source_label}\n\n{body}",
        RaceKit, db=db, user_id=user_id)
    return result.parsed, {
        **stats,
        "model": result.model,
        "cost_usd": result.cost_usd,
        "latency_ms": result.latency_ms,
        "prompt_version": gateway.PROMPT_VERSION,
    }
