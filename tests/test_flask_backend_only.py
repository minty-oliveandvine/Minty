"""What is left of Flask's old pages once its HTML frontend is gone (2026-10-20).

The pages are deleted, not hidden: their addresses answer 404 (JSON, ``test_zz_no_html_frontend``).
What stays is redirects for the addresses the other apps, the emails and Xero still send people
to - and every one of them ends in a Next.js app. Petty Cash's own hand-offs (dashboard, history,
settings, old share links) are pinned in ``test_petty_cash_web_handoff``.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import char_factories as F
import pytest

pytestmark = pytest.mark.char

HUB = "https://my.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def hosts(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB)


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, name="Vine Cafe Central", currency=currency, country=country)
        stranger = F.make_user(db, "stranger@test.com")
    return {"owner": owner, "entity": entity, "stranger": stranger}


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/login"),
        ("POST", "/login"),
        ("GET", "/reset_password"),
        ("POST", "/reset_password"),
        ("GET", "/reset_password/some-token"),
        ("GET", "/no-permission"),
        ("GET", "/admin"),
        ("GET", "/admin_dashboard"),
        ("POST", "/approve_user/u-1"),
        ("POST", "/reject_user/u-1"),
        ("GET", "/find_user"),
        ("GET", "/admin/download_statements"),
        ("POST", "/download_attachments"),
        ("GET", "/create"),
        ("GET", "/entity/success"),
        ("GET", "/me/sidebar-token"),
        ("GET", "/favicon.ico"),
        ("GET", "/report/opening"),
        ("GET", "/report/r-1"),
        ("GET", "/report/edit/r-1"),
        ("GET", "/report/download/r-1"),
        ("GET", "/report/r-1/export"),
        ("GET", "/report/r-1/screenshot"),
        ("GET", "/download/a.png"),
        ("GET", "/preview/a.png"),
        ("GET", "/api/get_draft_totals"),
        ("POST", "/report/expense/add"),
    ],
)
def test_a_retired_page_is_gone(client, shop, method, path):
    F.login(client, shop["owner"])

    resp = client.open(path, method=method)

    assert resp.status_code in (404, 405), (path, resp.status_code, resp.headers.get("Location"))
    assert resp.mimetype == "application/json"


def test_the_old_wizard_pages_under_a_company_are_gone(client, shop):
    F.login(client, shop["owner"])
    base = F.co(client, shop["entity"].id) + "/petty-cash/reports"

    for path in ("/new/opening", "/new/sale", "/new/expense", "/new/deposit", "/new/cash-count",
                 "/new/ending", "/new/submitted", "/r-1/summary", "/resume", "/download-csv"):
        resp = client.get(base + path)
        assert resp.status_code == 404, (path, resp.status_code)


def test_index_is_the_company_list_whatever_it_is_given(client, shop):
    F.login(client, shop["owner"])

    for query in ({}, {"entity_id": shop["entity"].id}):
        resp = client.get("/index", query_string=query)
        assert resp.status_code == 302
        assert urlsplit(resp.headers["Location"]).path == "/entity"


def test_creating_a_company_is_the_wizards_and_only_a_get(client, shop):
    F.login(client, shop["owner"])

    assert client.get("/entity/create").status_code == 302
    assert client.post("/entity/create", data={"entity_name": "X"}).status_code == 405


def test_xero_not_connected_goes_to_the_hubs_integration_tab(client, shop):
    F.login(client, shop["owner"])
    entity_id = shop["entity"].id

    resp = client.get(F.co(client, entity_id) + "/xero-not-connected")

    assert resp.status_code == 302
    assert urlsplit(resp.headers["Location"]).path.endswith("/settings/integration")


def test_a_refused_browser_lands_on_the_company_list(client, shop):
    """A stranger at someone else's company: told so on minty-web's company list, not a Flask page."""
    F.login(client, shop["stranger"])

    resp = client.get(F.co(client, shop["entity"].id) + "/settings/users")

    assert resp.status_code == 302
    assert urlsplit(resp.headers["Location"]).path == "/entity"


def test_a_superadmin_signs_in_to_the_company_list_like_everyone(app, db):
    from blueprints.auth.models.user import User
    from blueprints.auth.routes.email_auth import _post_login_redirect

    with app.app_context():
        admin = F.make_user(db, "admin@test.com", system_role=User.SYSTEM_ROLE_SUPERUSER)
        with app.test_request_context():
            assert _post_login_redirect(admin) == "/index"
