"""Removing a membership is destructive, and it ran no checks.

``DELETE /minty/api/users/<id>/role`` deleted the ``user_entity`` row on the strength of
the route permission alone — while ``update_user_role``, which merely CHANGES a role, ran
two guards. Three things could be broken through that gap, and all three are now refused:

  rank        USER_ROLE_DELETE's floor is ACCOUNTANT, so an accountant could delete an
              ADMIN outright — something they cannot do by the weaker route of demoting
              that admin first.
  the payer   the payer lives on the subscription rows, not the membership, so deleting
              the membership strands it: every remaining admin fails
              ``may_manage_subscription`` (a payer exists and is not them) and the payer
              fails ``has_entity_access`` (their membership is gone). Nobody can cancel
              or fix billing while the renewals keep charging.
  last admin  ENTITY_RENAME, ENTITY_DELETE and MODULE_MANAGE all need admin rank, and
              granting the role back needs someone who already outranks it — so an entity
              with no admin cannot be administered OR repaired from the inside.

The guards are pure functions taking their dependencies, so the logic is tested here
without a database; the route tests below pin that they are actually wired in.
"""
from __future__ import annotations

import sys
import types
import uuid
from types import SimpleNamespace

from flask import Flask

sys.modules.setdefault(
    "bcrypt",
    types.SimpleNamespace(hashpw=lambda *_args, **_kwargs: b"", gensalt=lambda: b""),
)

from blueprints.user_management.routes import roles as roles_routes
from blueprints.user_management.services.roles import (
    check_not_last_admin_or_error,
    check_not_subscription_payer_or_error,
    check_role_change_or_error,
)


def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def _member(user_id, role, approved=True):
    return SimpleNamespace(user_id=user_id, role=role, approved=approved)


class _Members:
    """A UserEntity stand-in whose query returns a fixed roster for the entity."""

    def __init__(self, rows):
        self._rows = rows
        self.query = self

    def filter_by(self, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


# --- the payer ------------------------------------------------------------------


def test_the_payer_cannot_be_removed():
    app = _build_app()
    with app.test_request_context():
        error = check_not_subscription_payer_or_error(
            "u1", "e1", payer_lookup=lambda _e: "u1"
        )

    assert error is not None
    response, status = error
    assert status == 409
    assert "pays for this company" in response.get_json()["message"]


def test_someone_who_is_not_the_payer_is_unaffected():
    app = _build_app()
    with app.test_request_context():
        assert check_not_subscription_payer_or_error(
            "u2", "e1", payer_lookup=lambda _e: "u1"
        ) is None


def test_an_entity_with_no_payer_blocks_nobody():
    """Nothing has ever been billed, so there is no card to strand."""
    app = _build_app()
    with app.test_request_context():
        assert check_not_subscription_payer_or_error(
            "u1", "e1", payer_lookup=lambda _e: None
        ) is None


def test_the_payer_check_survives_a_uuid():
    """``payer_for_entity`` can hand back a UUID while the route has a string. Compared
    either way round, or the guard silently never fires."""
    uid = uuid.uuid4()
    app = _build_app()
    with app.test_request_context():
        assert check_not_subscription_payer_or_error(
            str(uid), "e1", payer_lookup=lambda _e: uid
        ) is not None


# --- the last admin -------------------------------------------------------------


def test_the_only_admin_cannot_be_removed():
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "cashier")])
    with app.test_request_context():
        error = check_not_last_admin_or_error("admin", "u1", "e1", model=members)

    assert error is not None
    response, status = error
    assert status == 409
    assert "only admin" in response.get_json()["message"]


def test_one_of_several_admins_can_be_removed():
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "admin")])
    with app.test_request_context():
        assert check_not_last_admin_or_error("admin", "u1", "e1", model=members) is None


def test_an_unapproved_admin_does_not_count_as_cover():
    """An unapproved row is not yet somebody who can act, and every other read of this
    table agrees — so it cannot be what keeps the last real admin removable."""
    app = _build_app()
    members = _Members(
        [_member("u1", "admin"), _member("u2", "admin", approved=False)]
    )
    with app.test_request_context():
        assert check_not_last_admin_or_error("admin", "u1", "e1", model=members) is not None


def test_removing_a_non_admin_is_never_blocked():
    """Guarded on the TARGET's rank before anything is counted. On an entity that has
    somehow already lost its admins, counting alone would refuse to remove a cashier too —
    turning one broken invariant into a frozen user list."""
    app = _build_app()
    members = _Members([_member("u1", "cashier"), _member("u2", "cashier")])
    with app.test_request_context():
        assert check_not_last_admin_or_error("cashier", "u1", "e1", model=members) is None


def test_a_superuser_membership_counts_as_admin_cover():
    """The check is a RANK comparison, not an equality test, so anything at or above
    admin keeps the entity administrable."""
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "super_admin")])
    with app.test_request_context():
        assert check_not_last_admin_or_error("admin", "u1", "e1", model=members) is None


# --- the same two invariants, reached by demotion --------------------------------
#
# A role change lands in every state a removal does, so guarding only the DELETE left it
# bypassable in two moves: demote yourself to cashier, then delete the cashier.


def _change(role_from, role_to, *, payer=None, roster=()):
    app = _build_app()
    with app.test_request_context():
        return check_role_change_or_error(
            role_from, role_to, "u1", "e1",
            model=_Members(list(roster)),
            payer_lookup=lambda _e: payer,
        )


def test_the_subscriber_cannot_be_demoted_out_of_admin():
    """The case this was asked for. An admin who pays, demoting themselves, produces the
    deadlock nothing on the page can express: MODULE_MANAGE now fails for them, and
    may_manage_subscription fails for every other admin."""
    error = _change("admin", "cashier", payer="u1",
                    roster=[_member("u1", "admin"), _member("u2", "admin")])

    assert error is not None
    response, status = error
    assert status == 409
    assert "pays for this company" in response.get_json()["message"]


def test_demoting_the_last_admin_is_refused_like_removing_them(monkeypatch):
    """Closes the two-move bypass: this is the DELETE's guard asked of the role that is
    about to be given up."""
    error = _change("admin", "cashier", roster=[_member("u1", "admin")])

    assert error is not None
    response, status = error
    assert status == 409
    assert "demote the only admin" in response.get_json()["message"]


def test_an_admin_with_cover_who_pays_nothing_may_step_down():
    """Neither invariant is at stake, so the demotion is ordinary work."""
    assert _change("admin", "cashier", payer="u2",
                   roster=[_member("u1", "admin"), _member("u2", "admin")]) is None


def test_a_promotion_is_never_blocked():
    """Promotion is how BOTH broken states are repaired — a payer stuck below admin, and
    an entity short of admins. Guarding it would make them permanent."""
    assert _change("cashier", "admin", payer="u1", roster=[]) is None


def test_a_payer_already_below_admin_is_not_frozen():
    """Already in the broken state. Refusing every role change would trap them there;
    the guard is about LEAVING admin, not about being outside it."""
    assert _change("cashier", "shop_manager", payer="u1",
                   roster=[_member("u2", "admin")]) is None


def test_a_sideways_move_between_admin_ranks_is_allowed():
    """super_admin outranks admin, so no admin cover is lost and nothing is refused."""
    assert _change("super_admin", "admin", payer="u1", roster=[]) is None


# --- wired into the route, in order ---------------------------------------------


def _delete(app, monkeypatch, *, membership, may_manage=True, payer=None, roster=None):
    """Call the unwrapped DELETE handler with its collaborators stubbed."""
    session = SimpleNamespace(
        deleted=[], commit_calls=0,
        delete=lambda item: session.deleted.append(item),
        commit=lambda: setattr(session, "commit_calls", session.commit_calls + 1),
    )

    class FakeUserEntity:
        query = SimpleNamespace(
            filter_by=lambda **_k: SimpleNamespace(
                first=lambda: membership,
                all=lambda: list(roster or []),
            )
        )

    monkeypatch.setattr(roles_routes, "UserEntity", FakeUserEntity)
    monkeypatch.setattr(roles_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        roles_routes, "can_manage_role_assignment_for_entity",
        lambda *_a, **_k: may_manage,
    )
    # The route calls this without a lookup, so it would reach the real store.
    monkeypatch.setattr(
        roles_routes, "check_not_subscription_payer_or_error",
        lambda user_id, entity_id: check_not_subscription_payer_or_error(
            user_id, entity_id, payer_lookup=lambda _e: payer
        ),
    )

    with app.test_request_context(
        "/minty/api/users/target-user/role",
        method="DELETE",
        json={"entity_id": "entity-1"},
    ):
        response, status = roles_routes.delete_user_role.__wrapped__.__wrapped__(
            "target-user"
        )
    return response, status, session


def test_an_accountant_can_no_longer_delete_an_admin(monkeypatch):
    """Gap 1. The route permission's floor is ACCOUNTANT; the rank guard is what stops
    the delete being a cheaper path than the demote they are refused."""
    app = _build_app()
    response, status, session = _delete(
        app, monkeypatch,
        membership=SimpleNamespace(role="admin"),
        may_manage=False,
    )

    assert status == 403
    assert session.deleted == []


def test_the_route_refuses_to_strand_the_payer(monkeypatch):
    app = _build_app()
    response, status, session = _delete(
        app, monkeypatch,
        membership=SimpleNamespace(role="cashier"),
        payer="target-user",
    )

    assert status == 409
    assert "pays for this company" in response.get_json()["message"]
    assert session.deleted == []


def test_the_route_refuses_to_remove_the_last_admin(monkeypatch):
    app = _build_app()
    response, status, session = _delete(
        app, monkeypatch,
        membership=SimpleNamespace(role="admin"),
        roster=[_member("target-user", "admin"), _member("u2", "cashier")],
    )

    assert status == 409
    assert "only admin" in response.get_json()["message"]
    assert session.deleted == []


def test_an_ordinary_removal_still_works(monkeypatch):
    """The guards are exceptions, not a new default: a cashier who is nobody's payer
    still comes off the entity in one call."""
    app = _build_app()
    membership = SimpleNamespace(role="cashier")
    response, status, session = _delete(app, monkeypatch, membership=membership)

    assert status == 200
    assert response.get_json()["status"] == "success"
    assert session.deleted == [membership]
    assert session.commit_calls == 1
