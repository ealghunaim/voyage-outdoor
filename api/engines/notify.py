"""What to notify, and — mostly — what not to (§21).

DETERMINISTIC AND PURE, like every other engine here. Adventures, their packs
and the maintenance log go in; a list of notifications comes out. No model, no
clock, no I/O — `today` is a parameter, which is what makes "does it stop
reminding once the bag is packed" a test rather than a thing you wait a day to
find out.

§21 asks for packing reminders, critical-gear-unverified alerts, maintenance
due, weather changes and new releases, and then says the thing that actually
governs the design: NO NOTIFICATION SPAM. So most of this file is suppression.
A reminder about a pack that is already finished, a second reminder that says
what the first one said, and four notifications on the morning of a race are
each the kind of thing that gets an app muted — and a muted app cannot tell you
about the headlamp.

TWO OF THE FIVE ARE DELIBERATELY NOT HERE.

  weather changes  needs something watching the forecast between app opens.
                   There is no scheduler (Phase 0 audit risk #3 — VoyageOS runs
                   its jobs inside the web process and cannot scale past one
                   instance). When a Render cron lands, this engine is where the
                   rule goes; until then a "weather changed" alert would fire
                   only when you opened the app, which is the one moment you do
                   not need to be told.
  new releases     needs a product catalog that §0.4 does not provide in V1.

WHY A DATE AND AN HOUR RATHER THAN A TIMESTAMP. "The evening before" means six
o'clock where the runner is standing, and the server does not reliably know
where that is. Emitting a local date and an hour lets the device resolve it
against its own clock — which is also the only way a reminder survives someone
flying to the race.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

NOTIFY_RULESET = "notify-v1"

PACK_REMINDER = "pack_reminder"
CRITICAL_UNVERIFIED = "critical_unverified"
MAINTENANCE_DUE = "maintenance_due"

#: Days before the start on which a packing reminder may fire. Three, not seven:
#: a reminder a fortnight out is noise, and one on the morning of the race is
#: too late to do anything about a missing jacket.
LEAD_DAYS = (7, 2, 1)

#: The critical-item alert fires once, the day before. It is the one §24 exists
#: for — an unverified mandatory item is what ends a race at a kit table — so it
#: gets its own slot rather than sharing the packing reminder's.
CRITICAL_LEAD_DAY = 1

#: Maintenance is reminded once, this many days before it is due.
MAINTENANCE_LEAD_DAYS = 7

#: Evening. Late enough that someone is home with their gear, early enough that
#: they can still do something about it.
HOUR = 18

#: Hard ceiling per day, before the user's own preference is applied. Three
#: adventures in one week must not produce nine notifications on one evening.
DEFAULT_DAILY_CAP = 2


@dataclass(frozen=True)
class Notification:
    #: Stable across regenerations. The device cancels everything and
    #: reschedules on each app open, so the plan must be a pure function of the
    #: data — two runs over an unchanged record produce identical keys, and a
    #: reminder therefore cannot drift a day each time the app is opened.
    key: str
    kind: str
    on: str                    # local date, YYYY-MM-DD
    hour: int                  # local hour, 0-23
    title: str
    body: str
    subject_type: str          # adventure · gear_item
    subject_id: str


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def plan(adventures: list[dict], packs: dict[str, dict],
         maintenance: list[dict], today: date, *,
         daily_cap: int = DEFAULT_DAILY_CAP) -> list[Notification]:
    """Everything worth saying between now and the last adventure."""
    out: list[Notification] = []

    for adventure in adventures:
        start = _as_date(adventure.get("start_date"))
        if start is None or start < today:
            continue
        pack = packs.get(adventure["id"]) or {}
        readiness = pack.get("readiness") or {}
        title = adventure.get("title") or "your adventure"

        # NOTHING TO SAY ABOUT A FINISHED PACK. This is the single most
        # important suppression in the file: an app that reminds you about a bag
        # you already packed is an app you stop believing.
        if readiness.get("ready"):
            continue

        # No pack at all is still worth one nudge — but only the near one. A
        # reminder to build a pack for a race seven days out is a to-do item; on
        # the day before it is the actual problem.
        has_pack = bool(pack.get("list"))
        leads = LEAD_DAYS if has_pack else (2, 1)

        critical_day = None
        if readiness.get("critical_unverified"):
            when = start - timedelta(days=CRITICAL_LEAD_DAY)
            if when >= today:
                critical_day = when
                count = readiness["critical_unverified"]
                out.append(Notification(
                    key=f"crit:{adventure['id']}",
                    kind=CRITICAL_UNVERIFIED,
                    on=when.isoformat(), hour=HOUR,
                    title=f"{title} — tomorrow",
                    body=(f"{_plural(count, 'critical item is', 'critical items are')} "
                          f"still unverified. That is the check that stops people "
                          f"at the kit table."),
                    subject_type="adventure", subject_id=adventure["id"]))

        for lead in leads:
            when = start - timedelta(days=lead)
            if when < today:
                continue
            # ONE MESSAGE PER EVENING PER ADVENTURE. The critical alert already
            # says everything the packing reminder would have said that day, and
            # louder.
            if when == critical_day:
                continue
            out.append(Notification(
                key=f"pack:{adventure['id']}:{lead}",
                kind=PACK_REMINDER,
                on=when.isoformat(), hour=HOUR,
                title=f"{title} in {_plural(lead, 'day', 'days')}",
                body=_pack_body(readiness, has_pack),
                subject_type="adventure", subject_id=adventure["id"]))

    for row in maintenance:
        due = _as_date(row.get("next_due_on"))
        if due is None:
            continue
        when = due - timedelta(days=MAINTENANCE_LEAD_DAYS)
        # Already overdue when the plan is made: say so today rather than
        # scheduling something in the past, which never fires.
        if when < today:
            when = today if due >= today else None
        if when is None:
            continue
        name = row.get("gear_name") or "A piece of gear"
        out.append(Notification(
            key=f"maint:{row['id']}",
            kind=MAINTENANCE_DUE,
            on=when.isoformat(), hour=HOUR,
            title=f"{name} — {row.get('kind') or 'service'} due",
            body=f"Due {due.isoformat()}.",
            subject_type="gear_item", subject_id=row.get("gear_item_id") or ""))

    return _cap(out, max(1, daily_cap))


def _pack_body(readiness: dict, has_pack: bool) -> str:
    if not has_pack:
        return "No pack built yet. Smart Pack reads your locker and the forecast."
    missing = readiness.get("missing_total") or 0
    remaining = readiness.get("remaining") or 0
    if missing:
        # Stated as a gap, never as an errand. §14 — the same rule the pack
        # engine and Discover already hold.
        return (f"{_plural(missing, 'item', 'items')} on the list "
                f"{'is' if missing == 1 else 'are'} not in your locker, and "
                f"{_plural(remaining, 'is', 'are')} still to pack.")
    if remaining:
        return f"{_plural(remaining, 'item', 'items')} left to pack."
    return "Worth a last look before you go."


def _cap(items: list[Notification], daily_cap: int) -> list[Notification]:
    """At most `daily_cap` on any one evening, and the important ones win.

    Sorted so that a critical alert always survives the cut: dropping the
    kit-check warning to make room for "3 items left to pack" would invert the
    entire point of §21.
    """
    rank = {CRITICAL_UNVERIFIED: 0, PACK_REMINDER: 1, MAINTENANCE_DUE: 2}
    ordered = sorted(items, key=lambda n: (n.on, rank.get(n.kind, 9), n.key))
    kept: list[Notification] = []
    per_day: dict[str, int] = {}
    for item in ordered:
        if per_day.get(item.on, 0) >= daily_cap:
            continue
        per_day[item.on] = per_day.get(item.on, 0) + 1
        kept.append(item)
    return kept


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
