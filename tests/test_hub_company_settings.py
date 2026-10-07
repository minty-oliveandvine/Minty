"""A company's Users and Entity & Integration tabs, minty-web's since phase 2 (2026-10-05): the
bearer routes ``/api/me/company/*`` (``blueprints/entity/routes/hub_settings.py``) and the Flask
addresses that now hand over to them.

What is pinned here is what the session pages got wrong (Minty settings-tabs survey, 2026-09-30):
the company comes from ``?entity=`` alone; roles are the assignable four; an address to invite is
an address (no markup); names are not editable on this tab; every action asks its own permission
and the rank rule. The guard SERVICES (payer, last admin, nominee) have their own tests
(``test_membership_removal_guards.py``); here, that the routes run them and say so.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

import char_factories as F

pytestmark = pytest.mark.char

HUB = "http://hub.minty.test"


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture(autouse=True)
def hub(monkeypatch):
    monkeypatch.setenv("MINTY_WEB_URL", HUB + "/")


@pytest.fixture(autouse=True)
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


def _member(app, db, entity, email, role):
    with app.app_context():
        from models.db import UserEntity

        user = F.make_user(db, email, first_name=email.split("@")[0].title(), last_name="Member")
        db.session.add(UserEntity(user_id=user.id, entity_id=entity.id, role=role, approved=True))
        db.session.commit()
    return user


@pytest.fixture
def shop(app, db):
    """Olive & Vine with an admin, an accountant, a shop manager and a cashier - and a second
    company the admin is in alone."""
    with app.app_context():
        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        admin = F.make_user(db, "admin@test.com", first_name="Ada", last_name="Admin")
        entity = F.make_entity(db, admin, name="Olive & Vine", currency=currency, country=country)
        other = F.make_entity(db, admin, name="Other Co", currency=currency, country=country)
    return {
        "admin": admin,
        "entity": entity,
        "other": other,
        "currency": currency,
        "accountant": _member(app, db, entity, "acc@test.com", "accountant"),
        "manager": _member(app, db, entity, "mgr@test.com", "shop_manager"),
        "cashier": _member(app, db, entity, "cash@test.com", "cashier"),
    }


def call(client, app, method, path, user, entity_id=None, query=None, **kwargs):
    q = {**({"entity": entity_id} if entity_id else {}), **(query or {})}
    return client.open(path, method=method, query_string=q, headers=F.hub_headers(app, user.id), **kwargs)


# --- the door ------------------------------------------------------------------------------------


def test_the_preflight_names_delete_too(client, shop):
    resp = client.options("/api/me/company/users/x", headers={"Origin": HUB, "Access-Control-Request-Method": "DELETE"})
    assert resp.status_code == 204
    assert "DELETE" in resp.headers["Access-Control-Allow-Methods"]
    assert resp.headers["Access-Control-Allow-Origin"] == HUB


def test_no_token_no_company_and_someone_elses_company_are_refused(app, client, db, shop):
    assert client.get("/api/me/company/users", query_string={"entity": shop["entity"].id}).status_code == 401
    assert call(client, app, "GET", "/api/me/company/users", shop["admin"]).status_code == 403
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")
    assert call(client, app, "GET", "/api/me/company/users", stranger, shop["entity"].id).status_code == 403


# --- Users -----------------------------------------------------------------------------------------


def test_the_users_tab_reads_the_members_their_rights_and_the_roles_one_may_give(app, client, shop):
    resp = call(client, app, "GET", "/api/me/company/users", shop["manager"], shop["entity"].id)

    assert resp.status_code == 200, resp.get_json()
    page = resp.get_json()
    assert page["company"] == {"id": shop["entity"].id, "name": "Olive & Vine"}
    assert page["modules"] == ["PETTY_CASH"]
    rows = {m["email"]: m for m in page["members"]}
    assert set(rows) == {"admin@test.com", "acc@test.com", "mgr@test.com", "cash@test.com"}
    # a shop manager may change roles at or below their own, and remove nobody (accountant+)
    assert rows["cash@test.com"]["can_change_role"] is True
    assert rows["mgr@test.com"]["can_change_role"] is True and rows["mgr@test.com"]["is_you"] is True
    assert rows["admin@test.com"]["can_change_role"] is False
    assert all(m["can_remove"] is False for m in page["members"])
    assert [r["value"] for r in page["roles"]] == ["shop_manager", "cashier"]
    assert page["can_invite"] is True and page["invitations"] == []
    assert rows["admin@test.com"]["role_label"] == "Admin" and rows["admin@test.com"]["initials"] == "AA"


def test_the_subscriber_is_the_payer_not_a_rank(app, client, shop, monkeypatch):
    """"Who can change our modules" needs admin rank AND the payer, so the tab marks the payer -
    whoever they are, and nobody else."""
    from blueprints.subscription.services import store_ro as store

    monkeypatch.setattr(store, "payer_for_entity", lambda _eid: shop["accountant"].id)
    page = call(client, app, "GET", "/api/me/company/users", shop["admin"], shop["entity"].id).get_json()
    assert [m["email"] for m in page["members"] if m["subscriber"]] == ["acc@test.com"]

    monkeypatch.setattr(store, "payer_for_entity", lambda _eid: None)
    page = call(client, app, "GET", "/api/me/company/users", shop["admin"], shop["entity"].id).get_json()
    assert not any(m["subscriber"] for m in page["members"])


def test_a_cashier_may_not_open_the_tab(app, client, shop):
    assert call(client, app, "GET", "/api/me/company/users", shop["cashier"], shop["entity"].id).status_code == 403


def test_a_role_change_is_the_role_only_and_checked_against_rank(app, client, shop):
    entity = shop["entity"].id
    cashier = shop["cashier"]

    changed = call(client, app, "PATCH", f"/api/me/company/users/{cashier.id}", shop["manager"], entity,
                   json={"role": "shop_manager", "first_name": "Renamed"})
    assert changed.status_code == 200, changed.get_json()
    assert changed.get_json()["role"] == "shop_manager"
    page = call(client, app, "GET", "/api/me/company/users", shop["admin"], entity).get_json()
    row = next(m for m in page["members"] if m["id"] == cashier.id)
    assert row["role"] == "shop_manager" and row["first_name"] == "Cash"  # the name is not this tab's

    above = call(client, app, "PATCH", f"/api/me/company/users/{cashier.id}", shop["manager"], entity, json={"role": "admin"})
    assert above.status_code == 403
    assert call(client, app, "PATCH", f"/api/me/company/users/{shop['admin'].id}", shop["manager"], entity,
                json={"role": "cashier"}).status_code == 403


@pytest.mark.parametrize("role", ["entity_base", "super_admin", "owner", "Shop Manager", ""])
def test_only_the_four_assignable_roles_are_taken(app, client, shop, role):
    resp = call(client, app, "PATCH", f"/api/me/company/users/{shop['cashier'].id}", shop["admin"], shop["entity"].id,
                json={"role": role})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Pick one of the roles offered."}


def test_the_company_is_the_query_s_never_the_body_s(app, client, shop):
    """The session route checked the query's company and wrote through the body's."""
    other = shop["other"].id
    resp = call(client, app, "PATCH", f"/api/me/company/users/{shop['cashier'].id}", shop["admin"], other,
                json={"role": "accountant", "entity_id": shop["entity"].id})
    # the cashier is not in the query's company: nothing to change there
    assert resp.status_code == 404


def test_removal_runs_the_guards_in_order_and_removes(app, client, shop):
    entity = shop["entity"].id
    # an accountant may not remove an admin (rank first)
    refused = call(client, app, "DELETE", f"/api/me/company/users/{shop['admin'].id}", shop["accountant"], entity)
    assert refused.status_code == 403
    # the admin may not remove themself: the last admin
    last = call(client, app, "DELETE", f"/api/me/company/users/{shop['admin'].id}", shop["admin"], entity)
    assert last.status_code == 409 and "admin" in last.get_json()["error"].lower()
    # a shop manager may remove nobody (USER_ROLE_DELETE is accountant+)
    assert call(client, app, "DELETE", f"/api/me/company/users/{shop['cashier'].id}", shop["manager"], entity).status_code == 403

    gone = call(client, app, "DELETE", f"/api/me/company/users/{shop['cashier'].id}", shop["accountant"], entity)
    assert gone.status_code == 200, gone.get_json()
    emails = {m["email"] for m in call(client, app, "GET", "/api/me/company/users", shop["admin"], entity).get_json()["members"]}
    assert "cash@test.com" not in emails


def test_the_payer_is_not_removed(app, client, shop, monkeypatch):
    from blueprints.subscription.services import store_ro as store

    monkeypatch.setattr(store, "rows_for_entity", lambda eid: [type("Row", (), {"payer_user_id": shop["accountant"].id})()])
    resp = call(client, app, "DELETE", f"/api/me/company/users/{shop['accountant'].id}", shop["admin"], shop["entity"].id)
    assert resp.status_code == 409
    assert resp.get_json()["error"].startswith("I can't remove the person who pays")


# --- invitations -----------------------------------------------------------------------------------


def _invite(client, app, user, entity_id, **body):
    payload = {"email": "new@test.com", "role": "cashier", "first_name": "New", "last_name": "Person", **body}
    return call(client, app, "POST", "/api/me/company/invitations", user, entity_id, json=payload)


def test_an_invitation_is_sent_and_listed(app, client, shop, mail):
    sent = _invite(client, app, shop["manager"], shop["entity"].id)

    assert sent.status_code == 201, sent.get_json()
    assert sent.get_json()["email_sent"] is True
    assert mail.to("new@test.com")
    page = call(client, app, "GET", "/api/me/company/users", shop["manager"], shop["entity"].id).get_json()
    assert [(i["email"], i["role"], i["can_manage"]) for i in page["invitations"]] == [("new@test.com", "cashier", True)]


@pytest.mark.parametrize(
    "email, sentence",
    [
        ("<svg/onload=alert(1)>@x.co", "That doesn't look like an email address."),
        ("a'b@x.co", "That doesn't look like an email address."),
        ("no-at-sign.example", "That doesn't look like an email address."),
        ("two@@x.co", "That doesn't look like an email address."),
        ("홍길동@example.com", "Email can only contain English letters, numbers and symbols."),
        ("x" * 140 + "@example.com", "That doesn't look like an email address."),
    ],
)
def test_an_invitation_goes_only_to_an_address(app, client, shop, email, sentence):
    resp = _invite(client, app, shop["admin"], shop["entity"].id, email=email)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": sentence}


@pytest.mark.parametrize("names", [{"first_name": ""}, {"last_name": "  "}, {"first_name": "", "last_name": ""}])
def test_an_invitation_needs_both_names(app, client, shop, names):
    """A new invitee's account is made from them when they sign in by code."""
    resp = _invite(client, app, shop["admin"], shop["entity"].id, **names)
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "I need their first and last name."}


def test_an_invitation_s_role_is_assignable_and_not_above_the_inviter(app, client, shop):
    assert _invite(client, app, shop["admin"], shop["entity"].id, role="entity_base").status_code == 400
    assert _invite(client, app, shop["manager"], shop["entity"].id, role="admin").status_code == 403
    assert _invite(client, app, shop["cashier"], shop["entity"].id).status_code == 403  # no USER_INVITE


def test_an_invitation_is_managed_only_through_its_own_company(app, client, shop):
    sent = _invite(client, app, shop["admin"], shop["entity"].id)
    page = call(client, app, "GET", "/api/me/company/users", shop["admin"], shop["entity"].id).get_json()
    invitation = page["invitations"][0]["id"]
    assert sent.status_code == 201

    # named under another company of the same admin: not found there
    elsewhere = call(client, app, "POST", f"/api/me/company/invitations/{invitation}/cancel", shop["admin"], shop["other"].id)
    assert elsewhere.status_code == 404

    # resent at once: the cooldown, counted down by the page
    soon = call(client, app, "POST", f"/api/me/company/invitations/{invitation}/resend", shop["admin"], shop["entity"].id)
    assert soon.status_code == 429 and soon.get_json()["retry_after"] > 0

    cancelled = call(client, app, "POST", f"/api/me/company/invitations/{invitation}/cancel", shop["admin"], shop["entity"].id)
    assert cancelled.status_code == 200
    page = call(client, app, "GET", "/api/me/company/users", shop["admin"], shop["entity"].id).get_json()
    assert page["invitations"] == []


# --- Entity & Integration --------------------------------------------------------------------------


def test_the_integration_tab_reads_the_company_its_lists_and_its_xero_state(app, client, shop):
    resp = call(client, app, "GET", "/api/me/company/integration", shop["cashier"], shop["entity"].id)

    assert resp.status_code == 200, resp.get_json()
    page = resp.get_json()
    assert page["company"]["name"] == "Olive & Vine"
    assert page["company"]["currency_id"] == shop["currency"].id
    assert {"code": "HK", "name": page["countries"][0]["name"]} in page["countries"]
    assert page["xero"]["connected"] is False and page["xero"]["needs_reconnect"] is False
    assert page["can_edit"] is False and page["can_rename"] is False


def test_saving_the_company_s_settings(app, client, db, shop):
    entity = shop["entity"].id
    # an accountant may change country/currency but not the name
    assert call(client, app, "PATCH", "/api/me/company/integration", shop["accountant"], entity,
                json={"name": "New Name"}).status_code == 403
    # a cashier may change nothing
    assert call(client, app, "PATCH", "/api/me/company/integration", shop["cashier"], entity,
                json={"country_code": "HK"}).status_code == 403

    for body, status in (
        ({"name": "   "}, 422),
        ({"name": "x" * 101}, 422),
        ({"name": "Other Co"}, 422),
        ({"country_code": "ZZ"}, 422),
        ({"currency_id": "not-a-uuid"}, 422),
        ({"currency_id": F.new_id()}, 422),
    ):
        resp = call(client, app, "PATCH", "/api/me/company/integration", shop["admin"], entity, json=body)
        assert resp.status_code == status, (body, resp.get_json())

    saved = call(client, app, "PATCH", "/api/me/company/integration", shop["admin"], entity,
                 json={"name": "Olive and Vine Ltd", "country_code": "hk"})
    assert saved.status_code == 200, saved.get_json()
    assert saved.get_json()["company"]["name"] == "Olive and Vine Ltd"
    assert saved.get_json()["message"] == "Settings saved!"


def test_disconnecting_says_so_and_a_failure_says_so_too(app, client, shop, monkeypatch):
    entity = shop["entity"].id
    done = call(client, app, "POST", "/api/me/company/xero/disconnect", shop["admin"], entity)
    assert done.status_code == 200, done.get_json()
    assert done.get_json()["xero"]["status"] == "disconnected"

    import blueprints.xero.services.disconnect as disconnect

    def boom(_entity_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(disconnect, "disconnect_entity_from_xero", boom)
    failed = call(client, app, "POST", "/api/me/company/xero/disconnect", shop["admin"], entity)
    assert failed.status_code == 502
    assert "may still show as connected" in failed.get_json()["error"]
    assert call(client, app, "POST", "/api/me/company/xero/disconnect", shop["cashier"], entity).status_code == 403


# --- the Flask addresses hand over ---------------------------------------------------------------


@pytest.mark.parametrize("tab", ["users", "integration"])
def test_the_flask_tab_hands_over_with_what_was_flashed(app, client, shop, tab):
    F.login(client, shop["admin"])
    with client.session_transaction() as session:
        session["_flashes"] = [("success", "You're connected to Xero!")]

    resp = client.get(f"{F.co(client, shop['entity'].id)}/settings/{tab}")

    assert resp.status_code == 302
    where = urlsplit(resp.headers["Location"])
    assert f"{where.scheme}://{where.netloc}{where.path}" == f"{HUB}/landing"
    query = parse_qs(where.query)
    next_path = urlsplit(query["next"][0])
    assert next_path.path == f"/entity/{shop['entity'].id[:8]}/olive-and-vine/settings/{tab}"
    flash = parse_qs(next_path.query)["flash"][0]
    read = call(client, app, "GET", f"/api/me/company/{tab}", shop["admin"], shop["entity"].id, query={"flash": flash})
    assert read.get_json()["notices"] == [{"category": "success", "message": "You're connected to Xero!"}]
