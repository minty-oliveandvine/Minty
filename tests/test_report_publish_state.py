"""Starting a Xero publish (``xero/services/publish_start.py``), pinned before the start moved into
that service. Driven through the Jinja route (``/report/submitted/publish_to_xero``) until Flask's
HTML frontend was deleted (2026-10-20); now through the Petty Cash API's
``POST /reports/<id>/publish``, which always names the report (the Jinja route's "no id: the latest
submitted report" went with it). How a publish went is tests/test_petty_cash_api_report.py's.

Xero is never called: the token, the settings check, the system-account check and the
background worker are stubbed where the service calls them. Tests marked FIXED pin what the
extraction changed deliberately (they failed before it).
"""
from __future__ import annotations

import importlib
import time
from types import SimpleNamespace

import char_factories as F
import pytest
from test_report_edits_state import _submitted
from test_report_expenses_state import D3, db, s3, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

HOMES = ("blueprints.xero.services.publish_start",)


@pytest.fixture
def xero(monkeypatch):
    """Xero stubbed out; ``xero.started`` collects the worker's arguments."""
    state = SimpleNamespace(started=[], token="tok", complete=True, system_errors=[])

    def patch(name, value):
        for home in HOMES:
            # imported here: since the Jinja routes went (2026-10-20) nothing imports it at start-up
            module = importlib.import_module(home)
            if hasattr(module, name):
                monkeypatch.setattr(module, name, value)

    patch("resolve_xero_token",
          lambda entity_id, user: SimpleNamespace(access_token=state.token, username=user.username) if state.token else None)
    patch("ensure_valid_token", lambda user: False)
    patch("check_entity_xero_settings_complete", lambda entity_id: state.complete)
    patch("sync_entity_xero_status", lambda entity_id, **kw: None)
    patch("validate_expenses_for_system_accounts", lambda *a, **kw: state.system_errors)
    patch("process_xero_integration_background", lambda *args: state.started.append(args))
    state.patch = patch
    return state


def _publish(client, owner, entity, report_id):
    return client.post(f"/api/petty-cash/v1/companies/{entity.id}/reports/{report_id}/publish",
                       headers=F.petty_cash_headers(client.application, owner.id))


def _status(app, report_id):
    from models.db import Report, db as _db

    with app.app_context():
        value = _db.session.get(Report, report_id).publishing_status
        return str(getattr(value, "value", value))


def _wait(started):
    deadline = time.time() + 5
    while not started and time.time() < deadline:
        time.sleep(0.05)
    return started


def test_a_submitted_report_goes_to_the_worker(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner)

    resp = _publish(client, owner, entity, report_id)

    assert resp.status_code == 202, resp.get_json()
    assert resp.get_json()["publishing_status"] == "publishing"
    assert _status(app, report_id) == "publishing"
    args = _wait(xero.started)[0]
    assert (str(args[0]), args[1], str(args[2]), args[4], args[6]) == (str(entity.id), D3, report_id, "tok", "unpublished")


@pytest.mark.parametrize("setup, status, words", [
    ({"token": None}, 400, "I've lost access to your Xero account"),
    ({"complete": False}, 400, "Xero settings incomplete"),
    ({"system_errors": [{"message": "Account 800 is a system account.", "expense": "Fees", "account_code": "800"}]},
     400, "Account 800 is a system account."),
])
def test_a_publish_that_cannot_start_says_why_and_changes_nothing(app, client, db, shop, xero, setup, status, words):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner)
    for k, v in setup.items():
        setattr(xero, k, v)

    resp = _publish(client, owner, entity, report_id)

    assert resp.status_code == status and words in resp.get_json()["error"]
    assert _status(app, report_id) == "unpublished" and not xero.started


def test_a_report_already_publishing_is_not_sent_twice(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, publishing_status="publishing")

    resp = _publish(client, owner, entity, report_id)

    assert resp.status_code == 409 and not xero.started


def test_fixed_a_draft_is_never_published(app, client, db, shop, xero):  # noqa: F811
    """FIXED: with a report id the route took any report of the company - a draft went to Xero."""
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, status="draft")

    resp = _publish(client, owner, entity, report_id)

    assert resp.status_code == 409
    assert resp.get_json()["error"] == "This report is still a draft. Submit the day before publishing it."
    assert _status(app, report_id) == "unpublished" and not xero.started


def test_fixed_a_failed_start_never_leaves_the_report_publishing(app, client, db, shop, xero):  # noqa: F811
    """FIXED: the Jinja route's reset after a failure used the report id from the address, so a
    publish of the latest report (no id) that failed after the lock stayed "publishing" for good -
    and nothing could then publish, edit or delete it."""
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner)

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no threads today")

    xero.patch("threading", SimpleNamespace(Thread=Broken))

    resp = _publish(client, owner, entity, report_id)

    assert resp.status_code == 500
    assert _status(app, report_id) == "failed"
