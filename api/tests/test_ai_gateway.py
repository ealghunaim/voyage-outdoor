"""The gateway, with a fake Anthropic client.

These are the paths that only appear in production: a classifier declining, a
beta the account cannot use, a rate limit, a truncated extraction. Each one has
a specific correct behaviour and a tempting wrong one — a 500, an IndexError, a
retry that cannot succeed — and none of them can be exercised against the real
API on demand.
"""
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from fastapi import HTTPException

from api.ai_gateway import gateway


def api_error(cls, message: str, status: int):
    """The SDK's exceptions want a real httpx response to read a request off."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=request),
               body=None)


class FakeUsage(SimpleNamespace):
    pass


def message(text="a paragraph", *, model="claude-opus-5", stop="end_turn",
            tin=1000, tout=200, cache_read=0, cache_write=0, details=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=text)],
        model=model, stop_reason=stop, stop_details=details,
        usage=FakeUsage(input_tokens=tin, output_tokens=tout,
                        cache_read_input_tokens=cache_read,
                        cache_creation_input_tokens=cache_write),
    )


class FakeClient:
    """Records calls; returns or raises whatever the test queued."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        outer = self

        class Messages:
            def create(self, **kwargs):
                return outer._next("create", kwargs)

            def parse(self, **kwargs):
                return outer._next("parse", kwargs)

        self.messages = Messages()
        self.beta = SimpleNamespace(messages=Messages())

    def _next(self, kind, kwargs):
        self.calls.append((kind, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _fallback_on(monkeypatch):
    # This flag is process-global by design (see the gateway), so each test
    # resets it or they leak into each other in file order.
    monkeypatch.setattr(gateway, "_fallback_available", True)


def use(monkeypatch, *responses) -> FakeClient:
    client = FakeClient(responses)
    monkeypatch.setattr(gateway, "_client", lambda: client)
    return client


def test_refusal_is_a_422_not_a_crash(monkeypatch):
    """A refusal arrives as a successful HTTP 200 with empty content. Reading
    content[0] first raises IndexError and surfaces as a 500 — an outage, for
    something that is not one."""
    refused = message(stop="refusal", details=SimpleNamespace(category="cyber"))
    refused.content = []
    use(monkeypatch, refused)
    with pytest.raises(HTTPException) as e:
        gateway.complete("pack_narrative", "sys", "user")
    assert e.value.status_code == 422
    assert "computed here, not generated" in e.value.detail


def test_a_refused_call_is_still_billed_and_logged(monkeypatch):
    """The tokens were spent whether or not we got prose. Skipping the log
    would leave the daily cap under-counting exactly the calls that produced
    nothing."""
    refused = message(stop="refusal")
    refused.content = []
    use(monkeypatch, refused)
    logged = []
    db = _fake_db(logged)
    with pytest.raises(HTTPException):
        gateway.complete("pack_narrative", "sys", "user", db=db, user_id="u1")
    assert len(logged) == 1
    assert logged[0]["stop_reason"] == "refusal"
    assert logged[0]["cost_usd"] > 0


def test_cost_follows_the_model_that_answered(monkeypatch):
    """After a server-side fallback the answering model is not the one asked
    for, and billing follows the former. Pricing on the requested model would
    make ai_runs confidently wrong, which is worse than not logging it."""
    use(monkeypatch, message(model="claude-haiku-4-5", tin=1_000_000, tout=0))
    result = gateway.complete("pack_narrative", "sys", "user")
    assert result.served_by_fallback is True
    assert result.cost_usd == pytest.approx(1.0)      # haiku input, not opus


def test_cache_reads_are_not_billed_as_fresh_input(monkeypatch):
    """A cache read costs ~10% of input. Charging it at full rate over-reports
    every warm call and fires the daily cap early — locking someone out of
    explanations they had not paid for."""
    use(monkeypatch, message(tin=0, tout=0, cache_read=1_000_000))
    result = gateway.complete("pack_narrative", "sys", "user")
    assert result.cost_usd == pytest.approx(0.5)      # $5/M x 0.1


def test_unknown_model_is_priced_at_the_top_rate(monkeypatch):
    """Guessing low would let an unpriced model run past the daily cap
    unnoticed."""
    use(monkeypatch, message(model="claude-something-new", tin=1_000_000, tout=0))
    assert gateway.complete("pack_narrative", "s", "u").cost_usd == pytest.approx(5.0)


def test_unusable_fallback_beta_downgrades_once_and_stays_down(monkeypatch):
    """One 400 saying the account cannot use the beta is a configuration fact,
    not a transient failure. Re-learning it every request would cost a wasted
    round trip per call forever."""
    bad = api_error(anthropic.BadRequestError, "fallbacks: unsupported beta", 400)
    client = use(monkeypatch, bad, message(), message())

    first = gateway.complete("pack_narrative", "sys", "user")
    assert first.text == "a paragraph"
    assert gateway._fallback_available is False

    gateway.complete("pack_narrative", "sys", "user")
    # Three calls total: the failed beta attempt, its retry, and one direct
    # call — not a second beta attempt.
    assert len(client.calls) == 3
    assert all("fallbacks" not in kw for _, kw in client.calls[1:])


def test_an_unrelated_400_is_not_swallowed_as_a_beta_problem(monkeypatch):
    """Disabling fallbacks because a prompt was malformed would hide the actual
    bug behind a silently degraded config."""
    use(monkeypatch, api_error(
        anthropic.BadRequestError,
        "messages: text content blocks must be non-empty", 400))
    with pytest.raises(HTTPException) as e:
        gateway.complete("pack_narrative", "sys", "user")
    assert e.value.status_code == 502
    assert gateway._fallback_available is True


def test_rate_limit_maps_to_429_not_502(monkeypatch):
    """The SDK has already retried this with backoff. A 502 tells the app to
    look for a server fault; a 429 tells it to wait, which is the truth."""
    use(monkeypatch, api_error(anthropic.RateLimitError, "slow down", 429))
    with pytest.raises(HTTPException) as e:
        gateway.complete("ask_outdoor", "sys", "user")
    assert e.value.status_code == 429


def test_missing_key_is_503_and_never_reaches_the_network(monkeypatch):
    monkeypatch.setattr(gateway.settings, "llm_api_key", "")
    gateway._client.cache_clear()
    with pytest.raises(HTTPException) as e:
        gateway.complete("ask_outdoor", "sys", "user")
    assert e.value.status_code == 503
    assert "Everything else works without them" in e.value.detail
    gateway._client.cache_clear()


def test_long_system_prompt_is_marked_cacheable(monkeypatch):
    client = use(monkeypatch, message())
    gateway.complete("pack_narrative", "S" * 5000, "user")
    system = client.calls[0][1]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_short_system_prompt_is_not(monkeypatch):
    """Below the cacheable minimum the flag does nothing except add a field."""
    client = use(monkeypatch, message())
    gateway.complete("pack_narrative", "short", "user")
    assert isinstance(client.calls[0][1]["system"], str)


def test_thinking_stays_on_and_effort_is_the_dial(monkeypatch):
    """With thinking disabled, Opus 5 occasionally writes what should have been
    a tool call into its visible text and leaks internal tags. Effort is the
    supported cost lever; disabling thinking is not."""
    client = use(monkeypatch, message(), message())
    gateway.complete("ask_outdoor", "sys", "user")
    gateway.complete("race_kit_extract", "sys", "user")
    assert client.calls[0][1]["thinking"] == {"type": "adaptive"}
    assert client.calls[0][1]["output_config"]["effort"] == "low"
    assert client.calls[1][1]["output_config"]["effort"] == "high"


def test_ceilings_leave_room_for_thinking_and_text(monkeypatch):
    """max_tokens bounds thinking PLUS text. A 600-token ceiling on a
    one-sentence explanation is not tight, it is unreachable — the model spends
    the budget reasoning and returns an empty string."""
    for task in gateway.TASK_MAX_TOKENS.values():
        assert task >= 3000


def test_extraction_truncated_is_not_offered_as_a_result(monkeypatch):
    """A kit list cut off mid-object is a SHORTER kit list. Returning it is how
    someone arrives at a check missing the item that got cut."""
    class Kit:
        pass
    truncated = message(stop="max_tokens")
    truncated.parsed_output = Kit()
    use(monkeypatch, truncated)
    with pytest.raises(HTTPException) as e:
        gateway.extract("race_kit_extract", "sys", "page", Kit)
    assert e.value.status_code == 502
    assert "Paste just the mandatory-equipment section" in e.value.detail


def test_extraction_returns_the_validated_object(monkeypatch):
    class Kit:
        items = ["jacket"]
    ok = message(stop="end_turn")
    ok.parsed_output = Kit()
    use(monkeypatch, ok)
    result = gateway.extract("race_kit_extract", "sys", "page", Kit)
    assert result.parsed.items == ["jacket"]


def _fake_db(sink):
    class Table:
        def __init__(self, name):
            self.name = name

        def insert(self, row):
            sink.append(row)
            return self

        def execute(self):
            return SimpleNamespace(data=[{}])

    return SimpleNamespace(table=lambda name: Table(name))
