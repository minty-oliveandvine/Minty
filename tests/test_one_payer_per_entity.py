"""One payer per entity — enforced in ``store.upsert_module_row``, not merely assumed.

``payer_user_id`` reaches the store as "the acting user" from two directions —
``checkout.start_module_trial`` and ``checkout._grant_purchased_modules`` — so a second
admin starting a trial or buying a module on an entity someone else already pays for
would open a second billing relationship. Nothing downstream models that:
``payer_for_entity`` returns the FIRST row it finds, and ``get_module_cards`` reads one
payer's cycle and applies it to every module on the page.

It was observed live before this guard: one entity holding a paid module on one payer's
cycle and a trial on another payer with no cycle at all. The settings page rendered a
next-invoice date and a prorated conversion figure that belonged to neither of them.

The update path matters as much as the create path — the payer used to be reassigned on
every write, so a second admin merely CANCELLING a module took over the billing.
"""
from __future__ import annotations

import uuid

import pytest

_schema_attached = False


@pytest.fixture
def db_session(app):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _user(db, email):
    from models.db import User

    row = User(
        id=str(uuid.uuid4()),
        email=email,
        username=email,
        first_name="A",
        last_name="B",
        password="x",
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(row)
    db.session.commit()
    return row


def _entity(db, name="Acme"):
    from models.db import Entity

    row = Entity(id=str(uuid.uuid4()), name=name, status="active")
    db.session.add(row)
    db.session.commit()
    return row


def test_a_second_module_joins_the_entitys_existing_payer(app, db_session):
    """The exact shape seen live: admin A trials Petty Cash, admin B trials Bill."""
    from blueprints.subscription.services import store

    with app.app_context():
        entity = _entity(db_session)
        first = _user(db_session, "first@test.com")
        second = _user(db_session, "second@test.com")

        store.upsert_module_row(entity.id, "PETTY_CASH", first.id, phase="trial")
        store.upsert_module_row(entity.id, "BILL", second.id, phase="trial")

        rows = store.module_rows_for_entity(entity.id)
        assert {r.function_code for r in rows} == {"PETTY_CASH", "BILL"}
        assert {r.payer_user_id for r in rows} == {str(first.id)}, (
            "the second module must join the established payer, not open a second one"
        )
        assert store.payer_for_entity(entity.id) == str(first.id)


def test_an_update_cannot_move_the_payer(app, db_session):
    """Cancelling passes the acting user when the row has no payer of its own, and the
    payer used to be rewritten on every write — so this took the billing over."""
    from blueprints.subscription.services import store

    with app.app_context():
        entity = _entity(db_session)
        owner = _user(db_session, "owner@test.com")
        other = _user(db_session, "other@test.com")

        store.upsert_module_row(entity.id, "PETTY_CASH", owner.id, phase="trial")
        store.upsert_module_row(
            entity.id, "PETTY_CASH", other.id, phase="scheduled_cancel"
        )

        row = store.module_row(entity.id, "PETTY_CASH")
        assert row.phase == "scheduled_cancel", "the field write must still land"
        assert row.payer_user_id == str(owner.id), "but the payer must not move"


def test_the_first_payer_is_still_free_to_be_anyone(app, db_session):
    """The guard fixes the payer, it does not dictate who it is — an entity with no
    rows takes whoever acts first."""
    from blueprints.subscription.services import store

    with app.app_context():
        entity = _entity(db_session)
        someone = _user(db_session, "someone@test.com")

        store.upsert_module_row(entity.id, "BILL", someone.id, phase="trial")

        assert store.payer_for_entity(entity.id) == str(someone.id)


def test_entities_do_not_share_a_payer_with_each_other(app, db_session):
    """One payer per ENTITY, not one payer globally — a different entity is free to
    have a different payer, which is the normal multi-company case."""
    from blueprints.subscription.services import store

    with app.app_context():
        one, two = _entity(db_session, "One"), _entity(db_session, "Two")
        a = _user(db_session, "a@test.com")
        b = _user(db_session, "b@test.com")

        store.upsert_module_row(one.id, "BILL", a.id, phase="trial")
        store.upsert_module_row(two.id, "BILL", b.id, phase="trial")

        assert store.payer_for_entity(one.id) == str(a.id)
        assert store.payer_for_entity(two.id) == str(b.id)


def test_repeat_writes_by_the_established_payer_are_untouched(app, db_session):
    """The common path must not be disturbed: same payer, many writes."""
    from blueprints.subscription.services import store

    with app.app_context():
        entity = _entity(db_session)
        owner = _user(db_session, "owner2@test.com")

        store.upsert_module_row(entity.id, "BILL", owner.id, phase="trial")
        store.upsert_module_row(entity.id, "BILL", owner.id, phase="active")
        store.upsert_module_row(entity.id, "PETTY_CASH", owner.id, phase="active")

        rows = store.module_rows_for_entity(entity.id)
        assert len(rows) == 2
        assert {r.payer_user_id for r in rows} == {str(owner.id)}
        assert store.module_row(entity.id, "BILL").phase == "active"
