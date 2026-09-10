"""The notification plan, and mostly the things it refuses to say (§21).

`today` is a parameter, so "does it stop nagging once the bag is packed" is an
assertion rather than something you find out tomorrow.
"""
from datetime import date

from api.engines import notify

TODAY = date(2026, 12, 1)


def adventure(id="a1", title="Oman by UTMB", start="2026-12-08"):
    return {"id": id, "title": title, "start_date": start}


def pack(*, ready=False, missing=0, remaining=0, critical=0, has_list=True):
    return {
        "list": {"id": "l1"} if has_list else None,
        "readiness": {"ready": ready, "missing_total": missing,
                      "remaining": remaining, "critical_unverified": critical},
    }


def test_a_finished_pack_is_never_mentioned_again():
    """The single most important suppression here. An app that reminds you
    about a bag you already packed is an app you stop believing."""
    out = notify.plan([adventure()], {"a1": pack(ready=True)}, [], TODAY)
    assert out == []


def test_reminders_land_on_the_lead_days():
    out = notify.plan([adventure()], {"a1": pack(remaining=4)}, [], TODAY)
    days = sorted(n.on for n in out)
    assert days == ["2026-12-01", "2026-12-06", "2026-12-07"]
    assert all(n.hour == 18 for n in out)


def test_nothing_is_ever_scheduled_in_the_past():
    """A notification dated yesterday does not fire — it just quietly is not
    there, which looks identical to the feature being broken."""
    out = notify.plan([adventure(start="2026-12-02")],
                      {"a1": pack(remaining=2)}, [], TODAY)
    assert all(n.on >= TODAY.isoformat() for n in out)


def test_a_critical_item_gets_its_own_alert_the_day_before():
    out = notify.plan([adventure()], {"a1": pack(critical=3, remaining=1)}, [], TODAY)
    crit = [n for n in out if n.kind == notify.CRITICAL_UNVERIFIED]
    assert len(crit) == 1
    assert crit[0].on == "2026-12-07"
    assert "3 critical items are" in crit[0].body
    assert "kit table" in crit[0].body


def test_the_packing_reminder_does_not_repeat_the_critical_alert():
    """Two notifications on one evening saying nearly the same thing is exactly
    the spam §21 forbids."""
    out = notify.plan([adventure()], {"a1": pack(critical=1, remaining=2)}, [], TODAY)
    on_the_eve = [n for n in out if n.on == "2026-12-07"]
    assert len(on_the_eve) == 1
    assert on_the_eve[0].kind == notify.CRITICAL_UNVERIFIED


def test_an_unbuilt_pack_is_nudged_late_not_early():
    """A reminder to build a pack a week out is a to-do item. The day before it
    is the actual problem."""
    out = notify.plan([adventure()], {}, [], TODAY)
    assert sorted(n.on for n in out) == ["2026-12-06", "2026-12-07"]
    assert "No pack built yet" in out[0].body


def test_a_gap_is_stated_as_a_gap_and_never_as_an_errand():
    """§14 holds here too — a notification is the easiest place in the app to
    slip into telling somebody to go shopping."""
    out = notify.plan([adventure()], {"a1": pack(missing=2, remaining=5)}, [], TODAY)
    blob = " ".join(n.title + " " + n.body for n in out).lower()
    assert "not in your locker" in blob
    for word in ("buy", "purchase", "shop", "order"):
        assert word not in blob


def test_three_races_in_one_week_do_not_produce_nine_notifications():
    advs = [adventure("a1", "Race one", "2026-12-08"),
            adventure("a2", "Race two", "2026-12-08"),
            adventure("a3", "Race three", "2026-12-08")]
    packs = {a["id"]: pack(remaining=3) for a in advs}
    out = notify.plan(advs, packs, [], TODAY)
    per_day: dict[str, int] = {}
    for n in out:
        per_day[n.on] = per_day.get(n.on, 0) + 1
    assert max(per_day.values()) <= notify.DEFAULT_DAILY_CAP


def test_the_critical_alert_survives_the_cap():
    """Dropping the kit-check warning to make room for '3 items left to pack'
    would inverts the whole point of the section."""
    advs = [adventure("a1", "Race one", "2026-12-08"),
            adventure("a2", "Race two", "2026-12-08"),
            adventure("a3", "Race three", "2026-12-08")]
    packs = {"a1": pack(remaining=3), "a2": pack(remaining=3),
             "a3": pack(critical=2)}
    out = notify.plan(advs, packs, [], TODAY, daily_cap=1)
    eve = [n for n in out if n.on == "2026-12-07"]
    assert len(eve) == 1
    assert eve[0].kind == notify.CRITICAL_UNVERIFIED


def test_the_plan_is_stable_across_runs():
    """The device cancels everything and reschedules on every app open. If the
    keys or dates moved between runs, a reminder would drift a day each time
    somebody opened the app."""
    args = ([adventure()], {"a1": pack(remaining=2, critical=1)}, [], TODAY)
    first = notify.plan(*args)
    second = notify.plan(*args)
    assert [(n.key, n.on, n.hour, n.body) for n in first] \
        == [(n.key, n.on, n.hour, n.body) for n in second]


def test_maintenance_is_reminded_a_week_ahead():
    rows = [{"id": "m1", "gear_item_id": "g1", "gear_name": "Norda 005",
             "kind": "clean", "next_due_on": "2026-12-20"}]
    out = notify.plan([], {}, rows, TODAY)
    assert len(out) == 1
    assert out[0].on == "2026-12-13"
    assert out[0].kind == notify.MAINTENANCE_DUE


def test_maintenance_already_inside_the_window_fires_today_not_yesterday():
    rows = [{"id": "m1", "gear_item_id": "g1", "gear_name": "Vest",
             "kind": "wash", "next_due_on": "2026-12-03"}]
    out = notify.plan([], {}, rows, TODAY)
    assert out[0].on == TODAY.isoformat()


def test_maintenance_already_overdue_is_dropped_rather_than_backdated():
    rows = [{"id": "m1", "gear_item_id": "g1", "gear_name": "Vest",
             "kind": "wash", "next_due_on": "2026-11-01"}]
    assert notify.plan([], {}, rows, TODAY) == []


def test_a_past_adventure_is_not_reminded_about():
    out = notify.plan([adventure(start="2026-11-01")],
                      {"a1": pack(remaining=9)}, [], TODAY)
    assert out == []


def test_a_malformed_date_is_skipped_not_crashed():
    out = notify.plan([adventure(start="not-a-date"), adventure("a2", start=None)],
                      {}, [{"id": "m", "next_due_on": ""}], TODAY)
    assert out == []


def test_an_empty_record_says_nothing():
    assert notify.plan([], {}, [], TODAY) == []
