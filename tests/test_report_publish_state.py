"""Starting a Xero publish (``report/routes/submitted.py::report_submitted_publish_to_xero``) and
reading how it went (``report/routes/api.py::report_publishing_status``), before the start moves
into a service the Jinja pages and the Petty Cash API share (``xero/services/publish_start.py``).

Xero is never called: the token, the settings check, the system-account check and the
background worker are stubbed wherever the code that calls them lives (the route today, the
service after the extraction), so these stay green across it. Tests marked FIXED pin what the
extraction changed deliberately (they failed before it).
"""
from __future__ import annotations

import sys
import time
from types import SimpleNamespace

import char_factories as F
import pytest
from test_report_edits_state import _submitted
from test_report_expenses_state import D3, db, s3, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

HOMES = ("blueprints.report.routes.submitted", "blueprints.xero.services.publish_start")


@pytest.fixture
def xero(monkeypatch):
    """Xero stubbed out; ``xero.started`` collects the worker's arguments."""
    state = SimpleNamespace(started=[], token="tok", complete=True, system_errors=[])

    def patch(name, value):
        for home in HOMES:
            module = sys.modules.get(home)
            if module is not None and hasattr(module, name):
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


def _publish(client, owner, entity, report_id=None):
    F.login(client, owner)
    query = f"entity_id={entity.id}" + (f"&report_id={report_id}" if report_id else "")
    return client.post(f"/report/submitted/publish_to_xero?{query}")


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
    assert resp.get_json()["status"] == "publishing"
    assert _status(app, report_id) == "publishing"
    args = _wait(xero.started)[0]
    assert (str(args[0]), args[1], str(args[2]), args[4], args[6]) == (str(entity.id), D3, report_id, "tok", "unpublished")


def test_without_a_report_id_the_latest_submitted_report_goes(app, client, db, shop, xero):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner)

    assert _publish(client, owner, entity).status_code == 202
    assert str(_wait(xero.started)[0][2]) == report_id


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

    assert resp.status_code == status and words in resp.get_json()["message"]
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
    assert resp.get_json()["message"] == "This report is still a draft. Submit the day before publishing it."
    assert _status(app, report_id) == "unpublished" and not xero.started


def test_fixed_a_failed_start_never_leaves_the_report_publishing(app, client, db, shop, xero):  # noqa: F811
    """FIXED: the reset after a failure used the report id from the address, so a publish of the
    latest report (no id) that failed after the lock stayed "publishing" for good - and nothing
    can then publish, edit or delete it."""
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner)

    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("no threads today")

    xero.patch("threading", SimpleNamespace(Thread=Broken))

    resp = _publish(client, owner, entity)

    assert resp.status_code == 500
    assert _status(app, report_id) == "failed"


def test_the_status_says_how_a_publish_went(app, client, db, shop, monkeypatch):  # noqa: F811
    owner, entity = shop
    report_id, _ = _submitted(app, db, entity, owner, publishing_status="failed")
    monkeypatch.setattr("blueprints.report.routes.api.annotate_resolution",
                        lambda entity_id, items, report_id=None: [{"text": "No account code for Fees", "resolved": False,
                                                                    "resolvable": True}])
    monkeypatch.setattr("blueprints.report.routes.api.latest_publish_reason_items", lambda rows: [{"text": "x"}])
    F.login(client, owner)

    body = client.get(f"/api/report/{report_id}/publishing_status").get_json()

    assert body["publishing_status"] == "failed" and body["xero_integrated_yes"] is False
    assert body["failure_reasons"] == ["No account code for Fees"]
