"""Adventure rules that hold without a database.

The status machine and the activity gate are the two places an adventure can go
wrong in a way no amount of UI care would catch, so they are pinned here rather
than left to the route that happens to enforce them.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.activities.registry import BUILT
from api.adventures.router import STATUSES, TRANSITIONS, AdventureCreate


# ── the status machine ──────────────────────────────────────────────────────

def test_every_status_has_a_transition_entry():
    """A status with no entry raises a KeyError inside the PATCH route — a 500
    where a 409 belongs. Adding a status without adding its transitions is
    exactly the edit that would do it."""
    assert set(TRANSITIONS) == set(STATUSES)


def test_transitions_only_name_real_statuses():
    for have, allowed in TRANSITIONS.items():
        for want in allowed:
            assert want in STATUSES, f"{have} -> {want}"


def test_nothing_returns_to_draft():
    """Draft means "not committed to yet". Once an adventure is planned, the
    Smart Pack, the gear assigned to it and the usage logged against it all
    hang off that commitment, and reopening it as a draft would strand them."""
    for have, allowed in TRANSITIONS.items():
        assert "draft" not in allowed, f"{have} can return to draft"


def test_a_completed_adventure_cannot_become_active_again():
    """An adventure that has happened cannot un-happen. A readiness score
    recomputed for a finished race answers a question nobody asked."""
    assert "active" not in TRANSITIONS["completed"]
    assert "planned" not in TRANSITIONS["completed"]


def test_archiving_is_available_from_everywhere_and_reversible():
    """Archive is the escape hatch — it must never be a one-way door, or it
    becomes a delete that pretends otherwise."""
    for have, allowed in TRANSITIONS.items():
        if have != "archived":
            assert "archived" in allowed, f"{have} cannot be archived"
    assert TRANSITIONS["archived"], "archived is a dead end"


def test_no_status_transitions_to_itself():
    """Self-transitions are filtered before the check in the route (want !=
    have), so listing one here would be dead data that implies a rule."""
    for have, allowed in TRANSITIONS.items():
        assert have not in allowed


# ── the activity gate ───────────────────────────────────────────────────────

def _body(**over):
    base = dict(activity_key="trail_running", title="Oman 100M",
                start_date="2027-02-05")
    base.update(over)
    return base


def test_a_built_activity_is_accepted():
    assert AdventureCreate(**_body()).activity_key == "trail_running"


@pytest.mark.parametrize("activity", ["hiking", "fishing", "fly_fishing"])
def test_schema_only_activities_are_refused(activity):
    """These exist so the attribute model is exercised by more than one
    consumer. They have no screens and no rule set, so an adventure created
    against one would be a row that looks like a feature and is a dead end."""
    with pytest.raises(ValidationError) as e:
        AdventureCreate(**_body(activity_key=activity))
    assert "not built yet" in str(e.value)


def test_the_refusal_names_what_is_available():
    with pytest.raises(ValidationError) as e:
        AdventureCreate(**_body(activity_key="bikepacking"))
    assert "trail_running" in str(e.value)


def test_built_is_the_single_source_for_the_gate():
    """If BUILT grows, the gate opens with it and no second list needs editing."""
    for activity in BUILT:
        assert AdventureCreate(**_body(activity_key=activity))


# ── shape ───────────────────────────────────────────────────────────────────

def test_coordinates_are_bounded():
    with pytest.raises(ValidationError):
        AdventureCreate(**_body(lat=91))
    with pytest.raises(ValidationError):
        AdventureCreate(**_body(lng=-181))


def test_end_date_is_optional():
    """A one-day race is the common case. Requiring end_date would make the
    create form ask for the same date twice."""
    assert AdventureCreate(**_body()).end_date is None


def test_title_is_required_and_bounded():
    with pytest.raises(ValidationError):
        AdventureCreate(**_body(title=""))
    with pytest.raises(ValidationError):
        AdventureCreate(**_body(title="x" * 200))
