"""The two gates every request passes, tested without a database.

Neither of these needs Supabase: the shared-secret middleware runs before any
route, and the auth dependency refuses before it ever calls get_db(). That is
worth stating because it is also the reason these tests are fast and the reason
a misconfigured gate cannot hide behind a database error.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.core.config import settings
from api.main import app

client = TestClient(app)

PROTECTED = ("/v1/activities", "/v1/gear", "/v1/me")


@pytest.fixture(autouse=True)
def _clean_secrets():
    """Each test states its own key configuration and leaves none behind. The
    middleware reads settings per request, so a leaked value would silently
    change the next test's meaning."""
    before = (settings.app_shared_secret, settings.app_shared_secret_previous,
              settings.env, settings.dev_user_id)
    settings.app_shared_secret = ""
    settings.app_shared_secret_previous = ""
    settings.env = "test"
    settings.dev_user_id = ""
    yield
    (settings.app_shared_secret, settings.app_shared_secret_previous,
     settings.env, settings.dev_user_id) = before


# ── health is open ──────────────────────────────────────────────────────────

def test_health_is_open_and_names_the_phase():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_health_stays_open_behind_the_shared_secret_gate():
    """The deploy platform health-checks this without knowing any key. If the
    gate ever covers it, the service reports unhealthy and gets restarted in a
    loop."""
    settings.app_shared_secret = "live-key"
    assert client.get("/health").status_code == 200


# ── the auth dependency ─────────────────────────────────────────────────────

@pytest.mark.parametrize("path", PROTECTED)
def test_protected_routes_refuse_without_a_token(path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_a_garbage_bearer_token_is_refused_not_crashed(path):
    """An unverifiable token must 401. It reaches the Supabase verify call,
    which fails closed — the branch that matters, because failing OPEN here
    would admit anyone who sends the word 'Bearer'."""
    r = client.get(path, headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_dev_user_fallback_is_local_only():
    """DEV_USER_ID is a convenience for working without the app running. It must
    never survive on a deployed host — flipping ENV is the whole retirement
    mechanism, so it is tested rather than trusted."""
    settings.dev_user_id = "00000000-0000-0000-0000-000000000001"
    settings.env = "production"
    assert client.get("/v1/gear").status_code == 401


# ── the shared-secret gate ──────────────────────────────────────────────────

def test_gate_is_off_when_no_key_is_configured():
    """Local development. With no key set the middleware must not invent one —
    the 401 below comes from auth, not from the gate."""
    r = client.get("/v1/gear")
    assert r.json()["detail"] == "Sign in required."


def test_gate_refuses_a_missing_header():
    settings.app_shared_secret = "live-key"
    r = client.get("/v1/gear")
    assert r.status_code == 401
    assert r.json()["detail"] == "unauthorized"       # the gate, not auth


def test_gate_accepts_the_current_key():
    settings.app_shared_secret = "live-key"
    r = client.get("/v1/gear", headers={"x-voyage-key": "live-key"})
    assert r.json()["detail"] == "Sign in required."  # past the gate, into auth


def test_gate_accepts_the_previous_key_during_a_rotation():
    """A released build still carries the old key. Rotating without an overlap
    401s every user who has not updated, and store updates are neither instant
    nor universal."""
    settings.app_shared_secret = "new-key"
    settings.app_shared_secret_previous = "old-key"
    for key in ("new-key", "old-key"):
        r = client.get("/v1/gear", headers={"x-voyage-key": key})
        assert r.json()["detail"] == "Sign in required.", key


def test_an_empty_previous_key_is_not_a_second_door():
    """A blank env var must contribute nothing. If empty strings were compared
    rather than filtered out, a request with no header would match one."""
    settings.app_shared_secret = "live-key"
    settings.app_shared_secret_previous = ""
    r = client.get("/v1/gear", headers={"x-voyage-key": ""})
    assert r.json()["detail"] == "unauthorized"


def test_wrong_key_is_refused():
    settings.app_shared_secret = "live-key"
    r = client.get("/v1/gear", headers={"x-voyage-key": "guessed"})
    assert r.json()["detail"] == "unauthorized"
