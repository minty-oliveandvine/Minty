"""The report_draft -> report mirror (Stage 4b scaffolding).

These tests exist because the mirror is invisible at the call site: routes go on
writing to the draft and the Report row updates by side effect. If the listener
silently stops firing, nothing raises — reads just start serving stale values.
That is exactly the failure the reader migration cannot tolerate, so it gets a
test rather than trust.

Delete this file in Stage 5 along with the mirror itself.
"""
from __future__ import annotations

from datetime import date

import pytest

# NOTE: models are imported INSIDE the fixtures, not at module scope. The `app`
# fixture (tests/conftest.py) clears cached modules before building the Flask
# app, so a module-level import here binds classes that are then discarded and
# the mappers fail to configure.


def _mk(session, rid, **overrides):
    """A draft and its paired report row, sharing one id."""
    from models.db import Report, ReportDraft

    values = {
        "transaction_date": date(2026, 7, 1),
        "company": "entity-1",
        "opening_balance": 100.0,
        "status": "draft",
    }
    values.update(overrides)
    draft = ReportDraft(id=rid, **values)
    report = Report(id=rid, **values)
    session.add_all([draft, report])
    session.commit()
    return draft, report


_schema_attached = False


@pytest.fixture
def session(app):
    # Same setup the other DB-backed tests use: the models hardcode the
    # pettycashv2 schema, so sqlite needs it ATTACHed before create_all().
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
    import blueprints.report.services.draft_report_mirror as _mirror

    return _mirror


def test_mirrored_columns_exclude_primary_key(mirror):
    """id must never be mirrored — rewriting a PK would be a bug, not a sync."""
    assert "id" not in mirror._MIRRORED_COLUMNS


def test_mirrored_columns_exclude_report_only_fields(mirror):
    """actual_cash_total lives on report only; it has no draft counterpart."""
    assert "actual_cash_total" not in mirror._MIRRORED_COLUMNS


def test_draft_write_lands_on_report(session):
    draft, _ = _mk(session, "mirror-1")

    draft.opening_balance = 555.0
    draft.cash_addition = 25.0
    draft.withdrawal_type = "company"
    session.commit()

    from models.db import Report

    report = session.get(Report, "mirror-1")
    assert report.opening_balance == 555.0
    assert report.cash_addition == 25.0
    assert report.withdrawal_type == "company"


def test_mirror_only_touches_changed_fields(session):
    """A write to one field must not stamp the draft's other 26 onto the report.

    The two rows legitimately diverge before the reader migration completes, so
    a blanket copy would clobber report-side values nobody asked to change.
    """
    draft, report = _mk(session, "mirror-2")

    # Diverge the report deliberately.
    report.uploaded_by = "report-side-value"
    session.commit()

    # Touch one unrelated field on the draft.
    draft.opening_balance = 999.0
    session.commit()

    from models.db import Report

    refreshed = session.get(Report, "mirror-2")
    assert refreshed.opening_balance == 999.0
    assert refreshed.uploaded_by == "report-side-value"


def test_workflow_fields_mirror(session):
    """current_section / completed_sections drive the stepper, so they matter."""
    draft, _ = _mk(session, "mirror-3")

    draft.current_section = "expenses"
    draft.completed_sections = ["opening", "sales"]
    session.commit()

    from models.db import Report

    report = session.get(Report, "mirror-3")
    assert report.current_section == "expenses"
    assert report.completed_sections == ["opening", "sales"]


def test_status_flip_mirrors(session):
    """Submit flips the draft to 'posted'; the report must follow."""
    draft, _ = _mk(session, "mirror-4")

    draft.status = "posted"
    session.commit()

    from models.db import Report

    assert session.get(Report, "mirror-4").status == "posted"


def test_no_paired_report_is_not_an_error(session):
    """Drafts predating Stage 4a have no report row. That must not raise."""
    from models.db import Report, ReportDraft

    draft = ReportDraft(
        id="orphan-1",
        transaction_date=date(2026, 7, 1),
        company="entity-1",
        opening_balance=10.0,
        status="draft",
    )
    session.add(draft)
    session.commit()

    draft.opening_balance = 42.0
    session.commit()  # must not raise

    assert session.get(Report, "orphan-1") is None
    assert draft.opening_balance == 42.0
