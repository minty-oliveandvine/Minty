"""The shop_expense_draft -> shop_expense pairing and mirror (Stage 4b).

Like the report mirror, this works by side effect: routes keep writing to
ShopExpenseDraft and the ShopExpense row follows. If the listener stops firing
nothing raises — expense reads just go stale, which is precisely the failure
the reader migration cannot tolerate.

Delete this file in Stage 5 with the mirror itself.
"""
from __future__ import annotations

from datetime import date

import pytest

_schema_attached = False


@pytest.fixture
def session(app):
    # Matches the other DB-backed tests: models hardcode the pettycashv2
    # schema, so sqlite needs it ATTACHed before create_all().
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(
                        db.text("ATTACH DATABASE ':memory:' AS pettycashv2")
                    )
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        yield db.session
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


@pytest.fixture
def mirror(app):
    import blueprints.report.services.expense_draft_mirror as _m

    return _m


def _report(session, rid="rep-1"):
    from models.db import Report

    r = Report(
        id=rid,
        transaction_date=date(2026, 7, 1),
        company="entity-1",
        opening_balance=0.0,
        status="draft",
    )
    session.add(r)
    session.commit()
    return r


def _draft(session, report_id, eid, **overrides):
    from models.db import ShopExpenseDraft

    values = {"item": "Coffee", "amount": 12.5}
    values.update(overrides)
    d = ShopExpenseDraft(id=eid, report_draft_id=report_id, **values)
    session.add(d)
    session.flush()
    return d


def test_mirrored_columns_exclude_pk_and_fk(mirror):
    """id is never mirrored; the two FK columns are named differently and are
    handled explicitly rather than copied."""
    assert "id" not in mirror._MIRRORED_COLUMNS
    assert "report_id" not in mirror._MIRRORED_COLUMNS
    assert "report_draft_id" not in mirror._MIRRORED_COLUMNS


def test_ensure_creates_paired_row(session, mirror):
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-1")
    mirror.ensure_shop_expense_for_draft(d)
    session.commit()

    e = session.get(ShopExpense, "exp-1")
    assert e is not None
    # report_id comes straight from report_draft_id — same value by design.
    assert e.report_id == "rep-1"
    assert e.item == "Coffee"
    assert e.amount == 12.5


def test_ensure_is_idempotent(session, mirror):
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-2")
    first = mirror.ensure_shop_expense_for_draft(d)
    second = mirror.ensure_shop_expense_for_draft(d)
    session.commit()

    assert first.id == second.id
    assert session.query(ShopExpense).filter_by(id="exp-2").count() == 1


def test_draft_edit_mirrors(session, mirror):
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-3")
    mirror.ensure_shop_expense_for_draft(d)
    session.commit()

    d.item = "Tea"
    d.amount = 3.25
    d.remarks = "changed"
    session.commit()

    e = session.get(ShopExpense, "exp-3")
    assert (e.item, e.amount, e.remarks) == ("Tea", 3.25, "changed")


def test_s3_key_mirrors(session, mirror):
    """s3_key was the column the submit path silently dropped; it must sync."""
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-4")
    mirror.ensure_shop_expense_for_draft(d)
    session.commit()

    d.s3_key = "expenses/abc/receipt.jpg"
    session.commit()

    assert session.get(ShopExpense, "exp-4").s3_key == "expenses/abc/receipt.jpg"


def test_skeleton_draft_satisfies_not_null(session, mirror):
    """api.py:1737 creates a placeholder draft (item="", amount=0.0) for the
    multi-file upload path. shop_expense.item/amount are NOT NULL, so the
    mirrored row must still insert."""
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-5", item="", amount=0.0)
    mirror.ensure_shop_expense_for_draft(d)
    session.commit()

    e = session.get(ShopExpense, "exp-5")
    assert e is not None and e.item == "" and e.amount == 0.0


def test_no_paired_row_is_not_an_error(session):
    """A draft with no ShopExpense (predating this module) must still save."""
    from models.db import ShopExpense

    _report(session)
    d = _draft(session, "rep-1", "exp-6")
    session.commit()  # no ensure_ call

    d.item = "Updated"
    session.commit()  # must not raise

    assert session.get(ShopExpense, "exp-6") is None
    assert d.item == "Updated"
