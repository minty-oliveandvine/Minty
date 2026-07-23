"""Tests for the "one Xero org = one entity" conflict guard.

Covers ``_conflict_still_live_on_xero`` (the live-check that decides whether a
matching ``xero_org_id`` row is a REAL conflict to block, or a stale ghost to
reconcile and allow) plus the connect-callback guard that uses it.

Scenarios exercised:

Core helper (``_conflict_still_live_on_xero``):
  1. No xero_org_id on the conflict row            -> not a conflict (allow)
  2. Conflict entity still live on Xero            -> real conflict (block)
  3. Conflict entity's token is dead / no connector-> ghost (reconcile, allow)
  4. Conflict entity's tenant gone from Xero       -> ghost (reconcile, allow)
  5. Xero /connections returns non-200             -> ghost (reconcile, allow)
  6. Xero /connections raises                       -> ghost (reconcile, allow)
  7. Same-org re-authorization (the reported bug):
       fresh_connections contains the tenant but the other entity's own token
       is dead -> ghost (reconcile, allow) — proves we do NOT use
       fresh_connections to decide, so re-authorizing the same org for a new
       entity no longer falsely blocks.

Connect callback guard (end-to-end through ``xero_callback``):
  8. Real live conflict on a DIFFERENT entity      -> blocked, no write
  9. Ghost conflict (dead token) on another entity -> allowed, entity connects
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from flask import Flask

from blueprints.xero.routes import routes as xero_routes


# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------

def _build_app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    return app


def _make_entity(entity_id, *, xero_org_id=None, name="Entity", status="connected"):
    return SimpleNamespace(
        id=entity_id,
        name=name,
        xero_org_id=xero_org_id,
        xero_tenant_name=None,
        status=status,
        last_connected_at=None,
        connected_by_user_id="conn-user" if xero_org_id else None,
    )


class _SessionStub:
    def __init__(self):
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1


def _connections_resp(tenant_ids, status_code=200, raises=False):
    """Build a stub `requests` module whose .get returns the given tenants."""
    def _get(*_a, **_kw):
        if raises:
            raise RuntimeError("xero unreachable")
        return SimpleNamespace(
            status_code=status_code,
            json=lambda: [{"tenantId": t, "tenantName": "Org"} for t in tenant_ids],
        )

    return SimpleNamespace(get=_get)


# ===========================================================================
# _revoke_new_grant — hand back the grant when a connect is blocked
#
# By the time the guard blocks, the OAuth exchange has already completed, so a
# live grant exists on Xero. Without revoking it the user stays connected on
# Xero while our UI says they are not, and Xero's Connected apps page collects
# duplicate "Minty" entries.
# ===========================================================================

def _delete_recorder(status_code=204, raises=False):
    """Stub `requests` capturing DELETE calls made to Xero."""
    calls = []

    def _delete(url, **kwargs):
        calls.append({"url": url, "headers": kwargs.get("headers", {})})
        if raises:
            raise RuntimeError("xero unreachable")
        return SimpleNamespace(status_code=status_code)

    return SimpleNamespace(delete=_delete), calls


CONNECTIONS = [
    {"id": "conn-abc", "tenantId": "tenant-X", "tenantName": "Org X"},
    {"id": "conn-def", "tenantId": "tenant-Y", "tenantName": "Org Y"},
]


def test_revoke_deletes_the_matching_connection(monkeypatch):
    """The grant just created for this tenant is handed back to Xero, using the
    connection *id* (not the tenantId) and the fresh access token."""
    app = _build_app()
    stub, calls = _delete_recorder()
    monkeypatch.setattr(xero_routes, "requests", stub)

    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", CONNECTIONS, "tenant-X")

    assert len(calls) == 1, "exactly one connection should be revoked"
    assert calls[0]["url"].endswith("/connections/conn-abc"), (
        "must DELETE by connection id, not tenantId"
    )
    assert calls[0]["headers"]["Authorization"] == "Bearer fresh-token"


def test_revoke_picks_the_right_tenant(monkeypatch):
    """With several connections in the auth event, only the blocked tenant's
    grant is revoked — the user's other orgs must keep working."""
    app = _build_app()
    stub, calls = _delete_recorder()
    monkeypatch.setattr(xero_routes, "requests", stub)

    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", CONNECTIONS, "tenant-Y")

    assert len(calls) == 1
    assert calls[0]["url"].endswith("/connections/conn-def")


def test_revoke_no_matching_connection_is_a_noop(monkeypatch):
    """No connection id for the tenant -> nothing to revoke, and no crash."""
    app = _build_app()
    stub, calls = _delete_recorder()
    monkeypatch.setattr(xero_routes, "requests", stub)

    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", CONNECTIONS, "tenant-NOPE")

    assert calls == []


def test_revoke_failure_never_raises(monkeypatch):
    """Revoking is best-effort: a Xero error must not turn a clean block into a
    500. The block still has to complete."""
    app = _build_app()
    stub, _ = _delete_recorder(raises=True)
    monkeypatch.setattr(xero_routes, "requests", stub)

    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", CONNECTIONS, "tenant-X")
    # reaching here without an exception is the assertion

    stub2, _ = _delete_recorder(status_code=500)
    monkeypatch.setattr(xero_routes, "requests", stub2)
    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", CONNECTIONS, "tenant-X")


def test_revoke_handles_empty_connections(monkeypatch):
    """Defensive: empty/None payload must not blow up."""
    app = _build_app()
    stub, calls = _delete_recorder()
    monkeypatch.setattr(xero_routes, "requests", stub)

    with app.app_context():
        xero_routes._revoke_new_grant("fresh-token", [], "tenant-X")
        xero_routes._revoke_new_grant("fresh-token", None, "tenant-X")

    assert calls == []


# ===========================================================================
# Core helper: _conflict_still_live_on_xero
# ===========================================================================

def test_no_xero_org_id_is_not_a_conflict(monkeypatch):
    """A conflict row with no xero_org_id can never be a real conflict."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id=None)
    session = _SessionStub()
    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is False
    assert session.commit_calls == 0  # nothing to reconcile


def test_conflict_still_live_blocks(monkeypatch):
    """Conflict entity's own token is valid AND its tenant is still on Xero ->
    a real, live conflict. Must return True (block) and NOT reconcile."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id="tenant-X", name="Alpha")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is True, "still-connected entity must be a real conflict"
    assert conflict.xero_org_id == "tenant-X", "must not reconcile a live entity"
    assert session.commit_calls == 0


def test_dead_token_is_ghost_and_allows(monkeypatch):
    """Conflict entity has no usable connector token (dead after a Xero-website
    disconnect) -> treat as revoked ghost: reconcile and allow (return False)."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id="tenant-X", name="Alpha")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity", lambda *_a, **_kw: None,
    )

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is False, "dead token must be treated as a ghost (allow)"
    assert conflict.xero_org_id is None, "ghost must be reconciled"
    assert conflict.status == "disconnected"
    assert conflict.connected_by_user_id is None
    assert session.commit_calls == 1


def test_tenant_gone_from_xero_is_ghost(monkeypatch):
    """Token is valid but the tenant is no longer in Xero's /connections ->
    revoked. Reconcile and allow."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id="tenant-X", name="Alpha")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    # Xero returns a DIFFERENT tenant — tenant-X is gone.
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-OTHER"]))

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is False
    assert conflict.xero_org_id is None
    assert session.commit_calls == 1


def test_non_200_from_xero_is_ghost(monkeypatch):
    """A non-200 from Xero can't confirm the conflict -> treat as ghost/allow
    (the chosen 'dead token = ghost' policy)."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id="tenant-X", name="Alpha")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(
        xero_routes, "requests", _connections_resp([], status_code=401),
    )

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is False
    assert conflict.xero_org_id is None
    assert session.commit_calls == 1


def test_xero_request_raises_is_ghost(monkeypatch):
    """Network error reaching Xero -> ghost/allow under the chosen policy."""
    app = _build_app()
    conflict = _make_entity("e-a", xero_org_id="tenant-X", name="Alpha")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp([], raises=True))

    with app.app_context():
        result = xero_routes._conflict_still_live_on_xero(conflict)

    assert result is False
    assert conflict.xero_org_id is None
    assert session.commit_calls == 1


def test_same_org_reauth_does_not_falsely_block(monkeypatch):
    """THE REPORTED BUG: one Xero org, user disconnects it on Xero's website,
    then connects a DIFFERENT entity to the SAME org.

    fresh_connections contains the tenant (because the user just re-authorized
    that same org for the new entity), but the OTHER entity's own token is dead.
    The guard must NOT use fresh_connections to conclude 'still connected' — it
    must verify via the other entity's own token, find it dead, and allow.
    """
    app = _build_app()
    conflict = _make_entity("e-old", xero_org_id="tenant-X", name="OldEntity")
    session = _SessionStub()

    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    # Old entity's token is dead (typical after a manual Xero-website disconnect).
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity", lambda *_a, **_kw: None,
    )

    with app.app_context():
        # fresh_connections DOES contain tenant-X (just re-authorized for the
        # new entity) — the old, buggy behaviour would treat this as a live
        # conflict and block. It must not.
        result = xero_routes._conflict_still_live_on_xero(
            conflict, fresh_connections=[{"tenantId": "tenant-X"}],
        )

    assert result is False, (
        "re-authorizing the same org for a new entity must not be blocked by "
        "the old entity's stale row"
    )
    assert conflict.xero_org_id is None, "old entity's ghost row must be cleared"
    assert session.commit_calls == 1


# ===========================================================================
# _live_org_claimant — the "who really holds this org?" lookup
#
# These cover the two states found in the real (already-populated) database:
#   * every row with an xero_org_id was ALSO status="disconnected"
#   * three orgs were claimed by TWO entities each (pre-guard duplicates)
# ===========================================================================

def _patch_claimants(monkeypatch, claimants, session):
    """Point Entity.query.filter(...).all() at a fixed claimant list."""
    class _Result:
        def all(self):
            return claimants

        def first(self):
            return claimants[0] if claimants else None

    class _Query:
        def filter(self, *_a):
            return _Result()

    class _FakeEntity:
        query = _Query()
        id = object()
        xero_org_id = object()

    monkeypatch.setattr(xero_routes, "Entity", _FakeEntity)
    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))


def test_disconnected_claimant_never_blocks(monkeypatch):
    """A row marked status="disconnected" that still holds an xero_org_id must
    NOT block a connect, even when its connector's token can still see the org
    on Xero (the user keeps Xero access after disconnecting in our UI).

    This is the state EVERY populated row was in, and it is why real users hit
    "already connected to another entity" on a legitimate connect.
    """
    app = _build_app()
    session = _SessionStub()
    ghost = _make_entity(
        "e-old", xero_org_id="tenant-X", name="HYBE", status="disconnected",
    )
    _patch_claimants(monkeypatch, [ghost], session)
    # Token is alive and Xero still lists the org — the old guard blocked here.
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant("tenant-X", "e-new")

    assert result is None, "a disconnected row must never block a connect"
    assert ghost.xero_org_id is None, "its stale claim must be cleared"
    assert session.commit_calls == 1


def test_all_duplicate_claimants_are_examined(monkeypatch):
    """An org can already be claimed by MORE than one entity (the pre-guard
    duplicates). Checking only the first row would let the second block the
    next attempt, so every claimant must be reconciled/considered."""
    app = _build_app()
    session = _SessionStub()
    first = _make_entity(
        "e-1", xero_org_id="tenant-X", name="231321", status="disconnected",
    )
    second = _make_entity(
        "e-2", xero_org_id="tenant-X", name="HYBE", status="disconnected",
    )
    _patch_claimants(monkeypatch, [first, second], session)

    with app.app_context():
        result = xero_routes._live_org_claimant("tenant-X", "e-new")

    assert result is None
    assert first.xero_org_id is None, "first duplicate must be cleared"
    assert second.xero_org_id is None, (
        "second duplicate must ALSO be cleared — otherwise it blocks the next "
        "connect attempt"
    )
    assert session.commit_calls == 2


def test_live_connected_claimant_still_blocks(monkeypatch):
    """The rule still holds: an entity that is genuinely connected (status is
    not 'disconnected' and Xero confirms the org) blocks the connect."""
    app = _build_app()
    session = _SessionStub()
    live = _make_entity(
        "e-live", xero_org_id="tenant-X", name="RealCo", status="connected",
    )
    _patch_claimants(monkeypatch, [live], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant("tenant-X", "e-new")

    assert result is live, "a genuinely connected entity must block"
    assert live.xero_org_id == "tenant-X", "a live claim must not be cleared"


# ===========================================================================
# Same-user claims: the shared-token blind spot
#
# Tokens live in ``user_token``, ONE ROW PER USER — not per entity. So a
# claimant's "own" token (resolved via its connected_by_user_id) is the very
# same token row as the user connecting now. Re-authorizing the org revives it,
# which makes the live probe answer "org present" for ANY org the user just
# authorized — it cannot tell a live claim from a dead one. These tests pin the
# behaviour that falls out of that: a same-user claim is unlinked, not blocked.
# ===========================================================================

def test_same_user_live_claimant_is_unlinked_not_blocked(monkeypatch):
    """THE REPORTED BUG: connect entity A, revoke Minty from inside the Xero
    website, then connect entity B to the same org.

    A still reads status="connected" (a website-side revoke never reaches us)
    and A's connector is the same user connecting now. The shared token is alive
    and Xero lists the org, so the probe would "confirm" a conflict and block B
    forever. Since the probe cannot answer here, defer to the user's intent:
    release A's claim and let B through.
    """
    app = _build_app()
    session = _SessionStub()
    entity_a = _make_entity(
        "e-a", xero_org_id="tenant-X", name="Alpha", status="connected",
    )
    entity_a.connected_by_user_id = "me"
    _patch_claimants(monkeypatch, [entity_a], session)
    # Exactly the state that makes the probe lie: token alive, org listed.
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="revived-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-b", connecting_user_id="me",
        )

    assert result is None, (
        "re-linking your own org to another entity must not be blocked by an "
        "unverifiable same-user claim"
    )
    assert entity_a.xero_org_id is None, "entity A's claim must be released"
    assert entity_a.status == "disconnected"
    assert entity_a.connected_by_user_id is None
    assert session.commit_calls == 1


def test_same_user_claim_does_not_probe_xero(monkeypatch):
    """The same-user case must not consult Xero at all.

    Reaching for the probe is what produced the false block, so this asserts the
    branch short-circuits BEFORE any token/network work rather than merely
    ignoring the answer.
    """
    app = _build_app()
    session = _SessionStub()
    entity_a = _make_entity(
        "e-a", xero_org_id="tenant-X", name="Alpha", status="connected",
    )
    entity_a.connected_by_user_id = "me"
    _patch_claimants(monkeypatch, [entity_a], session)

    def _boom(*_a, **_kw):
        raise AssertionError("must not probe Xero for a same-user claim")

    monkeypatch.setattr(xero_routes, "get_xero_token_user_for_entity", _boom)
    monkeypatch.setattr(
        xero_routes, "requests",
        SimpleNamespace(get=_boom, delete=_boom),
    )

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-b", connecting_user_id="me",
        )

    assert result is None


def test_other_user_live_claim_still_blocks(monkeypatch):
    """The rule is still enforced where it CAN be: a live claim held by another
    user blocks. Their token is independent of this auth event, so the probe is
    a real answer — this is the case 'one org = one entity' exists to protect.
    """
    app = _build_app()
    session = _SessionStub()
    theirs = _make_entity(
        "e-them", xero_org_id="tenant-X", name="TheirCo", status="connected",
    )
    theirs.connected_by_user_id = "other-user"
    _patch_claimants(monkeypatch, [theirs], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="their-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-mine", connecting_user_id="me",
        )

    assert result is theirs, "another user's live claim must still block"
    assert theirs.xero_org_id == "tenant-X", "their live claim must not be cleared"


def test_other_user_dead_claim_still_allows(monkeypatch):
    """A claim held by another user whose token is dead stays a ghost: probe,
    find nothing, reconcile, allow. The same-user branch must not have changed
    this path."""
    app = _build_app()
    session = _SessionStub()
    theirs = _make_entity(
        "e-them", xero_org_id="tenant-X", name="TheirCo", status="connected",
    )
    theirs.connected_by_user_id = "other-user"
    _patch_claimants(monkeypatch, [theirs], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity", lambda *_a, **_kw: None,
    )

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-mine", connecting_user_id="me",
        )

    assert result is None
    assert theirs.xero_org_id is None, "a dead claim must be reconciled"


def test_unknown_connecting_user_falls_back_to_probe(monkeypatch):
    """Without a connecting_user_id we cannot prove a claim is the same user's,
    so fall back to the live probe rather than unlinking on a guess."""
    app = _build_app()
    session = _SessionStub()
    live = _make_entity(
        "e-live", xero_org_id="tenant-X", name="RealCo", status="connected",
    )
    live.connected_by_user_id = "someone"
    _patch_claimants(monkeypatch, [live], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant("tenant-X", "e-new")

    assert result is live, "no connecting_user_id -> keep the old probe path"


def test_claimant_with_no_connector_is_probed_not_unlinked(monkeypatch):
    """connected_by_user_id is NULL: that is not 'the same user', so it must not
    take the same-user branch. It falls through to the probe, which finds no
    usable token and reconciles it as a ghost."""
    app = _build_app()
    session = _SessionStub()
    orphan = _make_entity(
        "e-orphan", xero_org_id="tenant-X", name="Orphan", status="connected",
    )
    orphan.connected_by_user_id = None
    _patch_claimants(monkeypatch, [orphan], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity", lambda *_a, **_kw: None,
    )

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-new", connecting_user_id="me",
        )

    assert result is None
    assert orphan.xero_org_id is None


def test_mixed_claimants_other_user_wins(monkeypatch):
    """Duplicates where one claimant is the user's own and another is a live
    claim by someone else: the same-user row is released, but the other user's
    live claim still blocks. Order matters — the block must survive the earlier
    unlink."""
    app = _build_app()
    session = _SessionStub()
    mine = _make_entity(
        "e-mine-old", xero_org_id="tenant-X", name="MyOld", status="connected",
    )
    mine.connected_by_user_id = "me"
    theirs = _make_entity(
        "e-them", xero_org_id="tenant-X", name="TheirCo", status="connected",
    )
    theirs.connected_by_user_id = "other-user"
    _patch_claimants(monkeypatch, [mine, theirs], session)
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="their-token"),
    )
    monkeypatch.setattr(xero_routes, "requests", _connections_resp(["tenant-X"]))

    with app.app_context():
        result = xero_routes._live_org_claimant(
            "tenant-X", "e-new", connecting_user_id="me",
        )

    assert result is theirs, "another user's live claim must still block"
    assert mine.xero_org_id is None, "the user's own stale row is still released"


def test_no_claimants_means_org_is_free(monkeypatch):
    """No other entity holds the org -> nothing to block."""
    app = _build_app()
    session = _SessionStub()
    _patch_claimants(monkeypatch, [], session)

    with app.app_context():
        result = xero_routes._live_org_claimant("tenant-FREE", "e-new")

    assert result is None
    assert session.commit_calls == 0


# ===========================================================================
# End-to-end: the connect callback guard
# ===========================================================================

def _patch_callback_common(monkeypatch, *, user, entities_by_id, session,
                           connect_tenant, conflict_entity):
    """Patch the connect callback dependencies. The Entity query returns the
    target entity by id and the conflict entity for the conflict filter."""

    target_entity = entities_by_id["entity-new"]

    class _EntityFilterResult:
        def first(self):
            return conflict_entity

        def all(self):
            return [conflict_entity] if conflict_entity is not None else []

    class _EntityQuery:
        def get(self, entity_id):
            return entities_by_id.get(entity_id)

        def filter(self, *_args):
            # Used for the conflict lookup in the guard.
            return _EntityFilterResult()

        def order_by(self, *_a):
            return SimpleNamespace(first=lambda: None)

    class _FakeEntity:
        query = _EntityQuery()
        id = object()
        xero_org_id = object()

    class _UserQuery:
        def filter(self, *_a):
            return SimpleNamespace(first=lambda: user)

        def get(self, *_a):
            return user

    class _FakeUser:
        query = _UserQuery()
        username = object()

    monkeypatch.setattr(xero_routes, "Entity", _FakeEntity)
    monkeypatch.setattr(xero_routes, "User", _FakeUser)
    monkeypatch.setattr(xero_routes, "db", SimpleNamespace(session=session))
    monkeypatch.setattr(xero_routes, "desc", lambda v: v)
    monkeypatch.setattr(
        xero_routes, "get_auth_token",
        lambda *_a, **_kw: {
            "access_token": "access-token", "id_token": "id-token",
            "refresh_token": "refresh-token", "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        xero_routes, "decode_jwt",
        lambda token: (
            {"preferred_username": "u@example.com"} if token == "id-token"
            else {"authentication_event_id": "auth-event"}
        ),
    )
    monkeypatch.setattr(xero_routes, "normalize_email", lambda e: e)
    monkeypatch.setattr(xero_routes, "resolve_user_by_email", lambda *_a, **_kw: user)
    monkeypatch.setattr(xero_routes, "_connect_initiator_mismatch", lambda *_a, **_kw: None)
    monkeypatch.setattr(xero_routes, "_resolve_connect_entity", lambda *_a, **_kw: target_entity)
    # The callback's /connections fetch for the NEW auth event returns the org
    # being connected now.
    monkeypatch.setattr(
        xero_routes, "requests",
        _connections_resp([connect_tenant]),
    )
    monkeypatch.setattr(xero_routes, "threading",
                        SimpleNamespace(Thread=lambda *a, **k: SimpleNamespace(
                            start=lambda: None, is_alive=lambda: True)))
    monkeypatch.setattr(xero_routes, "time", SimpleNamespace(sleep=lambda *_a, **_k: None))
    monkeypatch.setattr(xero_routes, "sync_all_accounts_and_contacts_background", lambda *_a, **_k: None)
    monkeypatch.setattr(xero_routes, "login_user", lambda *_a, **_k: None)
    monkeypatch.setattr(xero_routes, "flash", lambda *_a, **_k: None)
    monkeypatch.setattr(xero_routes, "url_for", lambda endpoint, **_k: f"/{endpoint}")
    monkeypatch.setattr(xero_routes, "redirect",
                        lambda loc: SimpleNamespace(status_code=302, location=loc))
    monkeypatch.setattr(xero_routes, "upsert_user_token", lambda *_a, **_k: None)
    monkeypatch.setattr(xero_routes, "current_user", SimpleNamespace(username="u@example.com"))


def test_callback_blocks_real_live_conflict(monkeypatch):
    """Connecting entity-new to tenant-X while a DIFFERENT entity is genuinely
    still connected to tenant-X must be blocked without writing the org."""
    app = _build_app()
    session = _SessionStub()

    user = _make_entity  # placeholder; build a real user below
    user = SimpleNamespace(id="u1", username="u@example.com", xero_entity_id=None)
    entity_new = _make_entity("entity-new", xero_org_id=None, status="onboarding")
    conflict = _make_entity("entity-old", xero_org_id="tenant-X", name="OldCo")

    _patch_callback_common(
        monkeypatch, user=user,
        entities_by_id={"entity-new": entity_new},
        session=session, connect_tenant="tenant-X", conflict_entity=conflict,
    )
    # The conflict entity is LIVE: its own token is valid and Xero still lists it.
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity",
        lambda *_a, **_kw: SimpleNamespace(access_token="live-token"),
    )

    with app.test_request_context("/callback?state=entity_connect:entity-new&code=c"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity_new.xero_org_id is None, "blocked connect must not write the org"
    assert conflict.xero_org_id == "tenant-X", "live conflict must be untouched"


def test_callback_allows_ghost_conflict(monkeypatch):
    """Connecting entity-new to tenant-X when the other entity's grant is a dead
    ghost must be allowed: entity-new gets the org, the ghost is reconciled."""
    app = _build_app()
    session = _SessionStub()

    user = SimpleNamespace(id="u1", username="u@example.com", xero_entity_id=None)
    entity_new = _make_entity("entity-new", xero_org_id=None, status="onboarding")
    conflict = _make_entity("entity-old", xero_org_id="tenant-X", name="OldCo")

    _patch_callback_common(
        monkeypatch, user=user,
        entities_by_id={"entity-new": entity_new},
        session=session, connect_tenant="tenant-X", conflict_entity=conflict,
    )
    # The conflict entity's token is DEAD -> ghost.
    monkeypatch.setattr(
        xero_routes, "get_xero_token_user_for_entity", lambda *_a, **_kw: None,
    )

    with app.test_request_context("/callback?state=entity_connect:entity-new&code=c"):
        response = xero_routes.xero_callback()

    assert response.status_code == 302
    assert entity_new.xero_org_id == "tenant-X", (
        "ghost conflict must not block: the new entity should connect"
    )
    assert conflict.xero_org_id is None, "the ghost row must be reconciled"
    assert conflict.status == "disconnected"
