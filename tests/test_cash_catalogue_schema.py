"""The cash catalogue's rules, as the database enforces them.

* ``cash_info`` is unique on (currency, face value): Hong Kong's $10 is a note, and a $10 coin
  beside it is refused. c5a05 (2026-10-13) added ``type`` to the key and made ``type`` /
  ``entity_cash_detail.cash_type`` NOT NULL; that was withdrawn on 2026-10-14
  (migrations/c5a05_down.sql), so the code always writes a type but the database does not
  insist on one.
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


def test_a_ten_dollar_coin_beside_the_ten_dollar_note_is_refused(app, db, hkd):
    with pytest.raises(IntegrityError):
        _add_cash(app, db, hkd.id, 10, "coin")
    with app.app_context():
        db.session.rollback()
