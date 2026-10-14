"""The cash catalogue's rules, as the database enforces them (2026-10-13).

* ``cash_info`` is unique on (currency, face value, TYPE): Hong Kong's $10 note and $10 coin
  are two rows, and a second $10 coin is refused. The key used to leave ``type`` out, so the
  coin could not be added at all.
* ``cash_info.type`` and ``entity_cash_detail.cash_type`` are NOT NULL: every denomination is a
  note or a coin, and a company's stock row says which (copied from the catalogue).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

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


@pytest.fixture
def hkd(app, db):
    """HKD with the $10 NOTE already in the catalogue (seed_currency types 10 as a note)."""
    with app.app_context():
        return F.seed_currency(db, "HKD", denominations=(100, 10, 1))


def _add_cash(app, db, currency_id, value, kind):
    from models.db import CashInfo

    with app.app_context():
        row = CashInfo(currency_id=currency_id, cash_value=value, type=kind,
                       cash_name=str(value), display_order=99, is_active=True)
        db.session.add(row)
        db.session.commit()
        return row.id


def test_the_ten_dollar_note_and_coin_are_two_denominations(app, db, hkd):
    from models.db import CashInfo

    _add_cash(app, db, hkd.id, 10, "coin")

    with app.app_context():
        tens = {c.type for c in CashInfo.query.filter_by(currency_id=hkd.id, cash_value=10)}
    assert {str(t.value if hasattr(t, "value") else t) for t in tens} == {"note", "coin"}


def test_a_second_ten_dollar_coin_is_refused(app, db, hkd):
    _add_cash(app, db, hkd.id, 10, "coin")
    with pytest.raises(IntegrityError):
        _add_cash(app, db, hkd.id, 10, "coin")
    with app.app_context():
        db.session.rollback()


def test_a_denomination_without_a_type_is_refused(app, db, hkd):
    with pytest.raises(IntegrityError):
        _add_cash(app, db, hkd.id, 20, None)
    with app.app_context():
        db.session.rollback()


def test_a_stock_row_without_a_type_is_refused(app, db, hkd):
    from models.db import CashInfo, EntityCashDetail

    with app.app_context():
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=hkd)
        cash_id = CashInfo.query.filter_by(currency_id=hkd.id, cash_value=100).one().id

    with pytest.raises(IntegrityError):
        with app.app_context():
            db.session.add(EntityCashDetail(entity_id=entity.id, cash_id=cash_id,
                                            cash_type=None, cash_instock=0))
            db.session.commit()
    with app.app_context():
        db.session.rollback()
