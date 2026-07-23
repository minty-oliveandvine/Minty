"""Tests for contact-sync reconcile safety in ``sync_contacts_if_changed``.

Bug: ``get_contacts_from_xero`` returns ``[]`` on *every* failure path — token
validation failure, non-200 HTTP status, and any exception (see
blueprints/xero/services/integration.py:39-88). The reconcile in
blueprints/entity/services/settings.py:1198-1250 treats an empty list as
"Xero has no contacts", so ``removed_ids`` becomes the entire local contact
set and every row for the entity is hard-deleted via ``db.session.delete``.

There *is* a guard for this at settings.py:1167-1173, but it checks
``xero_contacts is None`` — a value the fetcher never returns. It is dead code.

Blast radius: ``entity_pettycash_settings`` holds FKs into
``xero_contact_sync.id`` (director/cash_sale/discrepancy), so a spurious wipe
also silently unsets a completed onboarding step 6. The nightly job at
settings.py:1312 runs this for every connected entity, so one Xero outage
during that window can wipe contacts estate-wide, unattended.

These tests pin the intended contract:

  * a *failed* fetch must be distinguishable from a *genuinely empty* one, so
    the fetcher must return ``None`` on failure and ``[]`` only on success;
  * a failed fetch must abort the reconcile and write nothing;
  * the sync is insert/update-only — absence from Xero never removes a local
    contact, because absence is ambiguous (archived in Xero, a partial fetch,
    or a Xero-side mistake) and losing contact information is the worse
    outcome. Archived contacts remaining visible is accepted by design.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

def _settings_svc():
    """Resolve the live settings service module.

    Imported at call time rather than at test-module import: conftest's
    ``_clear_cached_modules`` reimports ``blueprints.*`` when the app fixture is
    built, so a top-level import would bind a stale module object.
    """
    import importlib

    return importlib.import_module("blueprints.entity.services.settings")


def _xero_integration():
    """Resolve the live Xero integration module — see ``_settings_svc``."""
    import importlib

    return importlib.import_module("blueprints.xero.services.integration")


ENTITY_ID = "e1"
ORG_ID = "org-123"
TOKEN = "tok"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _Contact:
    """Stand-in for a XeroContactSync row."""

    def __init__(self, xero_contact_id, name, row_id=None):
        self.id = row_id or f"row-{xero_contact_id}"
        self.entity_id = ENTITY_ID
        self.xero_contact_id = xero_contact_id
        self.xero_org_id = ORG_ID
        self.name = name
        self.category = None


class _SessionSpy:
    """Records writes so tests can assert nothing was destroyed."""

    def __init__(self):
        self.deleted = []
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def delete(self, obj):
        self.deleted.append(obj)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def remove(self):
        """Called by the app-context teardown hook (pettycash/core/hooks.py)."""


class _ResponseStub:
    def __init__(self, status_code=200, payload=None, raises=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self._raises = raises

    def json(self):
        if self._raises is not None:
            raise self._raises
        return self._payload


@pytest.fixture
def session_spy(monkeypatch, app):
    """Replace the DB session with a spy that records writes.

    Depends on ``app`` so the patch is applied to the post-reimport module — see
    the note in ``_install_fetch``.
    """
    spy = _SessionSpy()
    monkeypatch.setattr(
        "blueprints.entity.services.settings.db.session", spy, raising=False
    )
    return spy


def _install_db_contacts(monkeypatch, contacts):
    """Point ``XeroContactSync.query.filter_by(...).all()`` at ``contacts``.

    The stand-in is callable as well as queryable: the reconcile constructs
    ``XeroContactSync(...)`` for inserts, so a bare namespace would raise
    "not callable" on any test whose Xero response contains a new contact.
    """
    class _StubModel:
        query = SimpleNamespace(
            filter_by=lambda **_kw: SimpleNamespace(all=lambda: list(contacts))
        )

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr(
        "blueprints.entity.services.settings.XeroContactSync", _StubModel
    )


def _install_fetch(monkeypatch, result):
    """Stub the fetcher imported *inside* sync_contacts_if_changed.

    The import is function-local (settings.py:1152), so it re-resolves through
    sys.modules at call time. Patch by dotted path rather than via a
    module-level ``import ... as`` binding: conftest's ``_clear_cached_modules``
    reimports ``blueprints.*`` when the app fixture is built, so a reference
    captured at test-module import time is a *different* module object than the
    one the service resolves, and patching it would silently do nothing (the
    call would hit the real Xero API).
    """
    def _fake(*_args, **_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "blueprints.xero.services.integration.get_contacts_from_xero", _fake
    )


# ---------------------------------------------------------------------------
# The fetcher's contract: failure must be distinguishable from emptiness
# ---------------------------------------------------------------------------

def test_fetch_returns_none_on_non_200(monkeypatch, app):
    """A 401/429/500 must not look like "Xero has no contacts"."""
    monkeypatch.setattr(
        _xero_integration().requests, "get",
        lambda *a, **kw: _ResponseStub(status_code=401),
    )
    with app.app_context():
        result = _xero_integration().get_contacts_from_xero(
            TOKEN, ORG_ID, token_validated=True
        )
    assert result is None, (
        "non-200 from Xero returned %r; must be None so the reconcile guard "
        "can distinguish API failure from a genuinely empty contact list"
        % (result,)
    )


def test_fetch_returns_none_on_exception(monkeypatch, app):
    """Network/JSON errors must not collapse into an empty list."""
    def _boom(*_a, **_kw):
        raise ConnectionError("network down")

    monkeypatch.setattr(_xero_integration().requests, "get", _boom)
    with app.app_context():
        result = _xero_integration().get_contacts_from_xero(
            TOKEN, ORG_ID, token_validated=True
        )
    assert result is None, (
        "an exception during fetch returned %r; must be None" % (result,)
    )


def test_fetch_returns_none_on_token_validation_failure(monkeypatch, app):
    """The un-validated-token path must also signal failure, not emptiness."""
    monkeypatch.setattr(_xero_integration(), "ensure_valid_token", lambda _u: False)
    with app.app_context():
        result = _xero_integration().get_contacts_from_xero(
            TOKEN, ORG_ID, token_validated=False
        )
    assert result is None, (
        "token validation failure returned %r; must be None" % (result,)
    )


def test_fetch_returns_none_on_partial_pagination_failure(monkeypatch, app):
    """A mid-pagination failure must discard the partial result.

    Page 1 succeeds with a full page, page 2 returns 500. Returning the page-1
    contacts alone would look like a complete, smaller contact list — and the
    reconcile would delete everything from page 2 onward.
    """
    page_one = [
        {"ContactID": f"c{i}", "Name": f"Contact {i}"} for i in range(1000)
    ]
    calls = {"n": 0}

    def _paged(*_a, **_kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _ResponseStub(payload={"Contacts": page_one})
        return _ResponseStub(status_code=500)

    monkeypatch.setattr(_xero_integration().requests, "get", _paged)
    with app.app_context():
        result = _xero_integration().get_contacts_from_xero(
            TOKEN, ORG_ID, token_validated=True
        )
    assert result is None, (
        "partial pagination failure returned %d contacts; a truncated list is "
        "indistinguishable from deletions and must be None"
        % (len(result) if result is not None else -1,)
    )


def test_fetch_returns_empty_list_on_genuine_zero_contacts(monkeypatch, app):
    """The one case that legitimately yields []: Xero says there are none."""
    monkeypatch.setattr(
        _xero_integration().requests, "get",
        lambda *a, **kw: _ResponseStub(payload={"Contacts": []}),
    )
    with app.app_context():
        result = _xero_integration().get_contacts_from_xero(
            TOKEN, ORG_ID, token_validated=True
        )
    assert result == [], (
        "a genuine empty response returned %r; must be [] so a real "
        "zero-contact org is still distinguishable from a failure" % (result,)
    )


# ---------------------------------------------------------------------------
# The reconcile must never destroy on a failed fetch
# ---------------------------------------------------------------------------

def test_failed_fetch_deletes_nothing(monkeypatch, session_spy, app):
    """The original bug, end to end: a failed fetch must not touch the DB."""
    existing = [_Contact("c1", "Alice"), _Contact("c2", "Bob")]
    _install_db_contacts(monkeypatch, existing)
    _install_fetch(monkeypatch, None)

    with app.app_context():
        result = _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.deleted == [], (
        "failed fetch deleted %d contact(s)" % len(session_spy.deleted)
    )
    assert session_spy.commits == 0, "failed fetch must not commit"
    assert result["inserted"] == 0
    assert result["changed"] is False
    assert result["aborted"] is True, "a failed fetch must be reported, not silently read as no-change"


def test_fetch_raising_deletes_nothing(monkeypatch, session_spy, app):
    """Belt and braces: even if the fetcher raises, nothing is destroyed."""
    _install_db_contacts(monkeypatch, [_Contact("c1", "Alice")])
    _install_fetch(monkeypatch, RuntimeError("boom"))

    with app.app_context():
        result = _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.deleted == []
    assert session_spy.commits == 0
    assert result["inserted"] == 0


def test_genuine_empty_response_keeps_contacts(monkeypatch, session_spy, app):
    """Even a *genuine* zero-contact response must not remove anything.

    A real empty org and a silently-degraded one are indistinguishable from
    here, and the sync is insert/update-only, so [] is simply a no-op.
    """
    existing = [_Contact("c1", "Alice")]
    _install_db_contacts(monkeypatch, existing)
    _install_fetch(monkeypatch, [])

    with app.app_context():
        result = _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.deleted == [], "an empty response must not remove contacts"
    assert result["inserted"] == 0
    assert result["updated"] == 0


# ---------------------------------------------------------------------------
# Absence from Xero must never remove a local contact
# ---------------------------------------------------------------------------

def test_contact_missing_from_xero_is_kept(monkeypatch, session_spy, app):
    """Issue 3: archiving in Xero must not destroy the local row.

    The row carries FKs from entity_pettycash_settings (step 6); removing it
    silently unsets completed onboarding. Absence is ambiguous — archived,
    partially fetched, or a Xero-side mistake — so it is never acted on.
    """
    alice, bob = _Contact("c1", "Alice"), _Contact("c2", "Bob")
    _install_db_contacts(monkeypatch, [alice, bob])
    # Bob has been archived in Xero and no longer appears in the response.
    _install_fetch(monkeypatch, [{"ContactID": "c1", "Name": "Alice"}])

    with app.app_context():
        _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.deleted == [], (
        "contact absent from Xero was removed; the row (and any step 6 FK "
        "pointing at it) must survive"
    )


def test_archived_contact_is_kept(monkeypatch, session_spy, app):
    """A contact Xero reports as ARCHIVED stays in the local table."""
    bob = _Contact("c2", "Bob")
    _install_db_contacts(monkeypatch, [_Contact("c1", "Alice"), bob])
    _install_fetch(monkeypatch, [
        {"ContactID": "c1", "Name": "Alice", "ContactStatus": "ACTIVE"},
        {"ContactID": "c2", "Name": "Bob", "ContactStatus": "ARCHIVED"},
    ])

    with app.app_context():
        _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.deleted == []


def test_reappearing_contact_is_not_duplicated(monkeypatch, session_spy, app):
    """A contact that comes back in Xero must not insert a second row.

    Since nothing is ever removed, the original row is still present and the
    diff should treat the contact as already known.
    """
    bob = _Contact("c2", "Bob")
    _install_db_contacts(monkeypatch, [bob])
    _install_fetch(monkeypatch, [
        {"ContactID": "c2", "Name": "Bob", "ContactStatus": "ACTIVE"},
    ])

    with app.app_context():
        result = _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.added == [], "reappearing contact must not be re-inserted"
    assert result["inserted"] == 0


# ---------------------------------------------------------------------------
# Incidental defect found while mapping the sync
# ---------------------------------------------------------------------------

def test_long_name_truncated_to_column_width(monkeypatch, session_spy, app):
    """``name`` is String(150) but both sync paths truncate to 255.

    A 151-255 char name passes ``_trunc`` and then fails at the DB layer. There
    is no try/except around the commit at settings.py:1252, so the exception
    propagates into a daemon thread leaving the transaction unrolled-back.
    """
    _install_db_contacts(monkeypatch, [])
    _install_fetch(monkeypatch, [
        {"ContactID": "c9", "Name": "x" * 200},
    ])

    with app.app_context():
        _settings_svc().sync_contacts_if_changed(ENTITY_ID, TOKEN, ORG_ID)

    assert session_spy.added, "expected the new contact to be inserted"
    assert len(session_spy.added[0].name) <= 150, (
        "name truncated to %d chars but the column is String(150)"
        % len(session_spy.added[0].name)
    )
