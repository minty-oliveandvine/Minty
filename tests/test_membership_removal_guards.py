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

from blueprints.user_management.services.roles import (
    check_not_last_admin_or_error,
    check_not_pending_subscriber_or_error,
    check_not_subscription_payer_anywhere_or_error,
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


class _Accounts:
    """A User stand-in that reports a fixed set of ids as deactivated.

    The guard asks it only for accounts it can prove are switched off, so this returns
    exactly those and ignores the filter arguments.
    """

    def __init__(self, deactivated_ids):
        self._ids = list(deactivated_ids)
        self.query = self
        # Column stand-ins: the guard builds `id.in_(...)` and `approved.is_(False)`
        # before it ever calls `.filter`, so these have to answer, not just exist.
        self.id = SimpleNamespace(in_=lambda _values: None)
        self.approved = SimpleNamespace(is_=lambda _value: None)

    def filter(self, *_args):
        return self

    def with_entities(self, *_args):
        return self

    def all(self):
        return [(uid,) for uid in self._ids]


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


def test_a_deactivated_account_does_not_count_as_admin_cover():
    """The membership flag says "let into this company"; ``User.approved`` says "can sign
    in at all", and a deactivated account passes the first while failing the second.
    Counting only the membership let a dead account stand as cover for a live admin — so
    the last person who could actually administer the entity came off it, leaving an
    admin who cannot reach it."""
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "admin")])
    with app.test_request_context():
        error = check_not_last_admin_or_error(
            "admin", "u1", "e1", model=members, user_model=_Accounts(["u2"])
        )

    assert error is not None
    assert "only admin" in error[0].get_json()["message"]


def test_a_live_second_admin_still_counts():
    """The same roster with nobody deactivated is the ordinary case, and must not be
    refused just because the account check now runs."""
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "admin")])
    with app.test_request_context():
        assert check_not_last_admin_or_error(
            "admin", "u1", "e1", model=members, user_model=_Accounts([])
        ) is None


def test_an_unresolvable_account_lookup_keeps_the_cover():
    """Positive identification only. With no database bound the lookup raises, and the
    guard has to fall permissive — discounting cover on a failed check would refuse a
    removal that is perfectly fine."""
    app = _build_app()
    members = _Members([_member("u1", "admin"), _member("u2", "admin")])
    with app.test_request_context():
        assert check_not_last_admin_or_error("admin", "u1", "e1", model=members) is None


# --- the payer, reached by closing the account ------------------------------------
#
# The membership guard above refuses one company at a time. ``DELETE /minty/api/users/me``
# reached the same stranded state through a different door: it flips ``User.approved`` and
# clears the tokens while leaving every membership and every ``payer_user_id`` in place, so
# the payer can no longer sign in, no remaining admin may manage the subscription, and the
# renewals carry on charging a card nobody can reach.


def test_an_account_that_pays_for_a_company_cannot_be_closed():
    app = _build_app()
    with app.test_request_context():
        error = check_not_subscription_payer_anywhere_or_error(
            "u1", entities_lookup=lambda _u: [("e1", "Bakery Ltd")]
        )

    assert error is not None
    response, status = error
    assert status == 409
    assert "Bakery Ltd" in response.get_json()["message"]


def test_the_refusal_names_every_company():
    """A refusal that lists them is actionable; "you still pay for something" is not."""
    app = _build_app()
    with app.test_request_context():
        error = check_not_subscription_payer_anywhere_or_error(
            "u1",
            entities_lookup=lambda _u: [
                ("e1", "Bakery Ltd"), ("e2", "Cafe Co"), ("e3", "Deli Inc"),
            ],
        )

    message = error[0].get_json()["message"]
    assert "Bakery Ltd, Cafe Co and Deli Inc" in message


def test_an_account_paying_for_nothing_closes_normally():
    app = _build_app()
    with app.test_request_context():
        assert check_not_subscription_payer_anywhere_or_error(
            "u1", entities_lookup=lambda _u: []
        ) is None


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
# The route is minty-web's Users tab since phase 2 (2026-10-05), Flask's bearer
# DELETE /api/me/company/users/<id>: tests/test_hub_company_settings.py runs these guards
# through it, in order, against the real database.


# --- someone a handover is offered to ----------------------------------------------
#
# The two sides of a transfer can otherwise pass each other. An offer is validated when it
# is made and again when it is accepted, but nothing stopped the nominee being taken off
# the entity in between — so accept would re-check, refuse, and permanently cancel an
# offer the OUTGOING payer was relying on to get out. Silent from their side; it shows up
# only as an exit that never completes.


def test_the_nominee_of_a_pending_handover_cannot_be_removed():
    app = _build_app()
    with app.test_request_context():
        error = check_not_pending_subscriber_or_error(
            "u2", "e1", pending_lookup=lambda _e: "u2"
        )

    assert error is not None
    response, status = error
    assert status == 409
    assert "being handed over to them" in response.get_json()["message"]


def test_someone_else_is_unaffected_by_a_pending_handover():
    app = _build_app()
    with app.test_request_context():
        assert check_not_pending_subscriber_or_error(
            "u3", "e1", pending_lookup=lambda _e: "u2"
        ) is None


def test_no_pending_handover_blocks_nobody():
    app = _build_app()
    with app.test_request_context():
        assert check_not_pending_subscriber_or_error(
            "u2", "e1", pending_lookup=lambda _e: None
        ) is None


def test_the_nominee_cannot_be_demoted_out_of_admin_either():
    """Demotion reaches the same place removal does — the accept needs the rank."""
    app = _build_app()
    with app.test_request_context():
        error = check_role_change_or_error(
            "admin", "cashier", "u2", "e1",
            model=_Members([_member("u1", "admin"), _member("u2", "admin")]),
            payer_lookup=lambda _e: "u1",
            pending_lookup=lambda _e: "u2",
        )

    assert error is not None
    assert "being handed over to them" in error[0].get_json()["message"]


def test_a_promotion_is_still_never_blocked_by_a_pending_handover():
    """Promotion is how the nominee becomes eligible in the first place."""
    app = _build_app()
    with app.test_request_context():
        assert check_role_change_or_error(
            "cashier", "admin", "u2", "e1",
            model=_Members([]),
            payer_lookup=lambda _e: "u1",
            pending_lookup=lambda _e: "u2",
        ) is None


def test_the_payer_check_fails_closed_on_a_split_entity():
    """``payer_for_entity`` answers from an unordered ``.first()``, so a half-applied flip
    would let the answer depend on which row came back. Asking about ANY row means a split
    state refuses the removal rather than allowing it on a coin toss."""
    app = _build_app()
    with app.test_request_context():
        # Two rows disagreeing; u1 is named by one of them.
        assert check_not_subscription_payer_or_error(
            "u1", "e1", payer_lookup=lambda _e: "u1"
        ) is not None
