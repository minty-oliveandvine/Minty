"""Mirror ReportDraft writes onto the paired Report row.

TEMPORARY — this whole module is scaffolding for the report_draft -> report
consolidation and is deleted in Stage 5 once nothing reads report_draft.

-----------------------------------------------------------------------------
WHY IT EXISTS

Stage 4a made a `report` row exist from draft creation
(``ensure_report_row_for_draft``), but nothing keeps it CURRENT: every wizard
step still writes to the draft only. So the report row holds the values frozen
at creation while the user's real edits live on report_draft.

That blocks the reader migration. Pointing any module's reads at `report`
before the writes are mirrored would silently serve stale values — an opening
balance the user already changed would appear to revert. Reads can only move
after writes are kept in sync, which is what this does.

-----------------------------------------------------------------------------
WHY A HOOK RATHER THAN ~40 EXPLICIT DUAL-WRITES

A draft and its report share one id, and the two tables' column sets have
fully converged: all 28 draft columns now exist on `report` (r1a01 added the
last of them). So the mapping is 1:1 and mechanical — exactly the kind of
thing that is safer done once than transcribed forty times.

It also covers modules not yet migrated. A write added to any route tomorrow
is mirrored without anyone remembering to pair it.

-----------------------------------------------------------------------------
WHAT IT DOES NOT DO

* It does not create report rows. ``ensure_report_row_for_draft`` owns that;
  if no paired row exists this quietly does nothing.
* It does not mirror report -> draft. One direction only: the draft is still
  the write target, `report` is the follower. The reverse would create write
  loops and there is nothing that needs it.
* It does not touch ``id``. Re-keying a draft is not a thing that happens, and
  silently rewriting a primary key would be a bug, not a feature.
* It never mirrors ``actual_cash_total`` — that column exists on `report` only
  (hoisted from report_cashcount_draft in r1a01) and has no draft counterpart.

-----------------------------------------------------------------------------
FAILURE POLICY

Non-fatal. A mirror failure must never break the write that prompted it — the
draft remains the source of truth for as long as this module exists, so a
missed mirror is a stale read, not lost data. Failures are logged loudly.
"""
from loguru import logger
from sqlalchemy import event, inspect

# models.db imports THIS module to register the listener, so importing it at
# module scope here would be circular. Every reference is resolved lazily
# inside the functions below instead.

_MIRRORED_COLUMNS = ()


def _compute_mirrored_columns():
    """Columns present on BOTH tables, minus the primary key.

    Derived rather than hardcoded so a column added to both is picked up
    automatically, and one that exists on a single side is skipped by
    construction.
    """
    from models.db import Report, ReportDraft

    return tuple(
        sorted(
            {c.name for c in ReportDraft.__table__.columns}
            & {c.name for c in Report.__table__.columns}
            - {"id"}
        )
    )


def _mirror_draft_to_report(session, draft):
    """Copy the fields that actually changed on ``draft`` onto its Report row."""
    from models.db import Report

    report = session.get(Report, draft.id)
    if report is None:
        # No paired row: either an old draft predating Stage 4a, or a draft
        # created outside ensure_report_row_for_draft. Not this module's job.
        return

    state = inspect(draft)
    changed = []
    for name in _MIRRORED_COLUMNS:
        history = state.attrs[name].history
        # has_changes() is false for an untouched attribute, so an unrelated
        # write to one field does not stamp all 27 others onto the report.
        if not history.has_changes():
            continue
        new_value = getattr(draft, name)
        if getattr(report, name) != new_value:
            setattr(report, name, new_value)
            changed.append(name)

    if changed:
        logger.debug(
            f"draft->report mirror {draft.id}: {', '.join(changed)}"
        )


def _before_flush(session, _flush_context, _instances):
    from models.db import ReportDraft

    # session.dirty is the right hook point: it sees objects whose attributes
    # were modified in this transaction, before the UPDATE is emitted, so the
    # mirrored write lands in the SAME flush and cannot be half-committed.
    for obj in list(session.dirty):
        if isinstance(obj, ReportDraft):
            try:
                _mirror_draft_to_report(session, obj)
            except Exception as exc:
                logger.error(
                    f"draft->report mirror failed for {getattr(obj, 'id', '?')}: {exc}"
                )

    # New drafts are handled too: a draft added and populated in one request
    # would otherwise only mirror on its NEXT write.
    for obj in list(session.new):
        if isinstance(obj, ReportDraft):
            try:
                _mirror_draft_to_report(session, obj)
            except Exception as exc:
                logger.error(
                    f"draft->report mirror failed for new {getattr(obj, 'id', '?')}: {exc}"
                )


_registered = False


def register_draft_report_mirror():
    """Install the listener. Idempotent — safe to call more than once."""
    global _registered, _MIRRORED_COLUMNS
    if _registered:
        return
    from models.db import db

    _MIRRORED_COLUMNS = _compute_mirrored_columns()
    event.listen(db.session, "before_flush", _before_flush)
    _registered = True
    logger.info(
        f"draft->report mirror active ({len(_MIRRORED_COLUMNS)} columns)"
    )
