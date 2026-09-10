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
from collections import Counter

import httpx

from api.core.config import settings

SB = settings.supabase_url
SEC = settings.supabase_service_key
PUB = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
API = os.environ.get("SMOKE_API_URL", "http://localhost:8000")

#: The coarse gate's key, sent as x-voyage-key on every request.
#:
#: BLANK IS CORRECT LOCALLY and wrong against a deployment. With no key
#: configured the middleware leaves the gate open, so a local run needs
#: nothing; a deployed service refuses every request without it, and the
#: failure looks like a broken response shape rather than a missing header —
#: this run died on KeyError: 'profile' because /v1/me had answered
#: {"detail": "unauthorized"}.
APP_KEY = os.environ.get("SMOKE_APP_KEY") or settings.app_shared_secret
GATE = {"x-voyage-key": APP_KEY} if APP_KEY else {}

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
    admin = {"apikey": SEC, "Authorization": f"Bearer {SEC}",
             "Content-Type": "application/json"}

    # ── CLEAN UP BEFORE, NOT ONLY AFTER ────────────────────────────────────
    #
    # A run that dies before teardown — a 404 on a route that had not been
    # deployed yet, a dropped connection, Ctrl-C — leaves its accounts behind.
    # The NEXT run then finds "already exists", signs in, and inherits a locker
    # and four adventures from the last attempt. Every count-based assertion
    # drifts, and the failures look exactly like regressions in whatever was
    # being built that day. This happened: seven failures, then one, then none,
    # over three identical runs.
    #
    # Deleting first makes a run idempotent regardless of how the last one
    # ended. The teardown at the bottom stays — it is what keeps a development
    # project clean between sessions — but correctness no longer depends on it
    # having succeeded.
    stale = [u for u in c.get(f"{SB}/auth/v1/admin/users", headers=admin)
             .json().get("users", []) if u["email"] in (EMAIL, OTHER)]
    for u in stale:
        c.delete(f"{SB}/auth/v1/admin/users/{u['id']}", headers=admin)
    if stale:
        print(f"cleared {len(stale)} account(s) left over from a previous run")

    # ── a confirmed user, via the admin API (no email is sent) ──────────────
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
         "Content-Type": "application/json", **GATE}
    print(f"\nsigned in as {EMAIL}\n  user id {uid}\n")

    print(f"api: {API}")
    print(f"gate: {'on — sending x-voyage-key' if GATE else 'off (no key configured)'}\n")

    if GATE:
        # Worth asserting rather than assuming: a deployment whose gate is off
        # is open to anyone who finds the URL, and it looks identical to a
        # working one from the outside.
        bare = c.get(f"{API}/v1/activities",
                     headers={"Authorization": f"Bearer {session['access_token']}"})
        check("the gate refuses a request with no app key",
              bare.status_code == 401 and bare.json().get("detail") == "unauthorized",
              f"HTTP {bare.status_code}")

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
    lampid = lamp["id"]
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
          "Content-Type": "application/json", **GATE}
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
    #: The device's "today" for the notification plan. Today, not a
    #: fixed string: a plan is only ever computed relative to now.
    soon_minus_3 = date.today().isoformat()
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


    # ── PHASE 3: Smart Pack ────────────────────────────────────────────────
    print("\nSMART PACK")
    race = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Kit-check race",
        "place_name": "Bidiyah", "lat": 22.45, "lng": 58.80,
        "start_date": soon,
        "attributes": {"distance_km": 160, "expected_hours": 30,
                       "night_hours": 11, "elevation_gain_m": 9000,
                       "terrain": ["mountain", "technical"],
                       "mandatory_kit": ["Headlamp + spare batteries",
                                         "Survival blanket", "Whistle",
                                         "Mobile phone"]},
    }).json()

    empty = c.get(f"{API}/v1/adventures/{race['id']}/pack", headers=H).json()
    check("a GET does not silently generate", empty["list"] is None,
          "list is null before anything is built")

    built = c.post(f"{API}/v1/adventures/{race['id']}/pack", headers=H)
    check("pack generated", built.status_code == 201, f"HTTP {built.status_code}")
    built = built.json()
    counts = built["list"]["generation_snapshot"]["counts"]
    check("every ruleset version is stamped on the list",
          built["list"]["ruleset_version"] == "pack-v1"
          and built["list"]["generation_snapshot"]["compat_ruleset"],
          built["list"]["ruleset_version"])
    check("classifications were produced", sum(counts.values()) == len(built["items"]),
          str(counts))

    ids = [i["gear_item_id"] for i in built["items"] if i["gear_item_id"]]
    check("no gear item is claimed twice", len(ids) == len(set(ids)),
          f"{len(ids)} used, {len(set(ids))} distinct")

    mandatory = [i for i in built["items"] if i["source"] == "mandatory"]
    check("every mandatory line survived", len(mandatory) == 4, str(len(mandatory)))
    check("every mandatory line is critical", all(i["critical"] for i in mandatory))
    # The headlamp was RETIRED earlier in this run, and a retired lamp must
    # never answer a race requirement — "you already own one" is exactly wrong
    # for something in a bin. So it is missing here, and un-retiring it must
    # bring it back.
    lamp_line = next(i for i in mandatory if i["category_key"] == "headlamp")
    check("a RETIRED headlamp does not satisfy the race requirement",
          lamp_line["classification"] == "missing"
          and lamp_line["gear_item_id"] is None,
          "retired gear is not offered")

    c.patch(f"{API}/v1/gear/{lampid}", headers=H, json={"status": "active"})
    revived = c.post(f"{API}/v1/adventures/{race['id']}/pack", headers=H).json()
    lamp_line = next(i for i in revived["items"]
                     if i["category_key"] == "headlamp" and i["source"] == "mandatory")
    check("un-retiring it satisfies the requirement again",
          lamp_line["classification"] == "required"
          and lamp_line["gear_item_id"] == lampid,
          lamp_line["name"])
    built = revived
    mandatory = [i for i in built["items"] if i["source"] == "mandatory"]

    check("every line records the rule that produced it",
          all(i["rule_key"] and i["reason"] for i in built["items"]))

    text = " ".join([i["reason"] or "" for i in built["items"]]
                    + [w["message"] for w in built["warnings"]]).lower()
    check("nothing anywhere says buy", "buy" not in text and "purchase" not in text)

    print("\nREADINESS")
    r0 = built["readiness"]
    check("an unpacked list is 0% and not ready",
          r0["percent"] == 0 and r0["ready"] is False,
          f"{r0['required_packed']}/{r0['required_total']}")

    required = [i for i in built["items"] if i["classification"] == "required"]
    for i in required:
        c.patch(f"{API}/v1/adventures/{race['id']}/pack/items/{i['id']}",
                headers=H, json={"state": "packed"})
    r1 = c.get(f"{API}/v1/adventures/{race['id']}/readiness", headers=H).json()
    check("packing everything required reaches 100%", r1["percent"] == 100,
          f"{r1['required_packed']}/{r1['required_total']}")
    check("but it is NOT ready — critical items are unverified",
          r1["ready"] is False and r1["critical_unverified"] > 0,
          f"{r1['critical_unverified']} critical unverified, "
          f"{r1['missing_total']} missing")

    print("\nSTATE CARRY-OVER")
    regenerated = c.post(f"{API}/v1/adventures/{race['id']}/pack", headers=H).json()
    still = [i for i in regenerated["items"] if i["state"] == "packed"]
    check("regenerating does not un-pack a packed bag",
          len(still) == len(required),
          f"{len(still)} of {len(required)} still packed")
    check("the snapshot records how many states carried",
          regenerated["list"]["generation_snapshot"]["carried_states"] == len(required))

    print("\nGEAR HEALTH WRITTEN BACK")
    graded = c.get(f"{API}/v1/gear/{shoe['id']}", headers=H).json()
    check("condition is now measured, not guessed",
          graded["condition_pct"] is not None and graded["health_ruleset"] == "health-v1",
          f"{graded['condition_pct']}% · {graded['health_detail'].get('state')}")
    check("the health detail carries the band it judged against",
          "band_low_km" in graded["health_detail"],
          f"{graded['health_detail'].get('band_low_km')}–"
          f"{graded['health_detail'].get('band_high_km')} km")
    lamp = c.get(f"{API}/v1/gear/{lampid}", headers=H).json()
    check("a category with no distance is unknown, not 0%",
          lamp["condition_pct"] is None,
          lamp["health_detail"].get("reason"))

    print("\nPACK ISOLATION")
    check("another account cannot read the pack",
          c.get(f"{API}/v1/adventures/{race['id']}/pack", headers=H2).status_code == 404)
    check("another account cannot move an item",
          c.patch(f"{API}/v1/adventures/{race['id']}/pack/items/{required[0]['id']}",
                  headers=H2, json={"state": "verified"}).status_code == 404)

    # ── Phase 4: the AI layer ──────────────────────────────────────────────
    #
    # THIS SECTION SPENDS REAL MONEY when a key is configured, which is why it
    # is the last thing before teardown and why every call prints its cost. With
    # no key it still runs: the assertions become "the API says 503 and the pack
    # is untouched", which is the more important guarantee anyway — everything
    # below has to be optional, and the only way to know it is is to check.
    print("\nAI LAYER")
    ai_on = c.get(f"{API}/health").json().get("ai") is True
    check("health reports whether AI is configured",
          "ai" in c.get(f"{API}/health").json(), f"ai={ai_on}")

    kit_text = (
        "MANDATORY EQUIPMENT — 50km\n"
        "- Waterproof jacket with taped seams, minimum 10,000mm\n"
        "- Head torch with spare batteries\n"
        "- Survival blanket\n"
        "- Whistle\n"
        "- Mobile phone with the organisation's number saved\n"
        "Recommended: trekking poles.\n")

    # Captured BEFORE the draft. This adventure already carries a kit list typed
    # in by hand further up, so "the adventure has no kit yet" was never the
    # assertion worth making — "the draft changed nothing" is.
    kit_before = (c.get(f"{API}/v1/adventures/{race['id']}", headers=H).json()
                  .get("attributes", {}).get("mandatory_kit"))

    draft_r = c.post(f"{API}/v1/race-kit/drafts", headers=H,
                     json={"text": kit_text, "adventure_id": race["id"]})

    if not ai_on:
        check("with no key, the AI endpoints refuse honestly rather than 500",
              draft_r.status_code == 503, f"HTTP {draft_r.status_code}")
        check("and the pack is untouched by their absence",
              c.get(f"{API}/v1/adventures/{race['id']}/pack",
                    headers=H).json()["readiness"]["required_total"] > 0)
        check("the narrative endpoint reports no narrative rather than failing",
              c.get(f"{API}/v1/adventures/{race['id']}/pack/narrative",
                    headers=H).json()["narrative"] is None)
    else:
        check("a pasted kit list extracts", draft_r.status_code == 201,
              f"HTTP {draft_r.status_code} {draft_r.text[:160]}")
        draft = draft_r.json()
        items = draft["extracted"]["items"]
        check("every mandatory line came across", len(items) == 5,
              f"{len(items)}: " + " | ".join(i["text"][:28] for i in items))
        check("the specification survived transcription",
              any("10,000" in i["text"] or "10000" in i["text"] for i in items),
              "the number is what fails a kit check, not the word 'jacket'")
        check("a recommendation is not promoted to mandatory",
              not any("pole" in i["text"].lower() for i in items)
              and any("pole" in r.lower() for r in draft["extracted"]["recommended"]))
        kit_after = (c.get(f"{API}/v1/adventures/{race['id']}", headers=H).json()
                     .get("attributes", {}).get("mandatory_kit"))
        check("extracting changes nothing on the adventure",
              kit_after == kit_before,
              f"still {len(kit_before or [])} line(s) — a draft is a draft "
              f"until a human accepts it")

        accepted = c.post(f"{API}/v1/race-kit/drafts/{draft['id']}/accept",
                          headers=H,
                          json={"adventure_id": race["id"],
                                "items": [i["text"] for i in items[:4]],
                                "mode": "replace"})
        check("accepting writes the kit and rebuilds the pack",
              accepted.status_code == 200, f"HTTP {accepted.status_code}")
        after = accepted.json()
        check("only the four ticked lines were taken",
              len(after["adventure"]["attributes"]["mandatory_kit"]) == 4)
        mandatory = [i for i in after["pack"]["items"] if i["source"] == "mandatory"]
        check("the pack now carries the race's kit as critical lines",
              len(mandatory) == 4 and all(i["critical"] for i in mandatory),
              f"{len(mandatory)} lines")

        prov = c.get(f"{API}/v1/adventures/{race['id']}/race-kit", headers=H).json()
        check("provenance is readable from the adventure",
              prov and prov["status"] == "accepted" and prov["accepted_at"],
              f"{prov['source_kind']} · {prov.get('race_name')}")

        check("an address that resolves off the public internet is refused",
              c.post(f"{API}/v1/race-kit/drafts", headers=H,
                     json={"url": "http://169.254.169.254/latest/meta-data/",
                           "adventure_id": race["id"]}).status_code == 422,
              "instance metadata is one typo away from a race URL")

        narr = c.post(f"{API}/v1/adventures/{race['id']}/pack/narrative", headers=H)
        check("the narrative writes", narr.status_code == 201,
              f"HTTP {narr.status_code} {narr.text[:160]}")
        if narr.status_code == 201:
            body = narr.json()
            text = body["narrative"]
            check("it is prose, not a re-listing", len(text.split()) > 25,
                  f"{len(text.split())} words · ${body.get('cost_usd')}")
            # §14. The engine deliberately never says "buy"; a narrative that
            # reintroduced it would undo the rule at the last step.
            check("it does not turn a gap into a purchase",
                  not any(w in text.lower() for w in
                          ("buy ", "purchase", "shop", "order one")),
                  "§14")
            check("a second read is stored rather than regenerated",
                  c.get(f"{API}/v1/adventures/{race['id']}/pack/narrative",
                        headers=H).json()["narrative"] == text)
            packed_one = c.patch(
                f"{API}/v1/adventures/{race['id']}/pack/items/{mandatory[0]['id']}",
                headers=H, json={"state": "packed"})
            check("packing an item marks the paragraph out of date",
                  packed_one.status_code == 200
                  and c.get(f"{API}/v1/adventures/{race['id']}/pack/narrative",
                            headers=H).json()["stale"] is True,
                  "the numbers in it moved")

        answer = c.post(f"{API}/v1/ask", headers=H,
                        json={"question": "What is on my mandatory kit list?",
                              "adventure_id": race["id"]})
        check("ask answers", answer.status_code == 200,
              f"HTTP {answer.status_code} {answer.text[:160]}")
        if answer.status_code == 200:
            a = answer.json()
            check("and says what it read", a["grounded_in"]["pack"] is True,
                  f"{a['grounded_in']['gear_items']} items · ${a['cost_usd']}")

        check("another account cannot read this import",
              c.get(f"{API}/v1/race-kit/drafts/{draft['id']}",
                    headers=H2).status_code == 404)
        check("another account cannot write a narrative for this pack",
              c.post(f"{API}/v1/adventures/{race['id']}/pack/narrative",
                     headers=H2).status_code == 404)

    # ── Phase 5: Discover and reviews ──────────────────────────────────────
    #
    # No model is called anywhere in this section and no external request is
    # made — that is the §0.4 constraint the whole phase is built on, and it is
    # worth asserting rather than assuming.
    print("\nDISCOVER")
    disc = c.get(f"{API}/v1/discover", headers=H)
    check("discover reads", disc.status_code == 200, f"HTTP {disc.status_code}")
    found = disc.json()
    findings = found["findings"]
    kinds = {}
    for f in findings:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    check("it is stamped with its ruleset", found["ruleset"] == "discover-v1",
          f"{len(findings)} finding(s): {kinds}")

    gaps = [f for f in findings if f["kind"] == "gap"]
    check("the pack's missing lines surfaced as gaps", len(gaps) > 0,
          f"{len(gaps)}")
    check("a gap names the adventures it came from",
          all(f["adventures"] for f in gaps),
          gaps[0]["adventures"][0] if gaps else "")
    check("a race-mandated gap is marked as such",
          any(f["mandatory"] and f["critical"] for f in gaps),
          "§24 outranks every other rule and the screen has to say so")

    # §8 and §14, the line between a tool and a storefront.
    optional_gaps = [f for f in gaps if not f["required"]]
    check("a merely suggested gap is offered no products",
          all(not f["catalog"] for f in optional_gaps),
          f"{len(optional_gaps)} optional gap(s), none with a catalog")
    check("and says plainly that it is optional",
          all("finish without" in f["detail"] for f in optional_gaps)
          if optional_gaps else True)

    blob = " ".join(f["title"] + " " + f["detail"] for f in findings).lower()
    check("nothing in discover says buy",
          not any(w in blob for w in ("buy", "purchase", "shop", "price")),
          "§14 — the trust anchor")

    # SETTLED NEEDS SOMETHING TO SETTLE. The race above runs 11 hours into the
    # dark, so every rule fires and nothing gets ruled out — which is correct,
    # and means the trust anchor goes untested unless the fixture gives it
    # something. A daylight run does: `headlamp_no_darkness` classifies the
    # headlamp NOT_NEEDED, and that is the finding §14 exists to produce.
    day_run = c.post(f"{API}/v1/adventures", headers=H, json={
        "activity_key": "trail_running", "title": "Daylight loop",
        "place_name": "Bidiyah", "lat": 22.45, "lng": 58.80,
        "start_date": soon,
        "attributes": {"distance_km": 12, "expected_hours": 1.5,
                       "night_hours": 0},
    }).json()
    c.post(f"{API}/v1/adventures/{day_run['id']}/pack", headers=H)

    after = c.get(f"{API}/v1/discover", headers=H).json()["findings"]
    settled = [f for f in after if f["kind"] == "settled"]
    check("settled reports what you do NOT need",
          any(f["category_key"] == "headlamp" for f in settled),
          f"{len(settled)} settled · "
          + (settled[0]["detail"] if settled else "none"))
    check("and it names the adventure that ruled it out",
          all(f["adventures"] for f in settled),
          "'a rule ruled it out' is only checkable if it says which rule, where")

    blob2 = " ".join(f["detail"] for f in settled).lower()
    check("saying you do not need something still never says buy",
          not any(w in blob2 for w in ("buy", "purchase", "shop")))

    check("another account sees their own empty record, not yours",
          len(c.get(f"{API}/v1/discover", headers=H2).json()["findings"]) == 0)

    print("\nREVIEWS")
    none_yet = c.get(f"{API}/v1/gear/{shoe['id']}/review", headers=H)
    check("an unreviewed item answers null rather than 404",
          none_yet.status_code == 200 and none_yet.json() is None)

    wrote = c.put(f"{API}/v1/gear/{shoe['id']}/review", headers=H,
                  json={"rating": 4, "body": "Grippy on rock, drains slowly."})
    check("a review saves", wrote.status_code == 200,
          f"HTTP {wrote.status_code} {wrote.text[:120]}")
    rev = wrote.json()
    ctx = rev["context"]
    check("and snapshots what it was based on",
          ctx["sessions"] > 0 and ctx["distance_m"] > 0,
          f"{ctx['sessions']} sessions · {ctx['distance_m']/1000:.1f} km")
    check("including the health band in the engine's words",
          "health_message" in ctx and ctx["health_ruleset"] == "health-v1",
          ctx.get("health_message"))

    # THE SNAPSHOT MUST NOT MOVE. A review written at 114 km that silently
    # starts claiming 214 is a review rewriting itself.
    c.post(f"{API}/v1/gear/{shoe['id']}/usage", headers=H,
           json={"occurred_on": "2026-03-02", "distance_m": 100000})
    still = c.get(f"{API}/v1/gear/{shoe['id']}/review", headers=H).json()
    check("logging another run does not rewrite the review's context",
          still["context"]["distance_m"] == ctx["distance_m"],
          f"still {ctx['distance_m']/1000:.1f} km after +100 km")

    again = c.put(f"{API}/v1/gear/{shoe['id']}/review", headers=H,
                  json={"rating": 5, "body": "Better once broken in."})
    check("writing again edits rather than duplicating",
          again.status_code == 200
          and len(c.get(f"{API}/v1/reviews", headers=H).json()) == 1,
          "one review per item per person")
    check("and the new context reflects the new mileage",
          again.json()["context"]["distance_m"] > ctx["distance_m"])

    check("ratings outside 1-5 are refused",
          c.put(f"{API}/v1/gear/{shoe['id']}/review", headers=H,
                json={"rating": 9}).status_code == 422)
    check("another account cannot read this review",
          c.get(f"{API}/v1/gear/{shoe['id']}/review",
                headers=H2).status_code == 404)
    check("another account cannot write one on your gear",
          c.put(f"{API}/v1/gear/{shoe['id']}/review", headers=H2,
                json={"rating": 1}).status_code == 404)
    check("a malformed product id is refused before the database",
          c.get(f"{API}/v1/products/not-a-uuid/reviews",
                headers=H).status_code == 422)

    # ── Phase 6: the notification plan ─────────────────────────────────────
    print("\nNOTIFICATIONS")
    # `today` is the DEVICE's local date — the server does not know which day it
    # is where the runner is standing, and "the evening before" is a local idea.
    plan_r = c.get(f"{API}/v1/notifications/plan", headers=H,
                   params={"today": soon_minus_3})
    check("the plan reads", plan_r.status_code == 200, f"HTTP {plan_r.status_code}")
    plan = plan_r.json()
    check("stamped with its ruleset", plan["ruleset"] == "notify-v1",
          f"{len(plan['notifications'])} notification(s), cap {plan['daily_cap']}")
    check("and says what it deliberately cannot send",
          "scheduler" in plan["note"] and "catalog" in plan["note"],
          "§21 lists five kinds; two need things this build does not have")

    check("nothing is scheduled in the past",
          all(n["on"] >= soon_minus_3 for n in plan["notifications"]),
          "a notification dated yesterday never fires, which looks identical "
          "to the feature being broken")
    check("the daily cap is respected",
          max(list(Counter(n["on"] for n in plan["notifications"]).values()) or [0])
          <= plan["daily_cap"])
    blob = " ".join(n["title"] + " " + n["body"]
                    for n in plan["notifications"]).lower()
    check("a notification never tells you to go shopping",
          not any(w in blob for w in ("buy", "purchase", "shop")), "§14")

    check("a malformed date is refused",
          c.get(f"{API}/v1/notifications/plan", headers=H,
                params={"today": "yesterday"}).status_code == 422)
    check("another account gets their own plan",
          c.get(f"{API}/v1/notifications/plan", headers=H2).json()["notifications"] == [])

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
