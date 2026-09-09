"""The weather layer's decisions, with the network stubbed out.

What is worth testing here is not that Open-Meteo returns JSON — it is the
handful of judgements this module makes on top: which provider wins, what
happens when the primary is rate-limited, and how a date range that reaches
past any forecast horizon is answered.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from api.weather import provider

TODAY = date.today()


@pytest.fixture
def stub(monkeypatch):
    """Replaces both providers. Each call records that it ran, so a test can
    assert the fallback was NOT reached as well as that it was."""
    calls = []

    def make(name, rows):
        def fn(lat, lng, start, end):
            calls.append(name)
            if isinstance(rows, Exception):
                raise rows
            return [{**r, "provider": name} for r in rows]
        return fn

    def install(primary, fallback):
        monkeypatch.setattr(provider, "_open_meteo", make("open-meteo", primary))
        monkeypatch.setattr(provider, "_met_no", make("met-no", fallback))
        return calls

    return install


DAY = [{"forecast_date": TODAY.isoformat(), "temp_min": 4, "temp_max": 19,
        "precip_prob": 20, "wind_kph": 14, "uv": 6}]


def test_primary_wins_and_the_fallback_is_not_called(stub):
    calls = stub(primary=DAY, fallback=DAY)
    rows = provider.forecast(23.6, 58.5, TODAY, TODAY)
    assert rows[0]["provider"] == "open-meteo"
    assert calls == ["open-meteo"], "fallback ran when it should not have"


def test_fallback_runs_when_the_primary_raises(stub):
    """Open-Meteo rate-limits per IP, and a cloud host shares its egress IP
    with strangers — so the primary failing is an ordinary Tuesday, not an
    exceptional event."""
    calls = stub(primary=RuntimeError("429 rate limited"), fallback=DAY)
    rows = provider.forecast(23.6, 58.5, TODAY, TODAY)
    assert rows[0]["provider"] == "met-no"
    assert calls == ["open-meteo", "met-no"]


def test_fallback_runs_when_the_primary_returns_nothing(stub):
    """An empty answer is a failure too. Returning [] from the primary without
    trying the fallback would show 'no forecast' for a place that has one."""
    calls = stub(primary=[], fallback=DAY)
    assert provider.forecast(23.6, 58.5, TODAY, TODAY)[0]["provider"] == "met-no"
    assert calls == ["open-meteo", "met-no"]


def test_both_failing_is_empty_rather_than_an_exception(stub):
    """A missing forecast degrades the adventure screen. A raised exception
    would take it down, and this call sits on the path that renders a race
    someone is about to start."""
    stub(primary=RuntimeError("down"), fallback=RuntimeError("also down"))
    assert provider.forecast(23.6, 58.5, TODAY, TODAY) == []


def test_a_date_far_in_the_future_is_empty_not_an_error(stub):
    """An adventure is usually planned months out. The honest answer then is
    'no forecast yet', which is an empty list — not an error the screen has to
    apologise for."""
    calls = stub(primary=DAY, fallback=DAY)
    far = TODAY + timedelta(days=300)
    assert provider.forecast(23.6, 58.5, far, far) == []
    assert calls == [], "a provider was called for a date beyond the horizon"


@pytest.fixture
def spy(monkeypatch):
    """Records the range the provider was actually asked for.

    Through monkeypatch rather than by assigning to the module: a direct
    assignment survives the test that made it and silently changes what the
    next one is testing."""
    seen = {}

    def fn(lat, lng, start, end):
        seen["start"], seen["end"] = start, end
        return [{**DAY[0], "provider": "open-meteo"}]

    monkeypatch.setattr(provider, "_open_meteo", fn)
    return seen


def test_a_range_starting_in_the_past_is_clamped_to_today(spy):
    """Editing an adventure's dates after it has started must not ask a
    forecast API for last week."""
    provider.forecast(23.6, 58.5, TODAY - timedelta(days=10), TODAY + timedelta(days=2))
    assert spy["start"] == TODAY


def test_a_long_range_is_clamped_to_the_horizon(spy):
    provider.forecast(23.6, 58.5, TODAY, TODAY + timedelta(days=200))
    assert spy["end"] == TODAY + timedelta(days=provider.HORIZON_DAYS)


def test_met_no_reports_unknown_rain_as_none_not_zero(monkeypatch):
    """MET Norway's compact product carries no precipitation probability.
    Filling that with 0 would state 'no chance of rain' on the strength of the
    provider not having an opinion — and a rule engine downstream would then
    leave a jacket off a pack list because of it."""
    class FakeResponse:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return {"properties": {"timeseries": [
                {"time": f"{TODAY.isoformat()}T09:00:00Z",
                 "data": {"instant": {"details":
                          {"air_temperature": 12.0, "wind_speed": 3.0}}}},
                {"time": f"{TODAY.isoformat()}T15:00:00Z",
                 "data": {"instant": {"details":
                          {"air_temperature": 21.0, "wind_speed": 6.0}}}},
            ]}}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(provider.httpx, "Client", FakeClient)
    rows = provider._met_no(23.6, 58.5, TODAY, TODAY)
    assert len(rows) == 1
    assert rows[0]["precip_prob"] is None
    assert rows[0]["temp_min"] == 12.0 and rows[0]["temp_max"] == 21.0
    # m/s -> km/h, taking the day's maximum
    assert rows[0]["wind_kph"] == pytest.approx(21.6)
