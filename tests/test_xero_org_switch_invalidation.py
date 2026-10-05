"""Tests for invalidate_entity_xero_cache.

When an entity is reconnected to a DIFFERENT Xero organisation, every cached
Xero id it holds becomes meaningless: contact ids, account ids and the account
mappings that point at them are all tenant-scoped. Leaving them behind makes
publishing target contacts and accounts that do not exist in the new org.

These cover the helper itself, plus a guard that all three org-write sites
(connect, reconnect, disconnect in blueprints/xero/routes/routes.py) still
call it: the helper no-ops on a falsy old org, so a dropped call would leave
stale ids behind without any error.
"""

from __future__ import annotations

import pytest

import uuid

# uuid columns since phase C; stable so the assertions can name them
def _uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"org-switch-{label}"))


ENTITY_ID = _uid("entity-001")
CONTACT_A, CONTACT_B, ACCOUNT_A = _uid("contact-a"), _uid("contact-b"), _uid("account-a")
ORG_A = "xero-org-OLD"
ORG_B = "xero-org-NEW"


@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


@pytest.fixture
def seeded(db_session):
    """An entity on org A with contacts, accounts and mappings for org A."""
    from models.db import (AccountInfo, Entity, EntityPettycashSettings,
                           XeroContactSync)

    db = db_session
    entity = Entity(
        id=ENTITY_ID,
        name="Switching Entity",
        xero_org_id=ORG_A,
        status="connected",
    )
    db.session.add(entity)

    contact_a = XeroContactSync(
        id=CONTACT_A,
        entity_id=ENTITY_ID,
        xero_contact_id="xero-contact-a",
        xero_org_id=ORG_A,
        name="Acme (old org)",
    )
    contact_b = XeroContactSync(
        id=CONTACT_B,
        entity_id=ENTITY_ID,
        xero_contact_id="xero-contact-b",
        xero_org_id=ORG_B,
        name="Acme (new org)",
    )
    account_a = AccountInfo(
        id=ACCOUNT_A,
        entity_id=ENTITY_ID,
        type="pettycash",
        name="Petty Cash",
        xero_account_id="xero-account-a",
        xero_code="090",
    )
    db.session.add_all([contact_a, contact_b, account_a])
    db.session.flush()

    db.session.add(
        EntityPettycashSettings(
            entity_id=ENTITY_ID,
            pettycash_account_id=ACCOUNT_A,
            cash_sale_contact_id=CONTACT_A,
        )
    )
    db.session.commit()
    return db


def _invalidate(*args, **kwargs):
    # Imported inside the test: conftest clears blueprints.* from sys.modules,
    # so a module-level import here would bind a stale object.
    from blueprints.entity.services.settings import invalidate_entity_xero_cache

    return invalidate_entity_xero_cache(*args, **kwargs)


class TestInvalidateEntityXeroCache:
    def test_removes_old_org_contacts_only(self, seeded):
        from models.db import XeroContactSync

        _invalidate(ENTITY_ID, ORG_A)
        seeded.session.commit()

        remaining = XeroContactSync.query.filter_by(entity_id=ENTITY_ID).all()
        assert [row.xero_org_id for row in remaining] == [ORG_B], (
            "a row already written for the incoming org must survive"
        )

    def test_removes_all_account_rows(self, seeded):
        from models.db import AccountInfo

        _invalidate(ENTITY_ID, ORG_A)
        seeded.session.commit()

        assert AccountInfo.query.filter_by(entity_id=ENTITY_ID).count() == 0

    def test_clears_account_and_contact_mappings(self, seeded):
        from models.db import EntityPettycashSettings

        _invalidate(ENTITY_ID, ORG_A)
        seeded.session.commit()

        row = EntityPettycashSettings.query.filter_by(entity_id=ENTITY_ID).first()
        assert row is not None, "the settings row itself must not be deleted"
        assert row.pettycash_account_id is None
        assert row.cash_sale_contact_id is None

    def test_noop_without_an_old_org(self, seeded):
        """First connect has nothing cached; the helper must not touch anything."""
        from models.db import AccountInfo, XeroContactSync

        _invalidate(ENTITY_ID, None)
        seeded.session.commit()

        assert XeroContactSync.query.filter_by(entity_id=ENTITY_ID).count() == 2
        assert AccountInfo.query.filter_by(entity_id=ENTITY_ID).count() == 1

    def test_noop_without_an_entity(self, seeded):
        from models.db import AccountInfo

        _invalidate(None, ORG_A)
        seeded.session.commit()

        assert AccountInfo.query.filter_by(entity_id=ENTITY_ID).count() == 1

    def test_survives_a_missing_bill_account_table(self, seeded):
        """billing-backend owns entity_bill_account_xero; Minty must not assume it.

        It does not exist in this test database at all, so this passing IS the
        assertion: a missing table must not propagate out of the helper and
        take down the OAuth callback that called it.
        """
        _invalidate(ENTITY_ID, ORG_A)
        seeded.session.commit()

        from models.db import AccountInfo

        assert AccountInfo.query.filter_by(entity_id=ENTITY_ID).count() == 0


class TestCallersAreWiredUp:
    """The helper no-ops on a falsy old org, so a dropped call fails silently."""

    def test_all_three_org_write_sites_invalidate(self):
        """Connect and reconnect in the OAuth routes; disconnect in its service (moved there in
        phase 2, 2026-10-05, when the Entity & Integration tab became minty-web's)."""
        import inspect

        from blueprints.xero.routes import routes
        from blueprints.xero.services import disconnect

        source = inspect.getsource(routes) + inspect.getsource(disconnect)
        calls = [
            line.strip()
            for line in source.splitlines()
            if "invalidate_entity_xero_cache(" in line
            and "import" not in line
            and "def " not in line
        ]
        assert len(calls) == 3, (
            "expected connect, reconnect and disconnect to invalidate; found "
            f"{len(calls)}. A missing call is silent: the cache simply never "
            "clears and stale org ids survive the switch."
        )
