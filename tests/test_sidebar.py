"""The sidebar on Flask's own pages - minty-web's one drawer, two views (the menu and My
Profile), ported on 2026-09-30 (``blueprints/shared/sidebar.py``,
``templates/components/minty_sidebar.html``, ``static/js/minty_sidebar.js``).

What is pinned here: the menu each kind of page draws and where every item leads; the token
``GET /me/sidebar-token`` hands the page (and that it opens the same ``/api/me/profile``
minty-web reads); the hub routes answering billing-frontend's origin by name, now that its
own copy of the sidebar reads them; and every page family carrying the new partial and none of
the old drawers.

Imports of project modules happen inside tests (the conftest ``app`` fixture re-imports the
blueprints).
"""

from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"
PAYMENTS = "http://payments.minty.test"
TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def origins(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")
    monkeypatch.setenv("FRONTEND_APP_URL", PAYMENTS + "/")


@pytest.fixture
def people(app, db):
    with app.app_context():
        currency = F.seed_currency(db, denominations=())
        country = F.seed_country(db, currency)
        olive = F.make_user(db, "olive@test.com", first_name="Olive", last_name="Vine")
        both = F.make_entity(db, olive, name="Olive Shop", modules=("PETTY_CASH", "PAYMENT_REQUEST"),
                             currency=currency, country=country)
        petty = F.make_entity(db, olive, name="Petty Only", modules=("PETTY_CASH",),
                              currency=currency, country=country)
        payments = F.make_entity(db, olive, name="Payments Only", modules=("PAYMENT_REQUEST",),
                                 currency=currency, country=country)
    return {"olive": olive, "both": both, "petty": petty, "payments": payments}


def _menu(app, path: str, *, user_id: str, org_id: str | None = None, **context) -> str:
    """The partial as the page at ``path`` draws it, for a signed-in person."""
    from flask import render_template
    from flask_login import login_user

    from models.db import User

    with app.test_request_context(path):
        login_user(User.query.get(user_id))
        org = SimpleNamespace(id=org_id) if org_id else None
        return render_template("components/minty_sidebar.html", org=org, **context)


def _row(html: str, label: str):
    """The menu row whose text is ``label``: its opening tag's match, or None."""
    for match in re.finditer(r'<a href="([^"]*)"([^>]*)>(.*?)</a>', html, re.S):
        if re.sub(r"<[^>]+>", " ", match.group(3)).split() == label.split():
            return match
    return None


def _link(html: str, label: str) -> str | None:
    """The href of the menu row whose text is ``label`` (None when there is no such row)."""
    row = _row(html, label)
    return row.group(1) if row else None


def _is_current(html: str, label: str) -> bool:
    """Whether the row is marked as the page being shown (for assistive technology only)."""
    row = _row(html, label)
    return bool(row) and 'aria-current="page"' in row.group(2)


# --- the menu --------------------------------------------------------------------------------


def test_inside_a_company_the_menu_leads_everywhere_minty_webs_does(app, people, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "1")
    shop = people["both"].id
    html = _menu(app, f"/entity/{shop}", user_id=people["olive"].id, org_id=shop)

    assert _link(html, "Select Entity") == "/entity"
    assert _link(html, "Manage subscriptions") == "/handoff/minty-web?next=/subscription"
    assert _link(html, "Dashboard") == f"/entity/{shop}"
    assert _link(html, "Reports") == f"/entity/{shop}/reports"
    assert _link(html, "Bills") == f"/entity/{shop}/bills"
    # this app's own settings - Petty Cash's (Settings opens the settings of the app it is in)
    assert _link(html, "Settings") == f"/entity/settings/entity/{shop}"
    assert _link(html, "Logout") == "/logout"
    assert _link(html, "Manage Subscription") == "/handoff/minty-web?next=/subscription"
    assert 'data-module-nav="PETTY_CASH">' in html
    assert 'data-module-nav="PAYMENT_REQUEST">' in html
    assert f'data-entity-id="{shop}"' in html
    assert "Subscriptions Overview" in html


def test_the_person_is_at_the_top_and_opens_my_profile(app, people):
    html = _menu(app, "/entity", user_id=people["olive"].id)

    assert 'data-sidebar-show="profile" aria-label="Olive Vine, My Profile"' in html
    assert '<span class="msb-avatar" aria-hidden="true" data-viewer-initials>OV</span>' in html
    assert 'data-viewer-name="Olive Vine"' in html


def test_a_module_that_is_off_is_drawn_hidden_for_the_module_page_to_show(app, people):
    shop = people["petty"].id
    html = _menu(app, f"/entity/{shop}", user_id=people["olive"].id, org_id=shop)

    assert 'data-module-nav="PETTY_CASH">' in html
    assert 'data-module-nav="PAYMENT_REQUEST" style="display:none">' in html


def test_on_the_entity_list_there_is_no_company_and_no_settings(app, people):
    # handed a company all the same: a person choosing one is in none (minty-web's rule)
    html = _menu(app, "/entity", user_id=people["olive"].id, org_id=people["both"].id)

    assert _link(html, "Select Entity") == "/entity"
    assert _is_current(html, "Select Entity")
    assert _link(html, "Settings") is None
    assert _link(html, "Dashboard") is None
    assert "data-module-nav" not in html
    assert 'data-entity-id=""' in html
    assert _link(html, "Logout") == "/logout"


def test_subscriptions_dark_no_door_into_them(app, people, monkeypatch):
    monkeypatch.setenv("SUBSCRIPTION_ENABLED", "0")
    html = _menu(app, "/entity", user_id=people["olive"].id)

    assert _link(html, "Manage subscriptions") is None
    # the card is not drawn at all - no heading, no figures, no door into a dark portal
    assert "Subscriptions Overview" not in html
    assert "Your subscription" not in html


def test_on_the_payment_request_pages_settings_is_the_payments_apps(app, people):
    # Flask's settings tabs in the Payment Request dress: that app's Payment Settings, where
    # billing-frontend's own Settings goes too (through the route that mints the token)
    shop = people["both"].id
    html = _menu(app, f"/entity/settings/users/{shop}", user_id=people["olive"].id, org_id=shop,
                 sidebar_from_bills=True)

    assert _link(html, "Settings") == f"/entity/settings/payments/{shop}?from=bills"
    assert not _is_current(html, "Settings")


def test_on_the_petty_cash_settings_page_settings_is_the_page_shown(app, people):
    shop = people["both"].id
    html = _menu(app, f"/entity/settings/entity/{shop}", user_id=people["olive"].id, org_id=shop)

    assert _link(html, "Settings") == f"/entity/settings/entity/{shop}"
    assert _is_current(html, "Settings")


def test_a_company_without_petty_cash_gets_the_general_settings(app, people):
    # Petty Cash Settings refuses a company without the module (require_module): no dead end
    shop = people["payments"].id
    html = _menu(app, f"/entity/{shop}/settings/xero", user_id=people["olive"].id, org_id=shop)

    assert _link(html, "Settings") == f"/entity/{shop}/settings/xero"
    assert _is_current(html, "Settings")


def test_the_dashboards_setup_links_open_the_petty_cash_settings():
    # "Setup Required" lists the Petty Cash Settings tab's accounts and contacts; its button and
    # the "Settings -> Petty Cash" hint used to open Entity & Integration instead
    source = (TEMPLATES / "entity" / "entity_dashboard_v2.html").read_text(encoding="utf-8")
    button = re.search(r'<a href="([^"]*)"[^>]*>\s*Set Up Settings', source)
    hint = re.search(r'<a href="([^"]*)"[^>]*>Settings → Petty Cash</a>', source)

    assert button and button.group(1) == "{{ url_for('entity_settings_entity', org_id=org.id) }}"
    assert hint and hint.group(1) == "{{ url_for('entity_settings_entity', org_id=org.id) }}"


def test_the_reads_it_is_told_about(app, people, monkeypatch):
    monkeypatch.setenv("BILLING_API_URL", "http://billing.minty.test/")
    html = _menu(app, "/entity", user_id=people["olive"].id)

    assert 'data-token-url="/me/sidebar-token"' in html
    assert 'data-profile-url="/api/me/profile"' in html
    assert 'data-billing-api="http://billing.minty.test"' in html


# --- the token -------------------------------------------------------------------------------


def test_no_session_no_token(client, people):
    resp = client.get("/me/sidebar-token")

    assert resp.status_code == 401
    assert resp.get_json() == {"error": "unauthorized"}


def test_the_token_is_an_unscoped_one_for_the_person_signed_in(app, client, people):
    F.login(client, people["olive"])
    resp = client.get("/me/sidebar-token")

    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    # never readable by another origin's credentialed request
    assert "Access-Control-Allow-Credentials" not in resp.headers
    body = resp.get_json()
    assert body["valid_for_seconds"] == 1800
    claims = jwt.decode(body["token"], app.config["SECRET_KEY"], algorithms=["HS256"])
    assert claims["user_id"] == people["olive"].id
    assert claims["entity_id"] == ""


def test_the_token_opens_the_profile_minty_web_reads(client, people):
    F.login(client, people["olive"])
    token = client.get("/me/sidebar-token").get_json()["token"]
    shop = people["both"].id

    resp = client.get(f"/api/me/profile?entity={shop}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["initials"] == "OV"
    assert body["entity"]["modules"] == ["PAYMENT_REQUEST", "PETTY_CASH"]


# --- the hub routes, called from billing-frontend too ------------------------------------------


@pytest.mark.parametrize(
    "origin, answered",
    [(HUB, HUB), (PAYMENTS, PAYMENTS), ("http://evil.test", HUB), (None, HUB)],
)
def test_the_hub_names_the_caller_it_allows(app, client, people, origins, origin, answered):
    F.login(client, people["olive"])
    token = client.get("/me/sidebar-token").get_json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    if origin:
        headers["Origin"] = origin

    for method in ("GET", "OPTIONS"):
        resp = client.open("/api/me/profile", method=method, headers=headers)
        assert resp.headers["Access-Control-Allow-Origin"] == answered, method
        assert "Origin" in resp.headers["Vary"]
        assert "PATCH" in resp.headers["Access-Control-Allow-Methods"]


# --- every page family carries it ------------------------------------------------------------

PAGES = [
    "entity/entity_create.html",
    "entity/entity_dashboard_v2.html",
    "entity/entity_list_empty.html",
    "entity/entity_no_permission.html",
    "entity/index.html",
    "entity/settings.html",
    "entity/settings_entity.html",
    "entity/settings_module.html",
    "entity/settings_users.html",
    "entity/settings_entity_bills_ui.html",
    "entity/settings_module_bills_ui.html",
    "entity/settings_users_bills_ui.html",
    "entity/settings_xero_bills_ui.html",
    "report/cash_count.html",
    "report/deposit.html",
    "report/ending.html",
    "report/expense.html",
    "report/opening.html",
    "report/sales.html",
    "report_history/report_history.html",
    "report_list.html",
]


@pytest.mark.parametrize("page", PAGES)
def test_every_header_opens_the_sidebar(page):
    source = (TEMPLATES / page).read_text(encoding="utf-8")

    assert source.count("{% include 'components/minty_sidebar.html' %}") == 1
    assert source.count('data-sidebar-open="menu"') == 1
    assert source.count('data-sidebar-open="profile"') == 1
    assert 'onclick="toggleMenu()"' not in source
    if page.endswith("_bills_ui.html"):
        assert "{% with sidebar_from_bills=True %}" in source


def test_the_old_drawers_are_gone_everywhere():
    for path in TEMPLATES.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        for old in ("sidepanel.html", "nav-drawer", "Open profile in Payments"):
            assert old not in source, f"{path.relative_to(TEMPLATES)} still has {old!r}"
