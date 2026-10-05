"""The URL security round (2026-10-05): who may call what, where a redirect may go, and
what a response gives away.

Each test pins one hole the audit found open:

* ``/api/check-dept-bank-yest`` rewrote any company's bank deposit (and Xero) with no login;
* ``/download/<key>`` signed ANY S3 key for any signed-in user;
* the all-company statement and attachment exports had no superuser check;
* ``/entity/<id>/enter`` turned ANY token (the onboarding one too) into a session, for any
  company;
* ``next`` let ``/%09/evil.com`` and ``/\\evil.com`` through, and ``/xero_auth`` took any URL;
* GETs published to Xero, disconnected Xero, and asked about an invite by its token;
* the old ``?token=`` share entries ignored the ShareLink row.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlsplit

import char_factories as F
import pytest

pytestmark = pytest.mark.char


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def s3(monkeypatch):
    return F.install_fake_s3(monkeypatch)


@pytest.fixture
def shop(app, db):
    """An owner (admin) of an entity, and a signed-up stranger who belongs to nothing."""
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        F.seed_sales_methods(db, owner, entity)
        stranger = F.make_user(db, "stranger@test.com")
        db.session.commit()
    return owner, entity, stranger


def _signed_in(client) -> bool:
    # The session itself: a page probe would meet the Terms gate first.
    with client.session_transaction() as sess:
        return bool(sess.get("_user_id"))


def _draft_report_id(client, app, entity) -> str:
    """Open a draft through the real wizard and return its id."""
    from models.db import Report

    resp = client.post(
        "/report/opening",
        data={
            "entity_id": entity.id,
            "transaction_date": F.iso(date(2026, 9, 1)),
            "opening_balance": "1000.00",
            "cash_addition": "0",
            "action_type": "save_next",
        },
    )
    assert resp.status_code in (200, 302), resp.data[:300]
    with app.app_context():
        return str(Report.query.filter(Report.company == entity.id).first().id)


# ---- the shared redirect rule ------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate, expected",
    [
        ("/entity/abc?x=1", "/entity/abc?x=1"),
        ("//evil.com", None),
        ("/\\evil.com", None),
        ("/\t/evil.com", None),
        ("/\n/evil.com", None),
        ("/\r/evil.com", None),
        ("https://evil.com", None),
        ("javascript:alert(1)", None),
        ("evil.com", None),
        ("/a/../b", None),
        ("", None),
        (None, None),
    ],
)
def test_safe_internal_path_keeps_only_paths_on_this_site(candidate, expected):
    from blueprints.shared.safe_redirect import safe_internal_path

    assert safe_internal_path(candidate) == expected


def test_enter_never_redirects_off_site(shop, client):
    owner, entity, _ = shop
    F.login(client, owner)
    for evil in ("/%09/evil.com", "/%5Cevil.com", "//evil.com", "https://evil.com"):
        resp = client.get(f"{F.co(client, entity.id)}/enter?next={evil}")
        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert "evil.com" not in location, (evil, location)
        assert location.endswith(f"{F.co(client, entity.id)}/petty-cash"), location


def test_handoff_never_forwards_an_off_site_next(shop, client, monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", "http://hub.minty.test/")
    owner, _, _ = shop
    F.login(client, owner)
    resp = client.get("/handoff/minty-web?next=/%09/evil.com")
    query = parse_qs(urlsplit(resp.headers["Location"]).query)
    assert query["next"] == ["/subscription"]


def test_xero_sign_in_does_not_remember_an_outside_next(app, client, db):
    client.get("/xero_auth?next=https://evil.com/steal")
    with client.session_transaction() as sess:
        assert "next_after_login" not in sess
    client.get("/xero_auth?next=/entity")
    with client.session_transaction() as sess:
        assert sess.get("next_after_login") == "/entity"


# ---- /entity/<id>/enter takes module tokens for members only ----------------------------


def _module_token(app, user_id, entity_id) -> str:
    from blueprints.entity.routes.modules import _generate_module_token

    with app.test_request_context():
        return _generate_module_token(user_id, entity_id, "", "admin")


def test_enter_logs_a_member_in_with_a_module_token(shop, client, app):
    owner, entity, _ = shop
    token = _module_token(app, owner.id, entity.id)
    resp = client.get(f"{F.co(client, entity.id)}/enter?token={token}")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"{F.co(client, entity.id)}/petty-cash")
    assert _signed_in(client)


def test_enter_refuses_the_onboarding_token(shop, client, app):
    from blueprints.entity.routes.create import _mint_onboarding_token

    owner, entity, _ = shop
    with app.test_request_context():
        token = _mint_onboarding_token(owner.id)
    client.get(f"{F.co(client, entity.id)}/enter?token={token}")
    assert not _signed_in(client)


def test_enter_refuses_a_company_the_person_is_not_in(shop, client, app):
    _, entity, stranger = shop
    token = _module_token(app, stranger.id, "")
    client.get(f"{F.co(client, entity.id)}/enter?token={token}")
    assert not _signed_in(client)


# ---- the bank-deposit correction -----------------------------------------------------------


def test_bank_deposit_correction_needs_a_member_and_a_post(shop, client, monkeypatch):
    import sys

    owner, entity, stranger = shop
    legacy = sys.modules["blueprints.report.routes.legacy"]
    calls = []
    monkeypatch.setattr(legacy, "update_after_deposit_change", lambda *a, **k: calls.append(a))
    body = {"amount": 0, "bankAccount": "x", "date": "2026-09-01"}
    url = f"/api/check-dept-bank-yest/{entity.id}"

    # No login at all: refused before anything is read.
    assert client.post(url, json=body).status_code in (302, 401)
    # Signed in, but not a member of this company.
    F.login(client, stranger)
    assert client.post(url, json=body, headers={"Accept": "application/json"}).status_code in (302, 403)
    assert calls == []

    F.login(client, owner)
    assert client.get(url).status_code == 405
    assert client.post(url, json=body).status_code == 200
    assert calls, "a member reaches the correction"


# ---- downloads -----------------------------------------------------------------------------


def test_receipt_download_only_for_someone_who_may_see_the_report(shop, client, app):
    owner, entity, stranger = shop
    F.login(client, owner)
    report_id = _draft_report_id(client, app, entity)
    key = f"expenses/{report_id}/upload_abc.jpg"

    resp = client.get(f"/download/{key}")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(key)

    assert client.get("/download/expenses/not-a-uuid/x.jpg").status_code == 404
    assert client.get("/download/somewhere/else.jpg").status_code == 404

    F.login(client, stranger)
    assert client.get(f"/download/{key}").status_code == 403


def test_receipt_preview_only_for_someone_who_may_see_the_report(shop, client, app):
    owner, entity, stranger = shop
    F.login(client, owner)
    key = f"expenses/{_draft_report_id(client, app, entity)}/upload_abc.jpg"

    assert client.get("/preview/expenses/not-a-uuid/x.jpg").status_code == 404
    F.login(client, stranger)
    assert client.get(f"/preview/{key}").status_code == 403
    client.get("/logout")
    assert client.get(f"/preview/{key}").status_code in (302, 401)


def test_all_company_exports_are_superuser_only(shop, client):
    owner, _, _ = shop
    F.login(client, owner)
    assert client.get("/admin/download_statements").status_code == 403
    assert client.post("/admin/download_statements", data={}).status_code == 403
    assert client.post("/download_attachments", data={}).status_code == 403


# ---- no state change by GET ----------------------------------------------------------------


def test_state_changing_routes_refuse_get(shop, client):
    owner, entity, _ = shop
    F.login(client, owner)
    assert client.get(f"/report/submitted/publish_to_xero?entity_id={entity.id}").status_code == 405
    # (Disconnecting is minty-web's tab since phase 2: bearer POST /api/me/company/xero/disconnect,
    # no GET and no session route at all.)
    assert client.get(f"/entity/settings/xero/disconnect?entity_id={entity.id}").status_code == 404
    assert client.get(f"/api/me/company/xero/disconnect?entity={entity.id}").status_code == 405
    assert client.get("/legal/invite-terms-status?invite=x").status_code == 405


@pytest.mark.parametrize(
    "path",
    ["/insert_xero_transaction", "/remove/connections/all", "/api/refresh_xero_token",
     "/mytoken", "/event_id", "/debug/xero-settings/abc", "/Minty_Report_X/ending?token=abc"],
)
def test_deleted_routes_are_gone(client, path):
    assert client.get(path).status_code == 404


def test_old_share_token_no_longer_opens_a_report(shop, client):
    _, entity, _ = shop
    resp = client.get(f"{F.co(client, entity.id)}/petty-cash/reports/summary?token=anything")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


# ---- what responses give away --------------------------------------------------------------


def test_every_response_carries_the_hardening_headers(client):
    resp = client.get("/")
    assert resp.headers["Referrer-Policy"] == "same-origin"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "SAMEORIGIN"
    # Tests run as development (plain http): no HSTS there.
    assert "Strict-Transport-Security" not in resp.headers


def test_a_page_with_a_secret_in_its_path_is_never_cached(client, db):
    resp = client.get("/reset_password/some-reset-token")
    assert resp.headers["Cache-Control"] == "no-store"


def test_the_access_log_blanks_secret_path_segments(app):
    from pettycash.core.http_hardening import loggable_path

    for path, logged in [
        ("/reset_password/abc123", "/reset_password/[redacted]"),
        ("/invitation/accept/tok", "/invitation/accept/[redacted]"),
        ("/Minty_Report/AB/01_Sep_2026/s3cr3t/", "/Minty_Report/[redacted]/"),
        ("/entity/abc?token=zzz", "/entity/abc"),
    ]:
        with app.test_request_context(path):
            adapter = app.url_map.bind("localhost")
            try:
                _, args = adapter.match(urlsplit(path).path)
            except Exception:
                args = {}
            from flask import request

            request.view_args = args
            assert loggable_path() == logged, path
