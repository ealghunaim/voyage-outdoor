"""The boundary in §11, tested without spending a token.

context.py is the last pure step before a model call, so what it produces is
exactly what the model is allowed to know. These assert the two properties the
narrative's honesty rests on: nothing decided is dropped, and nothing undecided
is added.
"""
from api.ai import context

ADVENTURE = {
    "title": "Oman by UTMB",
    "start_date": "2026-11-26",
    "status": "planned",
    "attributes": {
        "distance_km": 50, "elevation_gain_m": 2600, "expected_hours": 11,
        "night_hours": 3, "terrain": ["mountain", "rock"],
        "self_supported": True, "race_name": "Oman by UTMB",
    },
}

STORED = {
    "list": {"id": "list-1"},
    "items": [
        {"id": "a", "name": "Survival blanket", "classification": "missing",
         "state": "not_selected", "critical": True, "source": "mandatory",
         "reason": "Mandatory kit, and there is no safety in your locker."},
        {"id": "b", "name": "Petzl Swift RL", "classification": "required",
         "state": "packed", "critical": True, "source": "rule",
         "reason": "3 h of this is in the dark."},
        {"id": "c", "name": "Norda 005", "classification": "required",
         "state": "not_selected", "critical": False, "source": "rule",
         "reason": "You are running; shoes are the one thing without an alternative."},
        {"id": "d", "name": "Buff", "classification": "optional",
         "state": "not_selected", "critical": False, "source": "rule",
         "reason": "In your locker; no rule argues for or against it."},
    ],
    "warnings": [
        {"key": "mandatory_missing", "severity": "critical",
         "message": "Required by the race and not in your locker: survival blanket."},
    ],
    "readiness": {"required_total": 2, "required_packed": 1, "required_verified": 0,
                  "remaining": 1, "critical_total": 2, "critical_unverified": 2,
                  "missing_total": 1, "percent": 50, "ready": False},
}

WEATHER = [{"forecast_date": "2026-11-26", "temp_min": 4, "temp_max": 24,
            "precip_prob": 10, "wind_kph": 22, "uv": 7, "provider": "met"}]


def test_every_decision_crosses_the_boundary():
    """A summariser that dropped MISSING to save tokens would produce a
    confident paragraph about a pack with a hole in it."""
    text = context.pack_context(ADVENTURE, STORED, WEATHER)
    for line in ("Survival blanket", "Petzl Swift RL", "Norda 005"):
        assert line in text
    assert "MISSING" in text
    assert "not in your locker" in text
    assert "50%" in text
    assert "critical items: 2" in text


def test_warnings_are_carried_not_summarised():
    text = context.pack_context(ADVENTURE, STORED, WEATHER)
    assert "[critical]" in text
    assert "survival blanket" in text.lower()


def test_missing_ranks_above_optional_in_the_text():
    """Order is consequence, not the alphabet: what ends a race is read first."""
    text = context.pack_context(ADVENTURE, STORED, WEATHER)
    assert text.index("MISSING") < text.index("REQUIRED") < text.index("OPTIONAL")


def test_absent_forecast_is_stated_not_omitted():
    """Silence reads as 'no weather worth mentioning'. It is not the same fact
    as 'nobody knows yet', and the two produce different paragraphs."""
    text = context.pack_context(ADVENTURE, STORED, [])
    assert "none stored" in text


def test_optional_items_are_capped_but_counted():
    many = {**STORED, "items": STORED["items"] + [
        {"id": f"x{i}", "name": f"Thing {i}", "classification": "optional",
         "state": "not_selected", "critical": False, "reason": ""}
        for i in range(20)]}
    text = context.pack_context(ADVENTURE, many, WEATHER)
    assert "more owned items" in text
    # Capped, but the total is still stated — nothing is hidden, only
    # un-enumerated.
    assert "OPTIONAL — owned, no rule either way (21)" in text


def test_health_band_reaches_the_model_as_a_band():
    """§12 is only holdable downstream if the range survives this step. A
    context builder that wrote 'about 800 km' would hand the model a point
    estimate and make the rule unenforceable in the prompt."""
    locker = [{"name": "Norda 005", "category_key": "shoes", "weight_g": 210,
               "health_detail": {"message": "640-960 km expected; 710 km on them"}}]
    text = context.locker_context(locker)
    assert "640-960 km" in text


def test_fingerprint_moves_when_an_item_is_packed():
    before = context.fingerprint(STORED)
    after = context.fingerprint({
        **STORED,
        "items": [{**i, "state": "packed"} if i["id"] == "c" else i
                  for i in STORED["items"]],
    })
    assert before != after


def test_fingerprint_ignores_a_rename():
    """Regenerating on every edit would spend money to change nothing. A
    paragraph that never named the item is not wrong because it was renamed."""
    renamed = {**STORED,
               "items": [{**i, "name": "Buff (blue)"} if i["id"] == "d" else i
                         for i in STORED["items"]]}
    assert context.fingerprint(STORED) == context.fingerprint(renamed)


def test_fingerprint_is_order_independent():
    shuffled = {**STORED, "items": list(reversed(STORED["items"]))}
    assert context.fingerprint(STORED) == context.fingerprint(shuffled)
