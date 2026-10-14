"""The schema's views, read the way the code will read them (2026-10-13).

* ``report_cash_summary`` - a report's counted cash. An all-zero count stores no
  ``report_cash_count`` rows, so "the cash-count step is done and nothing was counted" must
  read 0, not NULL ("never counted"). That rule used to live only in ``Report.actual_cash_total``.
* ``entity_setup_summary`` - one row per company: Xero, modules, how many of the six petty-cash
  accounts and three contacts are mapped, bill account codes, the opening balance. It existed
  only in Supabase; the setup checks, the company list and onboarding resume read it now.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

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
        _db.session.execute(_db.text(f"DELETE FROM {_schema()}.entity_bill_account_xero"))
        _db.session.commit()


def _schema():
    from blueprints.shared.schema import SCHEMA

    return SCHEMA


@pytest.fixture
def shop(app, db):
    with app.app_context():
        currency = F.seed_currency(db, "HKD", denominations=(100, 10, 1))
        country = F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country,
                               modules=("PETTY_CASH", "PAYMENT_REQUEST"))
    return owner, entity, currency


def _report(app, db, entity, day, *, sections=(), safe_box=None, counts=None):
    """A report row with ``counts`` = {face value: quantity} cash-count rows."""
    from models.db import CashInfo, Report, ReportCashCount

    with app.app_context():
        report = Report(entity_id=entity.id, transaction_date=day, status="submitted",
                        completed_sections=list(sections), safe_box_balance=safe_box)
        db.session.add(report)
        db.session.flush()
        for value, qty in (counts or {}).items():
            cash = CashInfo.query.filter_by(cash_value=value).first()
            db.session.add(ReportCashCount(report_id=report.id, cash_id=cash.id,
                                           quantity=qty, cash_value=value))
        db.session.commit()
        return report.id


def _cash_summary(app, db, report_id):
    with app.app_context():
        row = db.session.execute(
            db.text(f"SELECT actual_cash_total, cash_balance FROM {_schema()}.report_cash_summary "
                    "WHERE report_id = :id"), {"id": report_id},
        ).one()
        return row.actual_cash_total, row.cash_balance


def _setup(app, db, entity_id):
    with app.app_context():
        return db.session.execute(
            db.text(f"SELECT * FROM {_schema()}.entity_setup_summary WHERE entity_id = :id"),
            {"id": entity_id},
        ).mappings().one()


# ---- report_cash_summary ----------------------------------------------------------------


def test_a_counted_report_sums_its_denominations_and_adds_the_safe_box(app, db, shop):
    _owner, entity, _cur = shop
    rid = _report(app, db, entity, date(2026, 9, 1), sections=["cash_count"], safe_box=50,
                  counts={100: 3, 10: 2})
    assert _cash_summary(app, db, rid) == (Decimal("320.00"), Decimal("370.00"))


def test_an_all_zero_count_reads_zero_not_never_counted(app, db, shop):
    """Zero quantities store no rows; the done cash-count step is what makes it 0."""
    _owner, entity, _cur = shop
    rid = _report(app, db, entity, date(2026, 9, 1), sections=["opening", "cash_count"], safe_box=5)
    assert _cash_summary(app, db, rid) == (Decimal("0"), Decimal("5"))


def test_a_report_never_counted_reads_null(app, db, shop):
    _owner, entity, _cur = shop
    rid = _report(app, db, entity, date(2026, 9, 1), sections=["opening"])
    assert _cash_summary(app, db, rid) == (None, None)


# ---- entity_setup_summary ----------------------------------------------------------------


def test_setup_summary_counts_what_is_mapped(app, db, shop):
    from models.db import AccountInfo, Entity, EntityPettycashSettings, XeroContactSync

    _owner, entity, _cur = shop
    with app.app_context():
        e = Entity.query.get(entity.id)
        e.xero_org_id = "org-1"
        e.status = "connected"
        acc = [AccountInfo(entity_id=entity.id, type="BANK", name=f"Acc {i}", xero_code=f"{i}00")
               for i in range(3)]
        con = XeroContactSync(entity_id=entity.id, xero_contact_id="c-1", name="Director")
        db.session.add_all([*acc, con])
        db.session.flush()
        db.session.add(EntityPettycashSettings(
            entity_id=entity.id, pettycash_account_id=acc[0].id, bank_account_id=acc[1].id,
            cash_sale_account_id=acc[2].id, director_contact_id=con.id,
            opening_balance=750, start_date=date(2026, 9, 1),
        ))
        for code, active in (("400", True), ("410", True), ("420", False)):
            db.session.execute(
                db.text(f"INSERT INTO {_schema()}.entity_bill_account_xero "
                        "(entity_id, account_code, is_active) VALUES (:e, :c, :a)"),
                {"e": entity.id, "c": code, "a": active},
            )
        db.session.commit()
        pettycash_account_id = str(acc[0].id)

    row = _setup(app, db, entity.id)
    assert row["xero_connected"] is True and row["xero_org_linked"] is True
    assert row["pettycash_module_enabled"] is True and row["bill_module_enabled"] is True
    assert (row["pettycash_accounts_set"], row["pettycash_accounts_total"]) == (3, 6)
    assert (row["pettycash_contacts_set"], row["pettycash_contacts_total"]) == (1, 3)
    assert row["xero_accounts_synced"] == 3
    assert row["bill_accounts_set"] == 2
    assert str(row["pettycash_account_id"]) == pettycash_account_id
    assert row["opening_balance"] == Decimal("750.00") and row["start_date"] == date(2026, 9, 1)


def test_a_company_with_nothing_set_up_has_a_row_of_zeros(app, db, shop):
    _owner, entity, _cur = shop
    row = _setup(app, db, entity.id)
    assert row["xero_org_linked"] is False
    assert (row["pettycash_accounts_set"], row["pettycash_contacts_set"]) == (0, 0)
    assert row["bill_accounts_set"] == 0
    assert row["pettycash_account_id"] is None and row["opening_balance"] is None
