"""Weather and geocoding providers — a resilient chain, no API key required.

Primary: Open-Meteo. Rich daily fields and free, but it rate-limits per IP, and
a cloud host's egress IP is shared with whoever else is on that machine — so
the limit can be exhausted by strangers.

Fallback: MET Norway. Cloud-friendly, requires an identifying User-Agent per
their terms of service, and carries NO precipitation probability. That gap is
passed through as null rather than filled with a zero: "no chance of rain" and
"this provider does not say" are different claims, and only one of them is
true. Anything reading these rows must treat null as unknown.

Every failure logs and returns empty. A missing forecast degrades the adventure
screen; a raised exception would take it down.
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
MET_NO_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

#: MET Norway's ToS requires a real identifier with a contact route. A generic
#: agent gets blocked, and being blocked here is silent — the fallback simply
#: stops working and nobody notices until the primary is also down.
USER_AGENT = "VoyageOutdoor/0.1 (+https://github.com/ealghunaim/VoyageOS)"

#: Open-Meteo publishes 16 days. Beyond that a forecast is climate, not
#: weather, and presenting it beside a real one would be the kind of false
#: precision §12 forbids.
HORIZON_DAYS = 16


def geocode(place_name: str, country_code: str | None = None) -> list[dict]:
    """Place name -> candidates, each with coordinates, country and elevation.

    Returns a LIST rather than a best guess. "Chamonix" is unambiguous and
    "Springfield" is not, and a picker that silently chose one of fourteen
    Springfields would put an adventure's weather on the wrong continent
    without anything on screen looking wrong.
    """
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(GEOCODE_URL, params={"name": place_name, "count": 8,
                                           "language": "en"})
            r.raise_for_status()
            results = r.json().get("results") or []
    except Exception as e:                                    # noqa: BLE001
        print(f"[weather] geocode failed for {place_name!r}: {type(e).__name__}: {e}")
        return []

    out = []
    for row in results:
        cc = (row.get("country_code") or "").upper() or None
        if country_code and cc != country_code.upper():
            continue
        out.append({
            "name": row.get("name"),
            "admin": row.get("admin1"),
            "country": row.get("country"),
            "country_code": cc,
            "lat": row.get("latitude"),
            "lng": row.get("longitude"),
            "elevation_m": int(row["elevation"]) if row.get("elevation") is not None else None,
        })
    return out


def _open_meteo(lat: float, lng: float, start: date, end: date) -> list[dict]:
    params = {
        "latitude": lat, "longitude": lng,
        "daily": ",".join([
            "temperature_2m_min", "temperature_2m_max",
            "precipitation_probability_max", "precipitation_sum",
            "wind_speed_10m_max", "uv_index_max",
        ]),
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
        "start_date": start.isoformat(), "end_date": end.isoformat(),
    }
    with httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(FORECAST_URL, params=params)
        r.raise_for_status()
        daily = r.json().get("daily") or {}

    rows = []
    for i, day in enumerate(daily.get("time") or []):
        def at(key):
            values = daily.get(key) or []
            return values[i] if i < len(values) else None
        rows.append({
            "forecast_date": day,
            "temp_min": at("temperature_2m_min"),
            "temp_max": at("temperature_2m_max"),
            "precip_prob": at("precipitation_probability_max"),
            "wind_kph": at("wind_speed_10m_max"),
            "uv": at("uv_index_max"),
            "provider": "open-meteo",
        })
    return rows


def _met_no(lat: float, lng: float, start: date, end: date) -> list[dict]:
    """MET Norway gives hourly points; this folds them into daily extremes.

    No precipitation probability exists in the compact product, so precip_prob
    stays None — see the module docstring on why that is not a zero.
    """
    with httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(MET_NO_URL, params={"lat": round(lat, 4), "lon": round(lng, 4)})
        r.raise_for_status()
        series = (r.json().get("properties") or {}).get("timeseries") or []

    by_day: dict[str, dict] = {}
    for point in series:
        day = (point.get("time") or "")[:10]
        if not day or not (start.isoformat() <= day <= end.isoformat()):
            continue
        details = ((point.get("data") or {}).get("instant") or {}).get("details") or {}
        temp = details.get("air_temperature")
        wind_ms = details.get("wind_speed")
        bucket = by_day.setdefault(day, {"temps": [], "winds": []})
        if temp is not None:
            bucket["temps"].append(temp)
        if wind_ms is not None:
            bucket["winds"].append(wind_ms * 3.6)      # m/s -> km/h

    rows = []
    for day, bucket in sorted(by_day.items()):
        if not bucket["temps"]:
            continue
        rows.append({
            "forecast_date": day,
            "temp_min": min(bucket["temps"]),
            "temp_max": max(bucket["temps"]),
            "precip_prob": None,                       # not "0" — see docstring
            "wind_kph": max(bucket["winds"]) if bucket["winds"] else None,
            "uv": None,
            "provider": "met-no",
        })
    return rows


def forecast(lat: float, lng: float, start: date, end: date) -> list[dict]:
    """Daily rows for a date range, from whichever provider answers.

    The range is clamped to the forecast horizon rather than refused. An
    adventure is usually planned months out, and the honest answer then is "no
    forecast yet" — an empty list — not an error the screen has to explain.
    """
    today = date.today()
    first = max(start, today)
    last = min(end, today + timedelta(days=HORIZON_DAYS))
    if last < first:
        return []

    for name, fn in (("open-meteo", _open_meteo), ("met-no", _met_no)):
        try:
            rows = fn(lat, lng, first, last)
            if rows:
                return rows
            print(f"[weather] {name} returned nothing for {lat},{lng}")
        except Exception as e:                                # noqa: BLE001
            print(f"[weather] {name} failed: {type(e).__name__}: {e}")
    return []


def elevation(lat: float, lng: float) -> int | None:
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as c:
            r = c.get(ELEVATION_URL, params={"latitude": lat, "longitude": lng})
            r.raise_for_status()
            values = r.json().get("elevation") or []
        return int(values[0]) if values else None
    except Exception as e:                                    # noqa: BLE001
        print(f"[weather] elevation failed: {type(e).__name__}: {e}")
        return None
