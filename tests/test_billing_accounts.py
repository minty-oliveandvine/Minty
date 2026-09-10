"""Billing accounts — the account is the identity, and it holds the cards.

``v1a01_billing_account`` turned ``payer_billing_group`` from "one card and its cycle"
into the account a payer creates and names: ``billing_email`` / ``billing_company``, plus
``billing_account_payment_method`` listing every card on it.

THE ONE THING THESE TESTS ARE REALLY FOR is the duplicated default. The card an account
charges is recorded twice on purpose — as ``payer_billing_group.stripe_payment_method_id``
so the charge path is a single row read, and as ``is_default`` on the shelf so the picker
can render it. Nothing raises when those two disagree; the account simply bills a card the
payer was never shown. So every path that writes either one is pinned here to write both.
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
        first_name="Pat",
        last_name="Payer",
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


def _cards(store, group_id):
    return {
        row.stripe_payment_method_id: row.is_default
        for row in store.cards_in_group(group_id)
    }


# --- opening an account ---------------------------------------------------------


def test_a_new_account_opens_with_its_card_already_on_the_shelf(app, db_session):
    """The shelf is not filled in later. An account charging a card its own list does
    not contain is the divergence the whole table exists to prevent."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "opens@test.com")
        account = store.create_billing_account(
            payer.id, "pm_first",
            billing_email="ap@acme.test", billing_company="Acme Ltd",
        )

        assert account.billing_email == "ap@acme.test"
        assert account.billing_company == "Acme Ltd"
        assert account.stripe_payment_method_id == "pm_first"
        assert _cards(store, account.id) == {"pm_first": True}


def test_an_account_can_be_opened_unnamed(app, db_session):
    """Identity is optional and stays optional — an unnamed account renders as the
    payer's own details, which is what every account did before identities existed."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "unnamed@test.com")
        account = store.create_billing_account(payer.id, "pm_bare")

        assert account.billing_email is None
        assert account.billing_company is None
        assert _cards(store, account.id) == {"pm_bare": True}


def test_blank_identity_fields_are_stored_as_absent_not_as_empty_text(app, db_session):
    """"" and NULL must not be two ways of saying "unnamed" — one of them would print
    as an empty line on an invoice while the other falls back to the payer."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "blank@test.com")
        account = store.create_billing_account(
            payer.id, "pm_blank", billing_email="   ", billing_company="",
        )

        assert account.billing_email is None
        assert account.billing_company is None


def test_a_payer_may_hold_the_same_card_on_two_accounts(app, db_session):
    """What ``uq_payer_billing_group_payer_card`` used to forbid. One company each,
    separate invoices, one card behind both — an ordinary arrangement."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "twoaccounts@test.com")
        first = store.create_billing_account(
            payer.id, "pm_shared", billing_company="Acme Ltd"
        )
        second = store.create_billing_account(
            payer.id, "pm_shared", billing_company="Acme Trading Ltd"
        )

        assert first.id != second.id
        assert {a.id for a in store.billing_groups_for_payer(payer.id)} == {
            first.id, second.id
        }


# --- the shelf ------------------------------------------------------------------


def test_adding_a_card_twice_updates_one_row_rather_than_making_two(app, db_session):
    """Find-or-create. Two rows for one card on one account leaves "which of these is
    it" with no answer."""
    from models.db import db
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "dupe@test.com")
        account = store.create_billing_account(payer.id, "pm_one")

        store.add_card_to_group(account.id, "pm_two")
        store.add_card_to_group(account.id, "pm_two")
        db.session.commit()

        assert _cards(store, account.id) == {"pm_one": True, "pm_two": False}


def test_adding_a_second_card_does_not_change_what_is_charged(app, db_session):
    """"Add a card" is not "switch card". A payer keeping a spare on the account must
    not discover the spare was billed."""
    from models.db import db
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "spare@test.com")
        account = store.create_billing_account(payer.id, "pm_main")

        store.add_card_to_group(account.id, "pm_spare")
        db.session.commit()

        assert account.stripe_payment_method_id == "pm_main"
        assert _cards(store, account.id) == {"pm_main": True, "pm_spare": False}


# --- the duplicated default -----------------------------------------------------


def test_switching_the_default_moves_both_halves_of_the_pair(app, db_session):
    """THE TEST THIS MODULE EXISTS FOR. ``renewals`` reads the account column and the
    picker reads ``is_default``; a switch that moves one and not the other bills a card
    the payer is not being shown, and nothing raises when it happens."""
    from models.db import db
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "switch@test.com")
        account = store.create_billing_account(payer.id, "pm_old")
        store.add_card_to_group(account.id, "pm_new")
        db.session.commit()

        store.set_group_default_card(account.id, "pm_new")

        assert store.billing_group(account.id).stripe_payment_method_id == "pm_new"
        assert _cards(store, account.id) == {"pm_old": False, "pm_new": True}


def test_switching_to_an_unknown_card_puts_it_on_the_shelf_first(app, db_session):
    """"Charge this instead" must not leave the account charging something its own
    list does not contain."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "unknown@test.com")
        account = store.create_billing_account(payer.id, "pm_old")

        store.set_group_default_card(account.id, "pm_never_seen")

        assert store.billing_group(account.id).stripe_payment_method_id == "pm_never_seen"
        assert _cards(store, account.id) == {"pm_old": False, "pm_never_seen": True}


def test_exactly_one_card_is_ever_the_default(app, db_session):
    """Demote-then-promote, in that order. Postgres holds this with a partial unique
    index; the ordering is what makes the service agree with it on every dialect."""
    from models.db import db
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "onedefault@test.com")
        account = store.create_billing_account(payer.id, "pm_a")
        store.add_card_to_group(account.id, "pm_b")
        store.add_card_to_group(account.id, "pm_c")
        db.session.commit()

        for card in ("pm_b", "pm_c", "pm_a"):
            store.set_group_default_card(account.id, card)
            defaults = [k for k, v in _cards(store, account.id).items() if v]
            assert defaults == [card], f"expected only {card} to be default"


def test_nominating_an_entity_onto_a_new_card_opens_the_shelf_too(app, db_session):
    """``nominate_card_for_entity`` is the one path that creates an account without
    going through ``create_billing_account``, so it has to open the shelf itself."""
    from blueprints.subscription.services import store

    with app.app_context():
        payer = _user(db_session, "nominate@test.com")
        entity = _entity(db_session)

        account = store.nominate_card_for_entity(entity.id, payer.id, "pm_nominated")

        assert _cards(store, account.id) == {"pm_nominated": True}


# --- the identity on the Stripe customer ----------------------------------------


def test_the_named_account_outranks_the_user_record(app, db_session):
    """The reversal. The user row still says who the payer IS; the account says what
    their invoices should SAY, and a finance lead does not want their own name there."""
    from blueprints.subscription.services import checkout, store

    with app.app_context():
        payer = _user(db_session, "named@test.com")
        store.create_billing_account(
            payer.id, "pm_x",
            billing_email="invoices@acme.test", billing_company="Acme Ltd",
        )

        assert checkout._payer_identity(payer.id) == {
            "name": "Acme Ltd",
            # NOT the company: description is what tells two payers sharing a name apart
            # in the Stripe dashboard, and two payers may bill for the same company.
            "description": f"@{payer.username}",
            "email": "invoices@acme.test",
        }


def test_an_unnamed_account_leaves_the_user_record_in_charge(app, db_session):
    """An account nobody named must behave exactly as it did before identities."""
    from blueprints.subscription.services import checkout, store

    with app.app_context():
        payer = _user(db_session, "plain@test.com")
        store.create_billing_account(payer.id, "pm_y")

        assert checkout._payer_identity(payer.id) == {
            "name": "Pat Payer",
            "description": f"@{payer.username}",
            "email": "plain@test.com",
        }


def test_the_oldest_named_account_names_the_customer(app, db_session):
    """There is ONE Stripe customer per payer and it holds one name. Taking the most
    recent account would rename the customer every time the payer opened another."""
    from blueprints.subscription.services import checkout, store

    from datetime import datetime, timedelta, timezone

    from models.db import db

    with app.app_context():
        payer = _user(db_session, "oldest@test.com")
        first = store.create_billing_account(
            payer.id, "pm_1", billing_company="First Ltd"
        )
        store.create_billing_account(payer.id, "pm_2", billing_company="Second Ltd")

        # Aged by hand. Both rows take their ``created_at`` from the same server clock
        # and land in the same tick, and the tie then falls to the uuid — stable, but
        # not insertion order, so a test that relied on it would be asserting the
        # tie-break rather than the rule.
        first.created_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.session.commit()

        assert checkout._payer_identity(payer.id)["name"] == "First Ltd"


def test_an_unreadable_account_never_breaks_naming_the_customer(app, monkeypatch):
    """A display name is never worth failing a card save for. Asked outside an app
    context — or with the table missing — this falls back to the user record."""
    import models.db as models_db
    from blueprints.subscription.services import checkout

    class _Payer:
        first_name = "Pat"
        last_name = "Payer"
        username = "patpayer"
        email = "pat@example.com"

    class _UserModel:
        query = type("_Q", (), {"get": staticmethod(lambda uid: _Payer())})()

    monkeypatch.setattr(models_db, "User", _UserModel)

    # No app context here at all, which is exactly what the store call needs.
    assert checkout._payer_identity("u1") == {
        "name": "Pat Payer",
        "description": "@patpayer",
        "email": "pat@example.com",
    }
