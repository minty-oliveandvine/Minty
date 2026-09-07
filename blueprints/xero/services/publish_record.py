"""Remember which Xero objects a report's publish created.

Publishing a petty-cash report posts to Xero's *collection* endpoints, so
without a record of what came back a republish creates a second copy of every
transaction. This module is that record.

It lives in ``pettycashv2.xero_report_sync``, which already exists and needed
no migration: only ``id`` is NOT NULL, and ``xero_reponse_text`` (the typo is
in the column name) is unbounded nullable text. Migration r9a09 describes that
table as "the audit trail of what was pushed to Xero -- the record that detects
a double-publish" and reshaped its keys so it survives report deletion. Nothing
had ever written to it.

Storing structured JSON in an existing text column follows ``publish_errors``,
which already does exactly this with ``report_history.new_value``.

Shape::

    {"version": 1,
     "org": "<entity.xero_org_id at publish time>",
     "objects": {
        "invoices":   {"type": "INVOICE", "id": "..."},
        "deposit":    {"type": "BANK_TRANSFER", "id": "...", "amount": 12.0},
        "expenses":   {"<shop_expense.id>": {"type": "BANK_TRANSACTION", "id": "..."}},
     }}

``expenses`` is keyed by ShopExpense id because a report has many; the other
modules hold a single object each.
"""

import json
from datetime import datetime

from loguru import logger

from models.db import XeroReportSync, db

RECORD_VERSION = 1

# Modules that hold one Xero object per report. ``expenses`` is the exception
# and is keyed by ShopExpense id.
PER_REPORT_MODULES = ("invoices", "deposit", "withdrawal_from", "discrepancy")
PER_SOURCE_MODULES = ("expenses",)


def _empty_record(org_id=None) -> dict:
    return {"version": RECORD_VERSION, "org": str(org_id or ""), "objects": {}}


def _row_for(report_id):
    return XeroReportSync.query.filter_by(report_id=report_id).first()


def load_record(report_id, current_org_id=None) -> dict:
    """Return the record for ``report_id``, or an empty one.

    An empty record means "nothing known was published", which makes every
    caller fall back to creating -- today's behaviour.

    ``current_org_id`` guards against a Xero organisation switch. Object ids
    issued by one org mean nothing in another, so a record from a different org
    is discarded rather than used to build a doomed update. A record with no
    org recorded counts as a match, so nothing written before this check
    existed regresses.
    """
    if not report_id:
        return _empty_record(current_org_id)

    row = _row_for(report_id)
    if row is None or not row.xero_reponse_text:
        return _empty_record(current_org_id)

    try:
        record = json.loads(row.xero_reponse_text)
    except (ValueError, TypeError):
        # The column is free text and predates this format. Anything we cannot
        # parse is treated as "no record" rather than an error: the worst case
        # is the duplicate that already happens today.
        logger.warning(
            f"xero_report_sync for report {report_id} is not valid JSON; "
            "ignoring it and treating the report as unpublished"
        )
        return _empty_record(current_org_id)

    if not isinstance(record, dict) or not isinstance(record.get("objects"), dict):
        return _empty_record(current_org_id)

    recorded_org = str(record.get("org") or "")
    if current_org_id and recorded_org and recorded_org != str(current_org_id):
        logger.info(
            f"Report {report_id} was published to Xero org {recorded_org} but "
            f"the entity is now on {current_org_id}; ignoring the recorded "
            "object ids and publishing fresh"
        )
        return _empty_record(current_org_id)

    record.setdefault("version", RECORD_VERSION)
    record.setdefault("org", recorded_org)
    return record


def _save(report_id, record) -> None:
    """Upsert the record onto the report's xero_report_sync row, and commit.

    Committing here rather than leaving it to the end of the publish run is
    the point of the whole module: an object Xero has already created must be
    remembered even if a later module crashes the run, or the retry creates a
    second copy of it.
    """
    row = _row_for(report_id)
    if row is None:
        row = XeroReportSync(report_id=report_id)
        db.session.add(row)

    row.xero_reponse_text = json.dumps(record)
    row.sync_statuc = "completed"
    row.completed_at = datetime.now()
    if row.reported_at is None:
        row.reported_at = datetime.now()

    try:
        db.session.commit()
    except Exception as exc:
        # Never let bookkeeping fail a publish that Xero already accepted.
        # The cost of losing this row is a duplicate on the next republish,
        # which is exactly what happens today.
        db.session.rollback()
        logger.error(
            f"Could not record Xero object ids for report {report_id}: {exc}"
        )


def record_object(
    report_id, org_id, module, xero_id, *, source_id=None, object_type=None, **extra
) -> None:
    """Remember that ``module`` created ``xero_id`` for this report.

    Written as each module succeeds rather than once at the end of the run: a
    crash mid-publish would otherwise lose the ids of objects Xero has already
    created, which is the duplicate this whole module exists to prevent.
    """
    if not report_id or not module or not xero_id:
        return

    record = load_record(report_id)
    record["org"] = str(org_id or record.get("org") or "")

    entry = {"type": object_type or "", "id": str(xero_id)}
    entry.update({k: v for k, v in extra.items() if v is not None})

    if source_id:
        bucket = record["objects"].setdefault(module, {})
        if not isinstance(bucket, dict):
            bucket = {}
            record["objects"][module] = bucket
        bucket[str(source_id)] = entry
    else:
        record["objects"][module] = entry

    _save(report_id, record)


def forget_object(report_id, module, *, source_id=None) -> None:
    """Drop a recorded object.

    Used when the object is gone from Xero (deleted, or about to be replaced).
    Forgetting BEFORE a delete-and-recreate matters: if the recreate then
    fails, no stale id is left pointing at a transfer that no longer exists.
    """
    if not report_id or not module:
        return

    record = load_record(report_id)
    if module not in record["objects"]:
        return

    if source_id:
        bucket = record["objects"].get(module)
        if isinstance(bucket, dict):
            bucket.pop(str(source_id), None)
            if not bucket:
                record["objects"].pop(module, None)
    else:
        record["objects"].pop(module, None)

    _save(report_id, record)


def recorded_entry(record, module, source_id=None):
    """Return the stored entry dict for a module (or one expense), or None."""
    if not isinstance(record, dict):
        return None
    entry = (record.get("objects") or {}).get(module)
    if source_id is not None:
        if not isinstance(entry, dict):
            return None
        entry = entry.get(str(source_id))
    if isinstance(entry, dict) and entry.get("id"):
        return entry
    return None


def recorded_id(record, module, source_id=None):
    """Return the stored Xero object id for a module (or one expense), or None."""
    entry = recorded_entry(record, module, source_id)
    return entry.get("id") if entry else None


def recorded_expense_ids(record) -> dict:
    """Return ``{shop_expense_id: xero_object_id}`` for every recorded expense."""
    bucket = (record.get("objects") or {}).get("expenses") if record else None
    if not isinstance(bucket, dict):
        return {}
    return {
        key: value.get("id")
        for key, value in bucket.items()
        if isinstance(value, dict) and value.get("id")
    }
