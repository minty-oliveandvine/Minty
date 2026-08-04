"""Cash denomination resolution and count totalling.

The read path that replaces the hardcoded face values in
``blueprints/report/routes/cash_count.py:300-309`` (and the three duplicate
copies in ``blueprints/report/services/ending.py``).

Two responsibilities:

  * ``resolve_denominations_for_entity`` — which denominations an entity logs,
    in order, with their face values.
  * ``get_cash_count_total`` / ``save_cash_count_details`` — read and write
    counts against those denominations.

The fallback shape mirrors ``get_cash_sales_from_detail``: count rows are the
source of truth, the nine legacy columns on ``report_cashcount_draft`` answer
for reports that predate the backfill.

Table names follow the proposed v3 schema (``cash_info`` /
``entity_cash_setting`` / ``report_cash_count``), so this layer survives the
v3 cutover with only its FK targets changing.
"""

from __future__ import annotations

from loguru import logger

from models.db import (CashInfo, CountryInfo, Entity, EntityCashSetting, ReportCashCount, db)

# Legacy column -> (face value, denomination type). Used only by the fallback
# path for reports with no count rows. Mirrors the nine columns that still
# exist on report_cashcount_draft; note200 is absent because no column was
# ever added for it.
LEGACY_COLUMN_DENOMINATIONS = [
    ("thousand_note", 1000.0, "note"),
    ("fivehundred_note", 500.0, "note"),
    ("onehundred_note", 100.0, "note"),
    ("fifty_note", 50.0, "note"),
    ("twenty_note", 20.0, "note"),
    ("ten_note", 10.0, "note"),
    ("five_coin", 5.0, "coin"),
    ("two_coin", 2.0, "coin"),
    ("one_coin", 1.0, "coin"),
]

# Face value + type -> the form field name the template has always used. Only
# the nine seeded denominations resolve here today; note200 and the HK$10 coin
# are listed so their field names are already right when the form gains inputs
# and they are seeded. An unmapped denomination falls back to cash{id}.
_DEFAULT_FIELD_BY_DENOMINATION = {
    "note1000": (1000.0, "note"),
    "note500": (500.0, "note"),
    "note200": (200.0, "note"),
    "note100": (100.0, "note"),
    "note50": (50.0, "note"),
    "note20": (20.0, "note"),
    "note10": (10.0, "note"),
    "10coins": (10.0, "coin"),
    "5coins": (5.0, "coin"),
    "2coins": (2.0, "coin"),
    "1coins": (1.0, "coin"),
}


def form_field_for(denomination):
    """Form field name for a denomination.

    Keeps the historical field names (``note1000``, ``5coins``) for the HKD
    defaults so existing markup, the hidden inputs and any saved browser
    autofill keep working. Matching is on value AND type, so the $10 note and
    the $10 coin resolve distinctly. Anything else is addressed by cash_id,
    which is stable and unique.
    """
    for field, (value, kind) in _DEFAULT_FIELD_BY_DENOMINATION.items():
        if float(denomination.cash_value) == value and denomination.type == kind:
            return field
    return f"cash{denomination.cash_id}"


def resolve_currency_id(entity):
    """The currency whose denominations this entity counts.

    ``entities.currency_id`` is authoritative. Falls back to the country's
    currency for an entity where it was never backfilled.
    """
    if entity is None:
        return None
    if entity.currency_id:
        return entity.currency_id
    if entity.country_code:
        country = CountryInfo.query.filter_by(
            country_code=entity.country_code
        ).first()
        if country is not None:
            return country.currency_id
    return None


def resolve_denominations_for_entity(entity_id):
    """Denominations an entity logs, ordered for display.

    Starts from the active catalog for the entity's currency, then applies the
    entity's overrides. An entity with no override rows gets its currency
    defaults — which is why creating an entity needs no denomination seed, and
    why a denomination added to a currency later shows up automatically.

    Returns a list of CashInfo rows with ``display_order`` already resolved.
    Empty list means the entity's currency has no catalog — the caller must
    handle that rather than render an empty form.
    """
    entity = Entity.query.filter_by(id=entity_id).first()
    currency_id = resolve_currency_id(entity)
    if not currency_id:
        logger.warning(
            f"resolve_denominations_for_entity: entity {entity_id} has no "
            "resolvable currency — cannot resolve denominations"
        )
        return []

    denominations = (
        CashInfo.query.filter(
            CashInfo.currency_id == currency_id,
            CashInfo.is_active.is_(True),
        )
        .order_by(CashInfo.display_order.asc(), CashInfo.cash_value.desc())
        .all()
    )
    if not denominations:
        logger.warning(
            f"resolve_denominations_for_entity: no active denominations for "
            f"currency {currency_id} (entity {entity_id})"
        )
        return []

    overrides = {
        row.cash_id: row
        for row in EntityCashSetting.query.filter_by(entity_id=entity_id).all()
    }

    resolved = []
    for denomination in denominations:
        override = overrides.get(denomination.cash_id)
        if override is not None:
            if not override.is_active:
                continue
            if override.display_order is not None:
                # Transient: overrides the catalog order for this entity only,
                # never written back to cash_info.
                denomination.display_order = override.display_order
        resolved.append(denomination)

    resolved.sort(key=lambda d: (d.display_order, -float(d.cash_value)))
    return resolved


def get_cash_count_details(report_id):
    """Counted denominations for a report, as {cash_id: ReportCashCount}."""
    return {
        row.cash_id: row
        for row in ReportCashCount.query.filter_by(report_id=report_id).all()
    }


def get_cash_count_total(report_id):
    """Total counted cash for a report.

    Sums ``quantity * cash_value`` over count rows. ``cash_value`` is read
    from the count row, not the catalog, so a revalued or retired
    denomination cannot retroactively change a historical total.

    The legacy wide-column fallback went in Step 4a-5, with the
    report_cashcount_draft table. It was gated on a currency check: c2a02
    backfilled HKD only, and the check came back clean (no non-HKD entity had
    wide-column-only counts with a non-zero total).
    """
    total = (
        db.session.query(
            db.func.sum(ReportCashCount.quantity * ReportCashCount.cash_value)
        )
        .filter(ReportCashCount.report_id == report_id)
        .scalar()
    )
    return float(total) if total is not None else 0.0


def save_cash_count_details(report_id, counts_by_cash_id):
    """Upsert counted quantities for a report.

    ``counts_by_cash_id`` maps cash_id -> quantity. A denomination counted as
    zero has its row removed rather than stored, so the table holds only what
    was actually counted — the same convention the backfill uses.

    Does not commit; the caller owns the transaction so the count and the
    discrepancy it drives are written atomically.
    """
    existing = get_cash_count_details(report_id)
    face_values = {
        row.cash_id: row.cash_value
        for row in CashInfo.query.filter(
            CashInfo.cash_id.in_(list(counts_by_cash_id) or [0])
        ).all()
    }

    for cash_id, count in counts_by_cash_id.items():
        count = int(count or 0)
        row = existing.get(cash_id)
        if count == 0:
            if row is not None:
                db.session.delete(row)
            continue
        if row is None:
            db.session.add(
                ReportCashCount(
                    report_id=report_id,
                    cash_id=cash_id,
                    quantity=count,
                    # Snapshot the face value in force right now.
                    cash_value=face_values.get(cash_id, 0),
                )
            )
        else:
            row.quantity = count


def counts_to_legacy_columns(counts_by_cash_id):
    """Map counted quantities onto the nine legacy column names.

    Keeps report_cashcount_draft in sync while its columns still have five
    readers (ending.py, export_screenshot.py, deposit.py, the template, and
    the next-day opening balance). Denominations with no legacy column — the
    HK$200 note, the HK$10 coin, and anything an entity adds — are simply
    absent from the result; they live only in the count rows.

    Returns {column_name: quantity}, always covering all nine columns so a
    denomination dropped to zero is written back as 0 rather than left stale.
    """
    by_denomination = {
        (float(row.cash_value), row.type): counts_by_cash_id.get(row.cash_id, 0)
        for row in CashInfo.query.filter(
            CashInfo.cash_id.in_(list(counts_by_cash_id) or [0])
        ).all()
    }
    return {
        column: int(by_denomination.get((value, kind), 0) or 0)
        for column, value, kind in LEGACY_COLUMN_DENOMINATIONS
    }


def legacy_column_counts_for_report(report_id):
    """``{legacy_column: quantity}`` for a report, sourced from count rows.

    The read-side counterpart to ``counts_to_legacy_columns``, for consumers
    that are keyed on the nine legacy names and cannot be reshaped — the
    export's .docx template addresses its placeholders as ``qty1_1000`` and
    friends, so the face-value keys have to survive the migration verbatim.

    Returns ``None`` when the report has no cash count at all, so callers can
    tell that from "counted, all zero" — the export 404s on the former and
    must NOT on the latter.

    That distinction used to come from the presence of a
    report_cashcount_draft row. With that table gone (Step 4a-5) the signal is
    ``report.actual_cash_total IS NOT NULL``, which cash_count.py writes on
    every save. It cannot come from the count rows alone: a denomination
    counted as zero has its row deleted, so an all-zero count legitimately has
    NO rows and would otherwise look identical to "never counted".

    Matching is on (value, type), so the HK$10 note and the HK$10 coin stay
    distinct and only the note lands in ``ten_note``, exactly as the wide
    columns behaved.
    """
    rows = get_cash_count_details(report_id)
    if rows:
        return counts_to_legacy_columns(
            {cash_id: row.quantity for cash_id, row in rows.items()}
        )

    from models.db import Report

    counted = (
        db.session.query(Report.actual_cash_total)
        .filter(Report.id == report_id)
        .scalar()
    )
    if counted is None:
        return None  # never counted -> caller 404s

    logger.info(f"Report {report_id} counted as all-zero; returning zeros")
    return {column: 0 for column, _value, _kind in LEGACY_COLUMN_DENOMINATIONS}


def build_denomination_rows(entity_id, report_id=None):
    """Denominations paired with their saved counts, ready for the template.

    Each row exposes ``cash_id``, ``field`` (the form input name), ``label``,
    ``value``, ``type`` and ``count``. The template iterates these instead of
    hardcoding one input per denomination.

    Counts come from report_cash_count. The legacy wide-column fallback went
    in Step 4a-5 with the report_cashcount_draft table; a denomination with no
    row renders as 0, which is also how a zero count is stored.
    """
    denominations = resolve_denominations_for_entity(entity_id)
    saved = get_cash_count_details(report_id) if report_id else {}

    rows = []
    for denomination in denominations:
        detail = saved.get(denomination.cash_id)
        rows.append(
            {
                "cash_id": denomination.cash_id,
                "field": form_field_for(denomination),
                "label": denomination.cash_name,
                "value": float(denomination.cash_value),
                "type": denomination.type,
                "count": detail.quantity if detail is not None else 0,
            }
        )
    return rows
