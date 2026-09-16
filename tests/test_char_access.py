"""Characterisation: who may do what - users, system role, entity roles, invitations, legal.

The redesign renames ``roles``/``permissions``/``role_permissions`` to the singular,
``invitations`` to ``invitation``, narrows ``invitation_status`` and turns ``user.system_role``
into the ``system_role`` enum (D6 restores the column). What is pinned is the behaviour those
tables back: the superuser gate, the role hierarchy when assigning roles, the invitation
lifecycle and the terms gate. See docs/modernisation_plan.md, Part 1 B3 group 6.

F3 (closed in C1): the code wrote ``superuser`` where the schema's ``system_role`` enum says
``superadmin``. ``blueprints/auth/system_roles.py`` now takes its words from
``blueprints/shared/enums.SystemRole``; ``superuser`` is still accepted on read (old JWTs).
"""

from __future__ import annotations

import pytest

import char_factories as F

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
def mail(monkeypatch):
    return F.install_fake_mail(monkeypatch)


@pytest.fixture
def company(app, db):
    """An admin-owned entity plus a superuser who is not a member of it."""
    with app.app_context():
        from models.db import User

        currency = F.seed_currency(db)
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com", first_name="Olive", last_name="Owner")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        superuser = F.make_user(db, "root@test.com", system_role=User.SYSTEM_ROLE_SUPERUSER,
                                first_name="Root", last_name="User")
    return owner, entity, superuser


def add_member(app, db, entity, email, role):
    with app.app_context():
        from models.db import UserEntity

        user = F.make_user(db, email, first_name=email.split("@")[0].title(), last_name="Member")
        db.session.add(UserEntity(user_id=user.id, entity_id=entity.id, role=role, approved=True))
        db.session.commit()
    return user


def profile(client):
    resp = client.get("/minty/api/users/me")
    assert resp.status_code == 200, resp.data[:300]
    return resp.get_json()


# ---- the superuser gate --------------------------------------------------------------------


def test_superuser_reaches_the_admin_pages(company, client):
    owner, entity, superuser = company
    F.login(client, superuser)
    assert client.get("/admin").status_code == 200
    assert client.get("/admin_dashboard").status_code == 200


def test_normal_user_is_bounced_from_the_admin_pages(company, client):
    owner, entity, superuser = company
    F.login(client, owner)
    for url in ("/admin", "/admin_dashboard"):
        resp = client.get(url)
        assert resp.status_code in (302, 403), (url, resp.status_code)
        if resp.status_code == 302:
            assert "/admin" not in resp.headers["Location"]


def test_profile_reports_the_system_role_and_memberships(company, client):
    owner, entity, superuser = company
    F.login(client, owner)

    body = profile(client)

    assert body["status"] == "success"
    assert body["user"]["email"] == "owner@test.com"
    assert body["user"]["system_role"] == "normal"
    assert [m["entity_id"] for m in body["memberships"]] == [entity.id]
    assert body["memberships"][0]["role"] == "admin"

    F.login(client, superuser)
    # the database's word (system_role enum); "superuser" was the code's until C1
    assert profile(client)["user"]["system_role"] == "superadmin"


def test_superuser_can_approve_and_reject_pending_users(company, client, app, db):
    owner, entity, superuser = company
    with app.app_context():
        from models.db import User

        pending = F.make_user(db, "pending@test.com")
        User.query.filter_by(id=pending.id).update({"approved": False})
        db.session.commit()
    F.login(client, superuser)

    resp = client.post(f"/approve_user/{pending.id}")
    assert resp.status_code in (200, 302), resp.data[:300]

    F.login(client, pending)
    assert profile(client)["user"]["approved"] is True

    F.login(client, superuser)
    resp = client.post(f"/reject_user/{pending.id}")
    assert resp.status_code in (200, 302), resp.data[:300]


def test_normal_user_cannot_approve_users(company, client, app, db):
    owner, entity, superuser = company
    with app.app_context():
        pending = F.make_user(db, "pending@test.com")
    F.login(client, owner)
    resp = client.post(f"/approve_user/{pending.id}")
    assert resp.status_code in (302, 403)


# ---- entity roles: the six-level hierarchy ---------------------------------------------------


def test_admin_creates_a_user_into_the_company_with_a_role(company, client):
    owner, entity, superuser = company
    F.login(client, owner)

    resp = client.post("/minty/api/users/create", json={
        "email": "cashier@test.com", "first_name": "Cash", "last_name": "Ier",
        "password": "Password!234", "company_uuid": entity.id, "role": "cashier"})

    assert resp.status_code in (200, 201), resp.data[:300]
    body = resp.get_json()
    assert body["status"] == "success", body
    resp = client.post("/minty/api/users/create", json={
        "email": "cashier@test.com", "first_name": "Cash", "last_name": "Ier",
        "password": "Password!234", "company_uuid": entity.id, "role": "cashier"})
    assert resp.status_code in (400, 409), "creating the same email twice must not succeed"
    assert "already" in resp.get_json()["message"].lower()


def test_a_role_above_your_own_cannot_be_granted(company, client, app, db):
    owner, entity, superuser = company
    manager = add_member(app, db, entity, "manager@test.com", "shop_manager")
    F.login(client, manager)

    resp = client.post("/minty/api/users/create", json={
        "email": "newadmin@test.com", "first_name": "New", "last_name": "Admin",
        "password": "Password!234", "company_uuid": entity.id, "role": "admin"})

    assert resp.status_code == 403, resp.data[:300]
    assert "above" in resp.get_json()["message"].lower()


def test_role_change_moves_a_member_up_and_down_the_hierarchy(company, client, app, db):
    owner, entity, superuser = company
    cashier = add_member(app, db, entity, "cashier@test.com", "cashier")
    F.login(client, owner)

    resp = client.patch(f"/minty/api/users/{cashier.id}/role", json={"entity_id": entity.id, "role": "accountant"})
    assert resp.status_code == 200, resp.data[:300]

    F.login(client, cashier)
    assert profile(client)["memberships"][0]["role"] == "accountant"


def test_the_last_admin_cannot_be_removed(company, client):
    owner, entity, superuser = company
    F.login(client, owner)

    resp = client.delete(f"/minty/api/users/{owner.id}/role", json={"entity_id": entity.id})

    assert resp.status_code in (400, 403, 409), resp.data[:300]
    assert "admin" in resp.get_json()["message"].lower()
    assert profile(client)["memberships"], "the owner is still a member"


def test_removing_a_role_ends_the_membership(company, client, app, db):
    owner, entity, superuser = company
    cashier = add_member(app, db, entity, "cashier@test.com", "cashier")
    F.login(client, owner)

    resp = client.delete(f"/minty/api/users/{cashier.id}/role", json={"entity_id": entity.id})

    assert resp.status_code == 200, resp.data[:300]
    F.login(client, cashier)
    assert profile(client)["memberships"] == []


def test_a_cashier_cannot_change_roles(company, client, app, db):
    owner, entity, superuser = company
    cashier = add_member(app, db, entity, "cashier@test.com", "cashier")
    F.login(client, cashier)
    resp = client.patch(f"/minty/api/users/{owner.id}/role", json={"entity_id": entity.id, "role": "cashier"})
    assert resp.status_code == 403


def test_leave_entity_keeps_the_session_and_returns_to_the_list(company, client):
    owner, entity, superuser = company
    F.login(client, owner)
    resp = client.get("/leave-entity")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/entity")
    assert client.get("/minty/api/users/me").status_code == 200, "leaving a company is not logging out"


# ---- invitations ----------------------------------------------------------------------------


def send_invite(client, entity, email, role, **extra):
    return client.post("/minty/api/invitation/send",
                       json={"entity_id": entity.id, "email": email, "role": role,
                             "first_name": "In", "last_name": "Vited", **extra})


def pending(client, entity):
    resp = client.get(f"/minty/api/invitation/{entity.id}/pending")
    assert resp.status_code == 200, resp.data[:300]
    body = resp.get_json()
    return body if isinstance(body, list) else body.get("invitations") or body.get("pending") or []


def test_invitation_is_listed_as_pending_with_its_role(company, client, mail):
    owner, entity, superuser = company
    F.login(client, owner)

    resp = send_invite(client, entity, "new@test.com", "cashier")

    assert resp.status_code in (200, 201), resp.data[:300]
    assert resp.get_json()["invitation"]["email_sent"] is True
    sent = mail.to("new@test.com")
    assert len(sent) == 1 and "/invitation/accept/" in (sent[0].html or sent[0].body or "")
    rows = pending(client, entity)
    assert [(r["email"], r["role"]) for r in rows] == [("new@test.com", "cashier")]
    assert all(r.get("status", "pending") == "pending" for r in rows)


def test_invitation_accept_link_hands_off_to_the_signup_flow(company, client, app, db):
    owner, entity, superuser = company
    F.login(client, owner)
    send_invite(client, entity, "new@test.com", "cashier")
    with app.app_context():
        from models.db import Invitation

        token = Invitation.query.filter_by(email="new@test.com").first().token

    resp = client.get(f"/invitation/accept/{token}")

    assert resp.status_code == 302, resp.data[:300]
    assert "invite=" in resp.headers["Location"] and "new%40test.com" in resp.headers["Location"] or "new@test.com" in resp.headers["Location"]


def test_cancelled_invitation_disappears_and_its_link_dies(company, client, app, db):
    owner, entity, superuser = company
    F.login(client, owner)
    send_invite(client, entity, "new@test.com", "cashier")
    with app.app_context():
        from models.db import Invitation

        inv = Invitation.query.filter_by(email="new@test.com").first()
        invitation_id, token = inv.id, inv.token

    resp = client.post(f"/minty/api/invitation/{invitation_id}/cancel")

    assert resp.status_code == 200, resp.data[:300]
    assert pending(client, entity) == []
    dead = client.get(f"/invitation/accept/{token}")
    assert dead.status_code in (302, 404)
    if dead.status_code == 302:
        assert "invite=" not in dead.headers["Location"], "a cancelled link must not hand off"


def test_invitation_above_own_rank_is_refused(company, client, app, db):
    owner, entity, superuser = company
    manager = add_member(app, db, entity, "manager@test.com", "shop_manager")
    F.login(client, manager)
    resp = send_invite(client, entity, "boss@test.com", "admin")
    assert resp.status_code == 403, resp.data[:300]


def test_duplicate_pending_invitation_is_refused(company, client):
    owner, entity, superuser = company
    F.login(client, owner)
    assert send_invite(client, entity, "new@test.com", "cashier").status_code in (200, 201)
    resp = send_invite(client, entity, "new@test.com", "cashier")
    assert resp.status_code == 409, resp.data[:300]


def test_resend_is_rate_limited_then_goes_out_again(company, client, app, db, mail, monkeypatch):
    owner, entity, superuser = company
    F.login(client, owner)
    send_invite(client, entity, "new@test.com", "cashier")
    with app.app_context():
        from models.db import Invitation

        invitation_id = Invitation.query.filter_by(email="new@test.com").first().id

    # straight after sending: the 60 s cooldown answers 429 with the wait
    resp = client.post(f"/minty/api/invitation/{invitation_id}/resend")
    assert resp.status_code == 429, resp.data[:300]
    assert resp.get_json()["retry_after"] > 0

    # once the cooldown has passed: one more email, still one pending invitation
    from blueprints.invitation.services import invite as invite_service

    invite_service._LAST_SENT.clear()
    resp = client.post(f"/minty/api/invitation/{invitation_id}/resend")
    assert resp.status_code == 200, resp.data[:300]
    assert len(pending(client, entity)) == 1
    assert len(mail.to("new@test.com")) == 2


# ---- the terms gate -------------------------------------------------------------------------


def test_unconsented_user_is_sent_to_the_terms_page(company, client):
    owner, entity, superuser = company
    F.login(client, owner, accepted_terms=False)

    resp = client.get(f"/entity/{entity.id}")

    # HTML pages bounce to the entity list, which is where the terms modal is shown
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/entity"), resp.headers.get("Location")
    listing = client.get("/entity")
    assert listing.status_code == 200 and "terms" in listing.get_data(as_text=True).lower()
    assert client.get("/legal/accept").status_code == 200
    api = client.get(f"/api/get_draft_totals?entity_id={entity.id}&transaction_date=2026-09-01")
    assert api.status_code == 403 and api.get_json()["code"] == "terms_acceptance_required"


def test_accepting_the_terms_opens_the_app(company, client, app):
    owner, entity, superuser = company
    F.login(client, owner, accepted_terms=False)
    from legal import registry

    resp = client.post("/legal/accept", json={"accepted": True,
                                              "terms_version": registry.current_version(registry.TERMS)})

    assert resp.status_code == 200, resp.data[:300]
    assert client.get(f"/entity/{entity.id}").status_code == 200


def test_terms_must_be_ticked(company, client):
    owner, entity, superuser = company
    F.login(client, owner, accepted_terms=False)
    from legal import registry

    resp = client.post("/legal/accept", json={"accepted": False,
                                              "terms_version": registry.current_version(registry.TERMS)})
    assert resp.status_code == 400
    assert client.get(f"/entity/{entity.id}").status_code == 302


def test_consent_is_recorded_once_per_version(company, client, app, db):
    owner, entity, superuser = company
    F.login(client, owner)  # records consent through the real service
    F.login(client, owner)  # again - idempotent
    with app.app_context():
        from blueprints.legal.services.consent import consents_for_user

        rows = consents_for_user(owner.id)
    assert len(rows) == 1
