"""End-to-end smoke test: the Phase 1 loop against a REAL project and a REAL API.

    .venv/bin/uvicorn api.main:app --port 8000 &
    .venv/bin/python -m scripts.smoke_test

WHAT THIS IS FOR. api/tests/ is fast and hermetic — it never touches Supabase,
which is what makes it fast and also what makes it blind to everything that can
only go wrong between two machines: a migration that did not run, an RLS policy
that locks out the service key, a jsonb column that quietly stringifies, an
attribute validator that agrees with itself and disagrees with Postgres.

So this one is the opposite: it signs in for real, writes real rows and reads
them back. It creates two throwaway accounts and DELETES them plus everything
they own at the end, so it is safe to run repeatedly against a development
project. Do not point it at production.

CREDENTIALS COME FROM .env — never from this file. It needs SUPABASE_URL and
SUPABASE_SERVICE_KEY (the admin API creates the confirmed accounts), plus
SUPABASE_PUBLISHABLE_KEY to sign in the way the app does.
"""
import json
import os
import sys

import httpx

from api.core.config import settings

SB = settings.supabase_url
SEC = settings.supabase_service_key
PUB = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
API = os.environ.get("SMOKE_API_URL", "http://localhost:8000")

PASSWORD = "smoke-test-160km"
EMAIL = "smoke-owner@voyageoutdoor.test"
OTHER = "smoke-other@voyageoutdoor.test"

if not (SB and SEC and PUB):
    print("Need SUPABASE_URL, SUPABASE_SERVICE_KEY and SUPABASE_PUBLISHABLE_KEY "
          "in .env or the environment.")
    sys.exit(2)

ok = fail = 0


def check(label, condition, detail=""):
    global ok, fail
    if condition:
        ok += 1
        print(f"  ok    {label}" + (f"  · {detail}" if detail else ""))
    else:
        fail += 1
        print(f"  FAIL  {label}  · {detail}")


with httpx.Client(timeout=30) as c:
    # ── a confirmed user, via the admin API (no email is sent) ──────────────
    admin = {"apikey": SEC, "Authorization": f"Bearer {SEC}",
             "Content-Type": "application/json"}
    r = c.post(f"{SB}/auth/v1/admin/users", headers=admin,
               json={"email": EMAIL, "password": PASSWORD, "email_confirm": True})
    if r.status_code not in (200, 201) and "already" not in r.text.lower():
        print("could not create the test user:", r.status_code, r.text[:300])
        sys.exit(1)

    r = c.post(f"{SB}/auth/v1/token?grant_type=password",
               headers={"apikey": PUB, "Content-Type": "application/json"},
               json={"email": EMAIL, "password": PASSWORD})
    if r.status_code != 200:
        print("sign-in failed:", r.status_code, r.text[:300])
        sys.exit(1)
    session = r.json()
    uid = session["user"]["id"]
    H = {"Authorization": f"Bearer {session['access_token']}",
         "Content-Type": "application/json"}
    print(f"\nsigned in as {EMAIL}\n  user id {uid}\n")

    # ── identity: the profile row must be auto-provisioned on first sight ───
    print("IDENTITY")
    me = c.get(f"{API}/v1/me", headers=H).json()
    check("profile auto-provisioned", me["profile"] and me["profile"]["id"] == uid)
    check("email captured from GoTrue", me["profile"]["email"] == EMAIL, me["profile"]["email"])
    check("preferences row created too", me["preferences"] is not None,
          f"{me['preferences']['distance_unit']} / {me['preferences']['weight_unit']}")

    # ── the activity system ────────────────────────────────────────────────
    print("\nACTIVITY SYSTEM")
    acts = c.get(f"{API}/v1/activities", headers=H).json()
    check("only built activities are offered", [a["key"] for a in acts] == ["trail_running"],
          str([a["key"] for a in acts]))
    allacts = c.get(f"{API}/v1/activities?include_unbuilt=true", headers=H).json()
    check("all four exist behind the flag", len(allacts) == 4, str(len(allacts)))
    schema = c.get(f"{API}/v1/activities/trail_running/schema", headers=H).json()
    check("schema serves from the registry", "shoes" in schema["gear"],
          f"{len(schema['gear'])} categories")
    cats = c.get(f"{API}/v1/gear-categories?activity_key=trail_running", headers=H).json()
    universal = [x["key"] for x in cats if x["activity_key"] is None]
    check("universal categories appear for the activity", "headlamp" in universal,
          f"{len(cats)} total, {len(universal)} universal")

    # ── own ────────────────────────────────────────────────────────────────
    print("\nOWN")
    shoe = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Norda 005", "brand": "Norda", "model": "005",
        "category_key": "shoes", "activity_key": "trail_running",
        "size": "EU 45", "weight_g": 248, "favorite": True,
        "attributes": {"stack_height_mm": 33, "drop_mm": 6, "lug_depth_mm": 4.5,
                       "cushioning": "max", "waterproof": False,
                       "terrain": ["technical", "mountain"], "lifespan_km": 800,
                       "outsole": "Vibram Litebase Megagrip"},
    })
    check("gear created", shoe.status_code == 201, f"HTTP {shoe.status_code}")
    shoe = shoe.json()
    check("attributes round-tripped", shoe["attributes"]["stack_height_mm"] == 33
          and shoe["attributes"]["terrain"] == ["technical", "mountain"],
          json.dumps(shoe["attributes"]))
    check("condition is null, not a guess", shoe["condition_pct"] is None,
          repr(shoe["condition_pct"]))

    vest = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Salomon ADV Skin 12", "category_key": "vest",
        "activity_key": "trail_running", "weight_g": 210,
        "attributes": {"capacity_l": 12, "flask_slots": 2, "pole_carry": True},
    }).json()
    lamp = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Petzl Swift RL", "category_key": "headlamp",
        "activity_key": "trail_running", "weight_g": 100,
        "attributes": {"lumens": 1100, "reactive": True, "rechargeable": True},
    }).json()
    check("universal category accepts its own fields",
          lamp["attributes"].get("lumens") == 1100, json.dumps(lamp["attributes"]))

    # ── the validator, on the real database ────────────────────────────────
    print("\nREFUSALS")
    bad = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Typo shoe", "category_key": "shoes", "activity_key": "trail_running",
        "attributes": {"stack_height_mm": 610}})
    check("out-of-range attribute refused", bad.status_code == 422,
          f"HTTP {bad.status_code} · {bad.json().get('detail')}")
    bad2 = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Bad enum", "category_key": "shoes", "activity_key": "trail_running",
        "attributes": {"cushioning": "plush"}})
    check("enum outside its options refused", bad2.status_code == 422,
          f"{bad2.json().get('detail')}")
    drop = c.post(f"{API}/v1/gear", headers=H, json={
        "name": "Unknown field", "category_key": "shoes",
        "activity_key": "trail_running",
        "attributes": {"stack_height_mm": 30, "quantum_flux": 9}}).json()
    check("unknown key dropped, write still succeeds",
          drop["attributes"] == {"stack_height_mm": 30}, json.dumps(drop["attributes"]))
    c.delete(f"{API}/v1/gear/{drop['id']}", headers=H)

    # ── use ────────────────────────────────────────────────────────────────
    print("\nUSE")
    for date, metres in [("2026-08-02", 32_000), ("2026-08-16", 45_500),
                         ("2026-08-30", 21_100)]:
        c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H,
               json={"occurred_on": date, "distance_m": metres})
    c.post(f"{API}/v1/gear/{shoe['id']}/maintenance", headers=H,
           json={"kind": "inspect", "occurred_on": "2026-09-01",
                 "notes": "Outsole lugs still sharp; midsole creasing on medial side."})

    detail = c.get(f"{API}/v1/gear/{shoe['id']}", headers=H).json()
    check("usage rollup sums", detail["totals"]["distance_m"] == 98_600,
          f"{detail['totals']['distance_m'] / 1000:.1f} km over "
          f"{detail['totals']['sessions']} sessions")
    check("last used is the most recent", detail["totals"]["last_used_on"] == "2026-08-30",
          detail["totals"]["last_used_on"])
    check("maintenance attached", len(detail["maintenance"]) == 1)
    check("condition still not measured", detail["condition_pct"] is None)

    # ── patch semantics ────────────────────────────────────────────────────
    print("\nPATCH")
    patched = c.patch(f"{API}/v1/gear/{shoe['id']}", headers=H,
                      json={"attributes": {"drop_mm": 4}}).json()
    check("patch MERGES attributes rather than replacing",
          patched["attributes"]["drop_mm"] == 4
          and patched["attributes"]["stack_height_mm"] == 33,
          json.dumps(patched["attributes"]))
    cleared = c.patch(f"{API}/v1/gear/{shoe['id']}", headers=H,
                      json={"attributes": {"outsole": None}}).json()
    check("explicit null clears one field only",
          "outsole" not in cleared["attributes"]
          and cleared["attributes"]["stack_height_mm"] == 33,
          json.dumps(cleared["attributes"]))

    retired = c.patch(f"{API}/v1/gear/{lamp['id']}", headers=H,
                      json={"status": "retired"}).json()
    check("retiring stamps retired_at", retired["retired_at"] is not None,
          retired["retired_at"])

    # ── the locker list ────────────────────────────────────────────────────
    print("\nLOCKER")
    active = c.get(f"{API}/v1/gear", headers=H).json()
    check("retired gear is hidden by default",
          {g["name"] for g in active} == {"Norda 005", "Salomon ADV Skin 12"},
          str(sorted(g["name"] for g in active)))
    every = c.get(f"{API}/v1/gear?status=all", headers=H).json()
    check("status=all shows it again", len(every) == 3, str(len(every)))
    shoes = c.get(f"{API}/v1/gear?category_key=shoes", headers=H).json()
    check("category filter", len(shoes) == 1 and shoes[0]["name"] == "Norda 005")
    found = c.get(f"{API}/v1/gear?q=norda", headers=H).json()
    check("search is case-insensitive", len(found) == 1, "q=norda")
    check("favourites sort first", active[0]["favorite"] is True, active[0]["name"])

    # ── isolation ──────────────────────────────────────────────────────────
    print("\nISOLATION")
    r2 = c.post(f"{SB}/auth/v1/admin/users", headers=admin,
                json={"email": OTHER,
                      "password": PASSWORD, "email_confirm": True})
    r2 = c.post(f"{SB}/auth/v1/token?grant_type=password",
                headers={"apikey": PUB, "Content-Type": "application/json"},
                json={"email": OTHER, "password": PASSWORD})
    H2 = {"Authorization": f"Bearer {r2.json()['access_token']}",
          "Content-Type": "application/json"}
    other = c.get(f"{API}/v1/gear/{shoe['id']}", headers=H2)
    check("another account gets 404, not 403", other.status_code == 404,
          f"HTTP {other.status_code} · {other.json().get('detail')}")
    check("their locker is empty", c.get(f"{API}/v1/gear", headers=H2).json() == [])
    steal = c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H2,
                   json={"occurred_on": "2026-09-01", "distance_m": 1000})
    check("cannot log usage against someone else's gear", steal.status_code == 404)


    # ── PHASE 2: adventures ────────────────────────────────────────────────
    print("\nADVENTURES")
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=3)).isoformat()
    far = (date.today() + timedelta(days=300)).isoformat()

    adv = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running",
        "title": "Oman by UTMB — 100M",
        "place_name": "Bidiyah, Oman", "country_code": "OM",
        "lat": 22.45, "lng": 58.80,
        "start_date": soon, "end_date": soon,
        "attributes": {"distance_km": 160, "elevation_gain_m": 9000,
                       "expected_hours": 30, "technicality": "technical",
                       "terrain": ["mountain", "technical"],
                       "night_hours": 11, "aid_stations": 12,
                       "mandatory_kit": ["Headlamp + spare", "Space blanket",
                                         "Waterproof jacket", "Whistle"]},
    })
    check("adventure created", adv.status_code == 201, f"HTTP {adv.status_code}")
    adv = adv.json()
    check("adventure attributes round-tripped",
          adv["attributes"]["distance_km"] == 160
          and len(adv["attributes"]["mandatory_kit"]) == 4,
          f"{adv['attributes']['distance_km']} km, "
          f"{len(adv['attributes']['mandatory_kit'])} mandatory items")
    check("a new adventure starts as a draft", adv["status"] == "draft", adv["status"])

    one_day = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Saturday long run",
        "start_date": soon, "attributes": {"distance_km": 32}}).json()
    check("end_date defaults to the start", one_day["end_date"] == soon,
          one_day["end_date"])

    print("\nADVENTURE REFUSALS")
    unbuilt = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "fishing", "title": "Socotra GT",
        "start_date": soon, "attributes": {"water_type": "offshore"}})
    check("a schema-only activity is refused", unbuilt.status_code == 422,
          f"HTTP {unbuilt.status_code}")
    missing = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "No distance",
        "start_date": soon, "attributes": {"elevation_gain_m": 500}})
    check("the required adventure field is enforced", missing.status_code == 422,
          str(missing.json().get("detail")))
    backwards = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Time travel",
        "start_date": soon, "end_date": date.today().isoformat(),
        "attributes": {"distance_km": 10}})
    check("end before start is refused", backwards.status_code == 422)

    print("\nSTATUS MACHINE")
    planned = c.patch(f"{API}/v1/adventures/{adv['id']}", headers=H,
                      json={"status": "planned"})
    check("draft -> planned", planned.status_code == 200
          and planned.json()["status"] == "planned")
    done = c.patch(f"{API}/v1/adventures/{adv['id']}", headers=H,
                   json={"status": "completed"}).json()
    check("planned -> completed", done["status"] == "completed")
    back = c.patch(f"{API}/v1/adventures/{adv['id']}", headers=H,
                   json={"status": "active"})
    check("completed cannot become active again", back.status_code == 409,
          back.json().get("detail"))
    c.patch(f"{API}/v1/adventures/{adv['id']}", headers=H, json={"status": "planned"})

    print("\nPLACES + WEATHER")
    places = c.get(f"{API}/v1/places", headers=H, params={"q": "Chamonix"})
    check("place search returns candidates with coordinates",
          places.status_code == 200 and places.json()
          and places.json()[0]["lat"] is not None,
          f"{len(places.json())} results, first is {places.json()[0]['name']}"
          if places.json() else "none")

    wx = c.post(f"{API}/v1/adventures/{adv['id']}/weather", headers=H)
    body = wx.json()
    check("forecast fetched for a near-term adventure",
          body["reason"] in ("fetched", "fresh") and body.get("days"),
          f"{body['reason']}, {len(body.get('days') or [])} days from "
          f"{body.get('provider', 'cache')}")
    if body.get("days"):
        d = body["days"][0]
        check("a forecast day carries real numbers",
              d["temp_max"] is not None and d["temp_min"] is not None,
              f"{d['forecast_date']} {d['temp_min']}–{d['temp_max']}°C")

    again = c.post(f"{API}/v1/adventures/{adv['id']}/weather", headers=H).json()
    check("a second call is served from the cache", again["reason"] == "fresh",
          again["reason"])

    distant = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Next year",
        "place_name": "Chamonix", "lat": 45.92, "lng": 6.87,
        "start_date": far, "attributes": {"distance_km": 171}}).json()
    beyond = c.post(f"{API}/v1/adventures/{distant['id']}/weather", headers=H).json()
    check("a date beyond the horizon is a reason, not an error",
          beyond["reason"] == "beyond_horizon", beyond.get("detail"))

    nowhere = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Somewhere",
        "start_date": soon, "attributes": {"distance_km": 20}}).json()
    noloc = c.post(f"{API}/v1/adventures/{nowhere['id']}/weather", headers=H).json()
    check("an adventure with no place says so", noloc["reason"] == "no_location",
          noloc.get("detail"))

    print("\nGEAR ON AN ADVENTURE")
    c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H,
           json={"occurred_on": date.today().isoformat(), "distance_m": 16000,
                 "adventure_id": adv["id"]})
    detail = c.get(f"{API}/v1/adventures/{adv['id']}", headers=H).json()
    check("usage logged against the adventure appears on it",
          len(detail["usage"]) == 1, f"{len(detail['usage'])} entries")
    stolen = c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H,
                    json={"occurred_on": date.today().isoformat(),
                          "adventure_id": distant["id"], "distance_m": 1})
    check("usage can attach to any adventure you own", stolen.status_code == 201)

    print("\nADVENTURE ISOLATION")
    check("another account cannot read it",
          c.get(f"{API}/v1/adventures/{adv['id']}", headers=H2).status_code == 404)
    check("another account cannot patch it",
          c.patch(f"{API}/v1/adventures/{adv['id']}", headers=H2,
                  json={"title": "mine now"}).status_code == 404)
    check("their adventure list is empty",
          c.get(f"{API}/v1/adventures", headers=H2).json() == [])
    check("their usage cannot name your adventure",
          c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H2,
                 json={"occurred_on": date.today().isoformat(),
                       "adventure_id": adv["id"]}).status_code == 404)

    print("\nDELETING AN ADVENTURE KEEPS THE MILEAGE")
    before = c.get(f"{API}/v1/gear/{shoe['id']}", headers=H).json()["totals"]["distance_m"]
    c.delete(f"{API}/v1/adventures/{adv['id']}", headers=H)
    after = c.get(f"{API}/v1/gear/{shoe['id']}", headers=H).json()["totals"]["distance_m"]
    check("the run still happened after its adventure is gone",
          before == after and after > 0,
          f"{after / 1000:.1f} km before and after")

    # ── teardown ───────────────────────────────────────────────────────────
    # Deleting the auth user cascades: profiles.id references auth.users on
    # delete cascade, and every table here hangs off profiles the same way. So
    # two deletes remove the accounts, their gear, their usage and their
    # maintenance — which is also a live proof that the cascade works.
    print("\nTEARDOWN")
    listed = c.get(f"{SB}/auth/v1/admin/users", headers=admin).json().get("users", [])
    removed = 0
    for u in listed:
        if u["email"] in (EMAIL, OTHER):
            c.delete(f"{SB}/auth/v1/admin/users/{u['id']}", headers=admin)
            removed += 1
    check("test accounts removed", removed == 2, f"{removed} deleted")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
