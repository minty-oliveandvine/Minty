"""Tests for the invitation feature.

Covers:
- Creating invitations (service layer)
- Duplicate / already-member guards
- Accepting invitations (pending → accepted, UserEntity created)
- The accept link's email-bound handoff to the onboarding /auth page
- Cancelling invitations
- API route responses (send, list pending, cancel)
- Accept page redirects
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import char_factories as F
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(db, User, email="test@example.com", role="cashier", approved=True):
    from werkzeug.security import generate_password_hash

    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        email=email,
        username=email,
        first_name="Test",
        last_name="User",
        password=generate_password_hash("password123"),
        system_role=User.legacy_role_to_system_role(role),
        approved=approved,
    )
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    user._cached_id = uid
    return user


def _make_entity(db, Entity, name="Test Corp", xero_org_id=None):
    eid = str(uuid.uuid4())
    entity = Entity(
        id=eid,
        name=name,
        # no country / currency: both are FKs to reference rows this test does not seed
        status="disconnected",
        xero_org_id=xero_org_id,
    )
    db.session.add(entity)
    db.session.commit()
    db.session.refresh(entity)
    entity._cached_id = eid
    return entity


# an id that exists nowhere (the columns are uuids since C6, so it must still be one)
NOWHERE = "00000000-0000-4000-8000-00000000dead"


def _id(obj):
    return getattr(obj, "_cached_id", None) or obj.id


def _make_user_entity(db, UserEntity, user_id, entity_id, role="cashier", approved=True):
    ue = UserEntity(
        user_id=user_id,
        entity_id=entity_id,
        role=role,
        approved=approved,
        joined_at=datetime.utcnow(),
    )
    db.session.add(ue)
    db.session.commit()
    return ue


def _login(client, user):
    """Log the user in via the Flask-Login test helper, with the live Terms accepted -
    the terms gate (blueprints/legal) answers 403 on the API and redirects pages until
    then, which is what the 403s these tests used to hit were."""
    uid = getattr(user, "_cached_id", None) or user.id
    from blueprints.legal.services.consent import record_consent
    from models.db import db

    with client.application.app_context():
        record_consent(uid, source="gate")
        db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = uid


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(app):
    from models.db import db
    with app.app_context():

        db.session.expire_on_commit = False
        yield db
        import char_factories

        char_factories.truncate_all(app)  # TRUNCATE ... CASCADE on Postgres


@pytest.fixture
def models(app):
    from models.db import Entity, User, UserEntity
    from blueprints.invitation.models.invitation import Invitation
    return {"User": User, "Entity": Entity, "UserEntity": UserEntity, "Invitation": Invitation}


# ---------------------------------------------------------------------------
# Service-layer tests
# ---------------------------------------------------------------------------

class TestCreateInvitation:
    def test_creates_invitation_successfully(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation

            inv, err = create_invitation(entity.id, "new@test.com", "cashier", inviter.id)

            assert err is None
            assert inv is not None
            assert inv.status == "pending"
            assert inv.email == "new@test.com"
            assert inv.role == "cashier"
            assert inv.token is not None
            assert len(inv.token) > 20

    def test_rejects_duplicate_pending_invitation(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin2@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation

            inv1, err1 = create_invitation(entity.id, "dup@test.com", "cashier", inviter.id)
            assert err1 is None

            inv2, err2 = create_invitation(entity.id, "dup@test.com", "cashier", inviter.id)
            assert inv2 is None
            assert "already pending" in err2.lower()

    def test_rejects_already_approved_member(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            existing = _make_user(db_session, models["User"], email="existing@test.com", role="cashier")
            _make_user_entity(db_session, models["UserEntity"], existing.id, entity.id)
            inviter = _make_user(db_session, models["User"], email="admin3@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation

            inv, err = create_invitation(entity.id, "existing@test.com", "cashier", inviter.id)
            assert inv is None
            assert "already a member" in err.lower()

    def test_rejects_nonexistent_entity(self, app, db_session, models):
        with app.app_context():
            inviter = _make_user(db_session, models["User"], email="admin4@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation

            inv, err = create_invitation(NOWHERE, "x@test.com", "cashier", inviter.id)
            assert inv is None
            assert "entity not found" in err.lower()


class TestAcceptInvitation:
    def test_accept_creates_user_entity_and_marks_accepted(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin5@test.com", role="admin")
            invitee = _make_user(db_session, models["User"], email="invitee@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation, accept_invitation

            inv, _ = create_invitation(entity.id, "invitee@test.com", "shop_manager", inviter.id)

            entity_id, err, hint = accept_invitation(inv.token, invitee.id)

            assert err is None
            assert entity_id == entity.id

            ue = models["UserEntity"].query.filter_by(
                user_id=invitee.id, entity_id=entity.id
            ).first()
            assert ue is not None
            assert ue.role == "shop_manager"
            assert ue.approved is True

            refreshed_inv = models["Invitation"].query.get(inv.id)
            assert refreshed_inv.status == "accepted"
            assert refreshed_inv.accepted_at is not None

    def test_accept_with_xero_connected_returns_dashboard_hint(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"], xero_org_id="xero-123")
            inviter = _make_user(db_session, models["User"], email="admin6@test.com", role="admin")
            invitee = _make_user(db_session, models["User"], email="xero_user@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation, accept_invitation

            inv, _ = create_invitation(entity.id, "xero_user@test.com", "cashier", inviter.id)

            with patch("blueprints.invitation.services.invite._is_user_in_xero_org", return_value=True):
                entity_id, err, hint = accept_invitation(inv.token, invitee.id)

            assert hint == "dashboard"

    def test_accept_wrong_email_rejected(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin8@test.com", role="admin")
            wrong_user = _make_user(db_session, models["User"], email="wrong@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation, accept_invitation

            inv, _ = create_invitation(entity.id, "correct@test.com", "cashier", inviter.id)
            entity_id, err, hint = accept_invitation(inv.token, wrong_user.id)

            assert entity_id is None
            assert "different account" in err.lower()

    def test_accept_is_idempotent_for_same_user(self, app, db_session, models):
        """Re-accepting an already-accepted invite as the SAME user is a no-op
        success (returns the entity), not an error — so a retried handoff or a
        double-click can't strand the invitee with 'already used'."""
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin9@test.com", role="admin")
            invitee = _make_user(db_session, models["User"], email="once@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation, accept_invitation

            inv, _ = create_invitation(entity.id, "once@test.com", "cashier", inviter.id)

            with patch("blueprints.invitation.services.invite._is_user_in_xero_org", return_value=False):
                accept_invitation(inv.token, invitee.id)
                # Second accept by the same user: success, same entity, no dup row.
                entity_id, err, hint = accept_invitation(inv.token, invitee.id)

            assert err is None
            assert entity_id == entity.id
            memberships = models["UserEntity"].query.filter_by(
                user_id=invitee.id, entity_id=entity.id
            ).all()
            assert len(memberships) == 1

    def test_accept_used_token_rejected_for_different_user(self, app, db_session, models):
        """An already-accepted token can't be reused by a DIFFERENT person
        (someone who doesn't own the invited address)."""
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin9b@test.com", role="admin")
            invitee = _make_user(db_session, models["User"], email="taken@test.com", role="cashier")
            interloper = _make_user(db_session, models["User"], email="interloper@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation, accept_invitation

            inv, _ = create_invitation(entity.id, "taken@test.com", "cashier", inviter.id)

            with patch("blueprints.invitation.services.invite._is_user_in_xero_org", return_value=False):
                accept_invitation(inv.token, invitee.id)
                entity_id, err, hint = accept_invitation(inv.token, interloper.id)

            assert entity_id is None
            # Rejected — either as a wrong-email or already-used conflict.
            assert err is not None
            assert (
                "different account" in err.lower()
                or "invalid" in err.lower()
                or "already" in err.lower()
            )


class TestCancelInvitation:
    def test_cancel_pending_invitation(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin10@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation, cancel_invitation

            inv, _ = create_invitation(entity.id, "cancel@test.com", "cashier", inviter.id)
            success, err = cancel_invitation(inv.id)

            assert success is True
            assert err is None
            assert models["Invitation"].query.get(inv.id).status == "revoked"  # invitation_status enum word (C6)

    def test_cancel_nonexistent_invitation(self, app, db_session, models):
        with app.app_context():
            from blueprints.invitation.services.invite import cancel_invitation

            success, err = cancel_invitation(NOWHERE)
            assert success is False
            assert err is not None


class TestResendInvitation:
    def test_resend_rotates_token_and_refreshes_expiry(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin12@test.com", role="admin")

            from blueprints.invitation.services.invite import create_invitation, resend_invitation

            inv, _ = create_invitation(entity.id, "resend@test.com", "cashier", inviter.id)
            old_token = inv.token
            old_expiry = inv.expires_at

            # Fresh invite has no recorded send → resendable now.
            invitation, err, retry_after = resend_invitation(inv.id, actor_id=inviter.id)

            assert err is None
            assert retry_after == 0
            assert invitation.token != old_token  # previous link invalidated
            assert invitation.expires_at >= old_expiry

    def test_resend_blocked_by_cooldown(self, app, db_session, models):
        with app.app_context():
            from blueprints.invitation.services.invite import (
                create_invitation, resend_invitation, _record_sent,
            )

            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin13@test.com", role="admin")

            inv, _ = create_invitation(entity.id, "cooldown@test.com", "cashier", inviter.id)
            # Simulate a just-sent email so the cooldown is active.
            _record_sent(inv.id)

            invitation, err, retry_after = resend_invitation(inv.id, actor_id=inviter.id)

            assert invitation is None
            assert err is not None
            assert retry_after > 0

    def test_resend_nonexistent_invitation(self, app, db_session, models):
        with app.app_context():
            from blueprints.invitation.services.invite import resend_invitation

            invitation, err, retry_after = resend_invitation(NOWHERE)
            assert invitation is None
            assert err is not None
            assert retry_after == 0


class TestGetPendingInvitations:
    def test_returns_only_pending(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="admin11@test.com", role="admin")

            from blueprints.invitation.services.invite import (
                create_invitation, cancel_invitation, get_pending_invitations,
            )

            inv1, _ = create_invitation(entity.id, "a@test.com", "cashier", inviter.id)
            inv2, _ = create_invitation(entity.id, "b@test.com", "cashier", inviter.id)
            cancel_invitation(inv1.id)

            pending = get_pending_invitations(entity.id)
            assert len(pending) == 1
            assert pending[0].email == "b@test.com"


# ---------------------------------------------------------------------------
# Route-layer tests
# ---------------------------------------------------------------------------

class TestInvitationAPI:
    def test_send_invitation_unauthenticated_redirects(self, app, db_session, models):
        with app.test_client() as c:
            resp = c.post("/minty/api/invitation/send", json={
                "entity_id": "x", "email": "x@test.com", "role": "cashier",
            })
            assert resp.status_code in (302, 401)

    def test_send_invitation_returns_201(self, app, db_session, models):
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            admin = _make_user(db_session, models["User"], email="api_admin@test.com", role="admin")
            _make_user_entity(db_session, models["UserEntity"], _id(admin), eid, role="admin")
            _login(c, admin)

            # The name the ROUTE calls: it imports the function, so patching the
            # service module's attribute never reached it (a real send was attempted).
            with patch("blueprints.invitation.routes.api.send_invitation_email", return_value=True):
                resp = c.post("/minty/api/invitation/send", json={
                    "entity_id": eid,
                    "email": "newperson@test.com",
                    "role": "cashier",
                })
            data = resp.get_json()
            assert resp.status_code == 201
            assert data["status"] == "success"
            assert data["invitation"]["email"] == "newperson@test.com"
            assert data["invitation"]["email_sent"] is True
            assert data["invitation"]["status"] == "pending"

    def test_send_duplicate_returns_409(self, app, db_session, models):
        """Pre-create invitation via service, then test duplicate via API."""
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            admin = _make_user(db_session, models["User"], email="api_admin2@test.com", role="admin")
            admin_id = _id(admin)
            _make_user_entity(db_session, models["UserEntity"], admin_id, eid, role="admin")

            from blueprints.invitation.services.invite import create_invitation
            create_invitation(eid, "dup_api@test.com", "cashier", admin_id)

            _login(c, admin)
            # The name the ROUTE calls: it imports the function, so patching the
            # service module's attribute never reached it (a real send was attempted).
            with patch("blueprints.invitation.routes.api.send_invitation_email", return_value=True):
                resp = c.post("/minty/api/invitation/send", json={
                    "entity_id": eid, "email": "dup_api@test.com", "role": "cashier",
                })
            assert resp.status_code == 409

    def test_list_pending_returns_invitations(self, app, db_session, models):
        """Pre-create invitation via service, then list via API."""
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            admin = _make_user(db_session, models["User"], email="api_admin3@test.com", role="admin")
            admin_id = _id(admin)
            _make_user_entity(db_session, models["UserEntity"], admin_id, eid, role="admin")

            from blueprints.invitation.services.invite import create_invitation
            create_invitation(eid, "list1@test.com", "cashier", admin_id)

            _login(c, admin)
            resp = c.get(f"/minty/api/invitation/{eid}/pending")
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["status"] == "success"
            assert len(data["invitations"]) >= 1

    def test_cancel_invitation_via_api(self, app, db_session, models):
        """Pre-create invitation via service, then cancel via API."""
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            admin = _make_user(db_session, models["User"], email="api_admin4@test.com", role="admin")
            admin_id = _id(admin)
            _make_user_entity(db_session, models["UserEntity"], admin_id, eid, role="admin")

            from blueprints.invitation.services.invite import create_invitation
            inv, _ = create_invitation(eid, "cancel_api@test.com", "cashier", admin_id)
            inv_id = inv.id

            _login(c, admin)
            resp = c.post(f"/minty/api/invitation/{inv_id}/cancel")
            data = resp.get_json()
            assert resp.status_code == 200
            assert data["status"] == "success"


class TestAcceptInvitationRoute:
    """The accept LINK itself is covered by TestAcceptInvitationPageEmailBinding (it hands
    off to the onboarding /auth page); what is left here is the not-connected page and a
    bad token."""

    def test_xero_not_connected_page_renders(self, app, db_session, models):
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"], name="PageRenderCorp")
            eid = _id(entity)
            user = _make_user(db_session, models["User"], email="page_render@test.com", role="cashier")
            _login(c, user)

            resp = c.get(f"{F.co(c, eid)}/xero-not-connected")
            assert resp.status_code == 200
            assert b"Xero Access Required" in resp.data
            assert b"PageRenderCorp" in resp.data

    def test_invalid_token_redirects(self, app, db_session, models):
        with app.test_client() as c:
            resp = c.get("/invitation/accept/invalid-token-abc")
            assert resp.status_code == 302


class TestEmailOtpInviteAcceptance:
    """End-to-end: an invited user logging in via the email-OTP flow gets the
    invited entity shared with them. This is the path the onboarding frontend
    drives: POST /auth/email/verify-code with the invite token, then a GET on
    the returned handoff URL where accept_invitation actually runs."""

    def _seed_otp(self, db_session, email, code="123456"):
        from werkzeug.security import generate_password_hash
        from datetime import timedelta
        from blueprints.auth.models.email_otp import EmailOtp

        EmailOtp.query.filter_by(email=email).delete()
        db_session.session.add(
            EmailOtp(
                email=email,
                code_hash=generate_password_hash(code, method="pbkdf2:sha256"),
                # timestamptz since C1: an aware stamp, or Postgres reads the naive
                # one in its session zone and the code has "expired"
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
                attempts=0,
            )
        )
        db_session.session.commit()

    def test_verify_code_with_invite_grants_entity_access(self, app, db_session, models):
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            inviter = _make_user(db_session, models["User"], email="e2e_admin@test.com", role="admin")
            # The invitee already has an account (login action path).
            invitee = _make_user(db_session, models["User"], email="e2e_invitee@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation
            inv, _ = create_invitation(eid, "e2e_invitee@test.com", "shop_manager", _id(inviter))
            token = inv.token

            self._seed_otp(db_session, "e2e_invitee@test.com", "123456")

            # No membership before login.
            assert models["UserEntity"].query.filter_by(
                user_id=_id(invitee), entity_id=eid
            ).first() is None

            resp = c.post("/auth/email/verify-code", json={
                "email": "e2e_invitee@test.com",
                "code": "123456",
                "invite": token,
            })
            data = resp.get_json()
            assert resp.status_code == 200, data
            assert data["status"] == "success"
            redirect_url = data["redirect_url"]

            # Follow the handoff GET — this is where accept_invitation runs.
            with patch("blueprints.invitation.services.invite._is_user_in_xero_org", return_value=False):
                handoff = c.get(redirect_url)
            assert handoff.status_code in (301, 302)

            # The entity is now shared with the invitee, with the invited role.
            ue = models["UserEntity"].query.filter_by(
                user_id=_id(invitee), entity_id=eid
            ).first()
            assert ue is not None, "invite login did not share the entity"
            assert ue.role == "shop_manager"
            assert ue.approved is True

            refreshed = models["Invitation"].query.get(inv.id)
            assert refreshed.status == "accepted"

    def test_verify_code_rejects_invite_for_wrong_email(self, app, db_session, models):
        """A valid OTP for an address that isn't the invited one must NOT mint a
        handoff — it returns an error so the user isn't logged in entity-less."""
        with app.test_client() as c:
            entity = _make_entity(db_session, models["Entity"])
            eid = _id(entity)
            inviter = _make_user(db_session, models["User"], email="e2e_admin2@test.com", role="admin")
            other = _make_user(db_session, models["User"], email="someone_else@test.com", role="cashier")

            from blueprints.invitation.services.invite import create_invitation
            inv, _ = create_invitation(eid, "the_invited@test.com", "cashier", _id(inviter))

            # OTP verified for someone_else, but the invite targets the_invited.
            self._seed_otp(db_session, "someone_else@test.com", "123456")

            resp = c.post("/auth/email/verify-code", json={
                "email": "someone_else@test.com",
                "code": "123456",
                "invite": inv.token,
            })
            data = resp.get_json()
            assert resp.status_code == 400
            assert "different account" in data["message"].lower()
            # And no membership was created.
            assert models["UserEntity"].query.filter_by(
                user_id=_id(other), entity_id=eid
            ).first() is None


class TestInvitationStateTransitions:
    """Verify the pending → accepted state change reflected in UserEntity."""

    def test_user_starts_as_non_member_then_becomes_member(self, app, db_session, models):
        with app.app_context():
            entity = _make_entity(db_session, models["Entity"])
            inviter = _make_user(db_session, models["User"], email="adm_state@test.com", role="admin")
            invitee = _make_user(db_session, models["User"], email="state@test.com", role="cashier")

            ue_before = models["UserEntity"].query.filter_by(
                user_id=invitee.id, entity_id=entity.id
            ).first()
            assert ue_before is None

            from blueprints.invitation.services.invite import create_invitation, accept_invitation
            inv, _ = create_invitation(entity.id, "state@test.com", "shop_manager", inviter.id)
            assert inv.status == "pending"

            with patch("blueprints.invitation.services.invite._is_user_in_xero_org", return_value=False):
                accept_invitation(inv.token, invitee.id)

            ue_after = models["UserEntity"].query.filter_by(
                user_id=invitee.id, entity_id=entity.id
            ).first()
            assert ue_after is not None
            assert ue_after.approved is True
            assert ue_after.role == "shop_manager"

            refreshed = models["Invitation"].query.get(inv.id)
            assert refreshed.status == "accepted"


class TestAcceptInvitationPageEmailBinding:
    """The /invitation/accept/<token> link is email-bound:

      - no session              -> bounce to onboarding /auth (token preserved)
      - matching session        -> bounce to onboarding /auth
      - mismatched session      -> FULL LOGOUT + bounce to /auth as invited email
                                   (never via Xero's end-session: xero_auth uses prompt=login)
      - expired / reused / bad  -> error, no handoff, no logout

    Normalized-email comparison (trim + lowercase) governs the match.
    """

    class _Inv:
        """The invitation's plain values. The request's session teardown detaches the ORM
        row, so reading ``inv.token`` after ``c.get(...)`` used to raise DetachedInstanceError."""

        def __init__(self, row):
            self.id, self.token, self.email = row.id, row.token, row.email

    def _invite(self, db_session, models, invited="invitee@test.com",
                inviter_email="pageadmin@test.com"):
        entity = _make_entity(db_session, models["Entity"])
        inviter = _make_user(
            db_session, models["User"], email=inviter_email, role="admin"
        )
        from blueprints.invitation.services.invite import create_invitation
        inv, err = create_invitation(entity.id, invited, "cashier", inviter.id)
        assert err is None
        return entity, self._Inv(inv)

    def test_no_session_bounces_to_onboarding_auth_with_token(
        self, app, db_session, models
    ):
        with app.test_client() as c:
            _, inv = self._invite(db_session, models)
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)
            loc = resp.headers["Location"]
            assert "/auth" in loc
            assert f"invite={inv.token}" in loc
            assert "email=invitee" in loc  # invited email surfaced for prefill

    def test_matching_session_proceeds_to_handoff(
        self, app, db_session, models
    ):
        with app.test_client() as c:
            _, inv = self._invite(db_session, models)
            invitee = _make_user(
                db_session, models["User"],
                email="invitee@test.com", role="cashier",
            )
            _login(c, invitee)
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)
            loc = resp.headers["Location"]
            # Matching session is NOT logged out: it goes to /auth resume,
            # never to a Xero end-session URL.
            assert "/auth" in loc
            assert "xero.com" not in loc
            assert f"invite={inv.token}" in loc

    def test_matching_session_case_insensitive(self, app, db_session, models):
        """Invited 'MixedCase@Test.com', session 'mixedcase@test.com' -> match."""
        with app.test_client() as c:
            _, inv = self._invite(
                db_session, models, invited="MixedCase@Test.com"
            )
            invitee = _make_user(
                db_session, models["User"],
                email="mixedcase@test.com", role="cashier",
            )
            _login(c, invitee)
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)
            # No logout for a normalized match.
            assert "xero.com" not in resp.headers["Location"]
            assert "/auth" in resp.headers["Location"]

    def test_mismatched_session_logs_out_and_redirects(
        self, app, db_session, models
    ):
        with app.test_client() as c:
            _, inv = self._invite(db_session, models)
            # A different, password-only user is logged in (no Xero id_token,
            # so logout goes straight to /auth, not via Xero end-session).
            wrong = _make_user(
                db_session, models["User"],
                email="wrong@test.com", role="cashier",
            )
            _login(c, wrong)
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)

            # Session was cleared (full logout).
            with c.session_transaction() as sess:
                assert sess.get("_user_id") is None

            loc = resp.headers["Location"]
            assert "/auth" in loc
            assert f"invite={inv.token}" in loc
            assert "email=invitee" in loc  # invited email surfaced

            # Nothing was accepted; invite stays pending.
            refreshed = models["Invitation"].query.get(inv.id)
            assert refreshed.status == "pending"

    def test_expired_token_errors_without_logout(
        self, app, db_session, models
    ):
        from datetime import timedelta
        from models.db import tz
        with app.test_client() as c:
            _, inv = self._invite(db_session, models)
            models["Invitation"].query.get(inv.id).expires_at = datetime.now(tz) - timedelta(days=1)
            db_session.session.commit()

            # Even a mismatched session must NOT be logged out for an invalid
            # token — token validity is checked first.
            wrong = _make_user(
                db_session, models["User"],
                email="someone@test.com", role="cashier",
            )
            _login(c, wrong)
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)
            assert "/auth" not in resp.headers["Location"]  # bounced to home
            # Session preserved (no logout on a bad token).
            with c.session_transaction() as sess:
                assert sess.get("_user_id") is not None
            # Token marked expired, not resurrected.
            refreshed = models["Invitation"].query.get(inv.id)
            assert refreshed.status == "expired"

    def test_already_accepted_token_shows_used_state(
        self, app, db_session, models
    ):
        with app.test_client() as c:
            _, inv = self._invite(db_session, models)
            models["Invitation"].query.get(inv.id).status = "accepted"
            db_session.session.commit()
            resp = c.get(f"/invitation/accept/{inv.token}")
            assert resp.status_code in (301, 302)
            assert "/auth" not in resp.headers["Location"]  # no handoff

    def test_unknown_token_errors(self, app, db_session, models):
        with app.test_client() as c:
            resp = c.get("/invitation/accept/this-token-does-not-exist")
            assert resp.status_code in (301, 302)
            assert "/auth" not in resp.headers["Location"]
