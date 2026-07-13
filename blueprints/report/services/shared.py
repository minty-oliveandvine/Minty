# Shared helpers for report flow: safe_float, parse_nested_keys,
# check_user_has_entities, draft progress, cleanup,
# get_cash_sales_from_detail.
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy.orm.attributes import flag_modified

from models.db import (Report, ReportDraft, ReportSaleDetail, ReportV2,
                       SaleInfo, ShopExpense, db, tz)
from utils.report import parse_nested_keys as _parse_nested_keys
from utils.report import safe_float as _safe_float

safe_float = _safe_float
parse_nested_keys = _parse_nested_keys


def header_publishing_status_for(
    report_id=None, entity_id=None, transaction_date=None
):
    """Return the posted Report's ``publishing_status`` for the header badge.

    Report flow steps (opening/sales/expense/deposit/cash count/ending) render
    the shared status badge but operate on a ReportDraft, which has no
    ``publishing_status``.  This looks up the matching posted Report so the
    badge can show "Partially Published".  Returns ``None`` when no posted
    report exists yet (draft-only), leaving the badge on Draft/Submitted.
    """
    try:
        row = None
        if report_id:
            row = Report.query.filter(Report.id == report_id).first()
        if row is None and entity_id and transaction_date:
            row = Report.query.filter(
                Report.company == entity_id,
                Report.transaction_date == transaction_date,
            ).first()
        return row.publishing_status if row else None
    except Exception as exc:  # never break a page render over a badge
        logger.warning(f"header_publishing_status_for failed: {exc}")
        return None


def normalize_expense_files(
    files_value: str | None,
    s3_key_column: str | None = None,
) -> list[dict]:
    """Normalize the ``files`` column of a ShopExpense / ShopExpenseDraft row
    into a consistent list of dicts suitable for template rendering.

    Handles two on-disk formats:

    * Format A — plain comma-separated S3 key(s):
      ``expenses/uuid/12_APR_2026_COST_OF_GOODS_100.jpg``

    * Format B — JSON object (single file metadata written by the multi-file
      upload path):
      ``{"original_filename": "image_13.png", "mime_type": "image/png"}``
      The JSON object intentionally omits the S3 key — the full object key is
      stored separately in the ``s3_key`` DB column.  Pass ``s3_key_column``
      so this function can emit the correct key for presigned-URL generation.

    Args:
        files_value:   Raw value of the ``files`` DB column.
        s3_key_column: Value of the ``s3_key`` DB column (only needed for
                       Format B records; ignored for Format A).

    Returns a list of::

        {
            "s3_key":       str,   # S3 key — used to build /download/<key>
            "display_name": str,   # human-readable filename
            "mime_type":    str,   # best-effort MIME type
        }

    An empty list is returned when *files_value* is falsy or unparseable.
    """
    if not files_value or not files_value.strip():
        return []

    results: list[dict] = []
    trimmed = files_value.strip()

    # --- Format B: single JSON object ----------------------------------------
    if trimmed.startswith("{") and trimmed.endswith("}"):
        try:
            obj = json.loads(trimmed)
            original_filename = obj.get("original_filename", "")
            mime_type = obj.get("mime_type", "")
            # Prefer the dedicated s3_key DB column (passed by caller) because
            # Format B JSON deliberately omits the full S3 path.  Fall back to
            # any s3_key/file_path stored inside the JSON blob, and finally to
            # original_filename as a last resort (which will NOT resolve in S3
            # but is better than an empty key for error messages).
            s3_key = (
                s3_key_column
                or obj.get("s3_key")
                or obj.get("file_path")
                or obj.get("path")
                or ""
            )
            if not s3_key and original_filename:
                s3_key = original_filename
            display_name = original_filename or os.path.basename(s3_key) or "file"
            if not mime_type:
                ext = os.path.splitext(display_name)[-1].lower().lstrip(".")
                mime_type = (
                    "application/pdf" if ext == "pdf"
                    else f"image/{ext}" if ext in {"jpg", "jpeg", "png", "gif", "webp"}
                    else "application/octet-stream"
                )
            results.append({"s3_key": s3_key, "display_name": display_name, "mime_type": mime_type})
            return results
        except (json.JSONDecodeError, TypeError):
            logger.warning("normalize_expense_files: failed to parse JSON object, falling through")

    # --- Format B: JSON array -------------------------------------------------
    if trimmed.startswith("[") and trimmed.endswith("]"):
        try:
            entries = json.loads(trimmed)
            for entry in entries:
                if isinstance(entry, str) and entry.strip():
                    key = entry.strip()
                    results.append({
                        "s3_key": key,
                        "display_name": os.path.basename(key) or key,
                        "mime_type": _mime_from_key(key),
                    })
                elif isinstance(entry, dict):
                    s3_key = (
                        entry.get("s3_key")
                        or entry.get("file_path")
                        or entry.get("path")
                        or entry.get("url")
                        or entry.get("original_filename")
                        or ""
                    )
                    display_name = (
                        entry.get("original_filename")
                        or entry.get("name")
                        or os.path.basename(s3_key)
                        or "file"
                    )
                    mime_type = entry.get("mime_type") or _mime_from_key(s3_key)
                    if s3_key:
                        results.append({"s3_key": s3_key, "display_name": display_name, "mime_type": mime_type})
            if results:
                return results
        except (json.JSONDecodeError, TypeError):
            logger.warning("normalize_expense_files: failed to parse JSON array, falling through")

    # --- Format A: comma-separated plain S3 keys ------------------------------
    for key in trimmed.split(","):
        key = key.strip()
        if key:
            results.append({
                "s3_key": key,
                "display_name": os.path.basename(key) or key,
                "mime_type": _mime_from_key(key),
            })

    return results


def _mime_from_key(key: str) -> str:
    """Return a best-effort MIME type from an S3 key / filename."""
    ext = os.path.splitext(key)[-1].lower().lstrip(".")
    if ext == "pdf":
        return "application/pdf"
    if ext in {"jpg", "jpeg", "png", "gif", "webp"}:
        return f"image/{ext if ext != 'jpg' else 'jpeg'}"
    return "application/octet-stream"


def future_date_error(selected_date, today=None):
    """Return an error message if ``selected_date`` is after today, else None.

    Single source of truth for the "no future-dated reports" rule: a report can
    never be created for any date after today. ``today`` defaults to the current
    date in the entity's business timezone (Asia/Hong_Kong) so the boundary
    matches the local calendar day, not the server's clock.
    """
    if today is None:
        today = datetime.now(tz).date()
    if selected_date and selected_date > today:
        return (
            "Transaction date cannot be in the future. You can only create "
            f"reports for dates up to {today}."
        )
    return None


def check_user_has_entities(user_id):
    """Return True if the user has access to at least one entity. Delegates to entity service."""
    from blueprints.entity.services.shared import \
        check_user_has_entities as check_entities

    return check_entities(user_id)


def update_draft_progress(
        report_draft,
        action_type,
        current_section,
        next_section):
    """Update report_draft.current_section and completed_sections for save_next or save_exit."""
    if report_draft.completed_sections is None:
        report_draft.completed_sections = []

    if action_type == "save_next":
        report_draft.current_section = next_section
        if current_section not in report_draft.completed_sections:
            new_completed_sections = list(
                report_draft.completed_sections or [])
            new_completed_sections.append(current_section)
            report_draft.completed_sections = new_completed_sections
            flag_modified(report_draft, "completed_sections")
    elif action_type == "save_exit":
        report_draft.current_section = current_section
        if current_section not in report_draft.completed_sections:
            new_completed_sections = list(
                report_draft.completed_sections or [])
            new_completed_sections.append(current_section)
            report_draft.completed_sections = new_completed_sections
            flag_modified(report_draft, "completed_sections")


def seed_opening_draft(user_id, entity_id, transaction_date, cash_addition):
    """Create/update the first 'opening' report draft from onboarding (Step 4).

    The onboarding 'beginning petty cash amount' is recorded as the draft's
    ``opening_balance`` for the chosen date (with ``cash_addition`` left at 0) so
    the petty-cash starting cash balance matches the amount entered during
    onboarding, rather than appearing as an addition to the cash drawer. The
    adjusted opening still equals the amount, so day 1's closing balance — and
    therefore the opening that carries into every subsequent day — is unchanged.
    This only affects the first onboarding day; future reports derive their
    opening from the previous day's closing balance (report create flow), a
    separate path this function does not touch. Idempotent per entity while the
    entity is still pre-first-report: re-saving on revisit updates the SAME
    onboarding draft in place — including moving its ``transaction_date`` when
    the user changes the opening date — rather than seeding a second draft. The
    selected date is honoured as-is (no first-report 7-day window — onboarding
    deliberately lets the user pick any start date in the current month).

    Once the entity has any posted ``Report``, onboarding is over and this
    falls back to keying on (entity, date) so it can only ever touch a draft
    for the exact date requested and never disturbs an unrelated day's
    in-progress draft.

    Returns ``(data, status_code)``.
    """
    from models.db import User
    from services.permission_policy import (Permission,
                                            has_permission_by_user_id)

    if not has_permission_by_user_id(user_id, Permission.REPORT_EDIT_OWN, entity_id):
        return {"error": "Access denied"}, 403

    if isinstance(transaction_date, str):
        try:
            tx_date = datetime.strptime(transaction_date.strip(), "%Y-%m-%d").date()
        except (ValueError, AttributeError):
            return {"error": "Invalid date format (expected YYYY-MM-DD)"}, 400
    else:
        tx_date = transaction_date
    if not tx_date:
        return {"error": "A start date is required"}, 400

    # Reject future start dates. Anchored to Hong Kong time so the boundary is
    # the users' local midnight, not the server's (UTC) midnight.
    today_hk = datetime.now(tz).date()
    if tx_date > today_hk:
        return {
            "error": (
                "Start date cannot be in the future. "
                f"You can only choose dates up to {today_hk}."
            )
        }, 400

    amount = safe_float(cash_addition)
    if amount < 0:
        return {"error": "Opening amount cannot be negative"}, 400

    if Report.query.filter(
        Report.company == entity_id,
        Report.transaction_date == tx_date,
    ).first():
        return {"error": f"A report for {tx_date} already exists."}, 409

    user = User.query.get(user_id)
    username = user.username if user else None
    adjusted = amount  # opening_balance (amount) + cash_addition (0)

    # While the entity is still pre-first-report (no posted Report at all), the
    # single existing draft IS the onboarding opening draft. Bind it by entity
    # alone so a revisit that changes the opening date UPDATES this same draft
    # (moving its transaction_date) instead of seeding a duplicate for the new
    # date. Order by date.asc() to pick the earliest draft as the canonical
    # opening draft in the (unexpected) event more than one exists.
    #
    # After the first Report is posted, onboarding is over: fall back to keying
    # on the exact (entity, date) so we can only ever touch a draft for the
    # requested date and never disturb an unrelated day's in-progress draft.
    entity_has_posted_report = (
        db.session.query(Report.id)
        .filter(Report.company == entity_id)
        .first()
        is not None
    )
    if entity_has_posted_report:
        draft = ReportDraft.query.filter(
            ReportDraft.company == entity_id,
            ReportDraft.transaction_date == tx_date,
            ReportDraft.status == "draft",
        ).first()
    else:
        draft = (
            ReportDraft.query.filter(
                ReportDraft.company == entity_id,
                ReportDraft.status == "draft",
            )
            .order_by(ReportDraft.transaction_date.asc())
            .first()
        )

    if draft:
        # Move the draft to the (possibly changed) requested date. When the
        # user edits the opening date on revisit this updates the existing
        # onboarding draft in place rather than leaving a stale one behind.
        draft.transaction_date = tx_date
        draft.opening_balance = amount
        draft.cash_addition = 0.0
        draft.adjusted_opening_balance = adjusted
        draft.closing_balance = adjusted
        draft.next_transaction_date = tx_date + timedelta(days=1)
        if username:
            draft.uploaded_by = username
        # The onboarding opening balance is seeded here, but the user still
        # starts their first report at Opening so they can see/confirm it — so
        # we don't pre-mark the opening section complete.
        created = False
    else:
        draft = ReportDraft(
            transaction_date=tx_date,
            next_transaction_date=tx_date + timedelta(days=1),
            opening_balance=amount,
            cash_addition=0.0,
            adjusted_opening_balance=adjusted,
            cash_sales=0.0, visa_sales=0.0, alipay_sales=0.0, wechat_sales=0.0,
            master_sales=0.0, unionpay_sales=0.0, amex_sales=0.0,
            octopus_sales=0.0, deliveroo_sales=0.0, foodpanda_sales=0.0,
            keeta_sales=0.0, openrice_sales=0.0, shop_sales=0.0,
            delivery_sales=0.0, total_sales=0.0, expenses=0.0, bank_deposit=0.0,
            closing_balance=adjusted,
            current_section="opening",  # start the first report at opening
            completed_sections=[],
            uploaded_by=username,
            company=entity_id,
            status="draft",
        )
        db.session.add(draft)
        created = True

    db.session.commit()
    logger.info(
        "seed_opening_draft: entity=%s date=%s opening_balance=%s created=%s draft=%s",
        entity_id, tx_date, amount, created, draft.id,
    )
    return {
        "draft_id": draft.id,
        "transaction_date": tx_date.isoformat(),
        "opening_balance": amount,
        "cash_addition": 0.00,
        "adjusted_opening_balance": adjusted,
        "created": created,
    }, 200


def cleanup_partial_submission_data(draft_id, logger=None):
    """Remove partial Report and ShopExpense records for a draft. Returns True on success."""
    try:
        partial_reports = Report.query.filter(Report.id == draft_id).all()
        for report in partial_reports:
            db.session.delete(report)
        if logger:
            logger.info(f"Cleaned up partial Report record: {draft_id}")

        partial_expenses = ShopExpense.query.filter(
            ShopExpense.report_id == draft_id
        ).all()
        for expense in partial_expenses:
            db.session.delete(expense)
        if logger:
            logger.info(
                f"Cleaned up partial ShopExpense records for draft {draft_id}")

        db.session.commit()
        if logger:
            logger.info(
                f"Successfully cleaned up partial data for draft {draft_id}")
        return True
    except Exception as e:
        if logger:
            logger.error(
                f"Error cleaning up partial data for draft {draft_id}: {str(e)}"
            )
        db.session.rollback()
        return False


def resolve_report_entity_id(report_id: str | None) -> str | None:
    if not report_id:
        return None

    report = Report.query.filter_by(id=report_id).first()
    if report and report.company:
        return str(report.company)

    draft = ReportDraft.query.filter_by(id=report_id).first()
    if draft and draft.company:
        return str(draft.company)

    return None


def get_next_section_for_user(
        user,
        company,
        transaction_date=None,
        draft_id=None):
    """Determine the next report section from current user/entity draft state."""
    if transaction_date is None:
        transaction_date = datetime.now().date()
    elif isinstance(transaction_date, str):
        try:
            transaction_date = datetime.strptime(
                transaction_date, "%Y-%m-%d").date()
        except ValueError:
            transaction_date = datetime.now().date()

    if draft_id:
        existing_draft = ReportDraft.query.filter(
            ReportDraft.id == draft_id,
            ReportDraft.company == company,
            ReportDraft.status == "draft",
        ).first()
    else:
        existing_draft = (
            ReportDraft.query.filter(
                ReportDraft.company == company,
                ReportDraft.transaction_date == transaction_date,
                ReportDraft.status == "draft",
            )
            .order_by(ReportDraft.date.desc())
            .first()
        )

    if existing_draft and existing_draft.current_section:
        return existing_draft.current_section, existing_draft.id, True

    return "opening", None, False


def get_cash_sales_from_detail(report_id, fallback_value=0.0):
    """
    Calculate cash sales from ReportSaleDetail table for a given report_id.
    Works for both Report and ReportDraft.
    """
    logger.info(
        f"Getting cash sales from report_sale_detail for report {report_id}")
    report_sale_details = (
        db.session.query(ReportSaleDetail, SaleInfo)
        .join(SaleInfo, ReportSaleDetail.sale_id == SaleInfo.sale_id)
        .filter(ReportSaleDetail.report_id == report_id)
        .all()
    )
    cash_sales = 0.0
    for sale_detail, sale_info_item in report_sale_details:
        amount = sale_detail.amount or 0
        sale_type = (
            sale_info_item.type
            if sale_info_item and sale_info_item.type
            else sale_detail.type
        )
        if sale_type == "Cash":
            cash_sales += amount
    if cash_sales > 0:
        logger.info(f"Found cash sales from report_sale_detail: {cash_sales}")
        return cash_sales
    logger.info(
        f"No cash sales found in report_sale_detail, using fallback: {fallback_value}"
    )
    return fallback_value


def calculate_sales_from_report_sale_detail(report_draft_id):
    """Calculate sales for a report draft based on report_sale_detail table."""
    logger.info(
        f"Calculating sales from report_sale_detail for draft {report_draft_id}"
    )
    sales_data = (
        db.session.query(
            SaleInfo.value_name,
            SaleInfo.type,
            db.func.sum(ReportSaleDetail.amount).label("total_amount"),
        )
        .join(ReportSaleDetail, SaleInfo.sale_id == ReportSaleDetail.sale_id)
        .join(ReportDraft, ReportDraft.id == ReportSaleDetail.report_id)
        .filter(ReportSaleDetail.report_id == report_draft_id)
        .group_by(SaleInfo.value_name, SaleInfo.type)
        .all()
    )
    report_draft = ReportDraft.query.get(report_draft_id)
    cash_sales = (report_draft.cash_sales or 0.0) if report_draft else 0.0
    sales_totals = {}
    shop_sales_total = 0.0
    delivery_sales_total = 0.0
    cash_found_in_data = False
    for value_name, sale_type, amount in sales_data:
        if value_name and amount:
            sales_totals[value_name] = float(amount) or 0.0
            if sale_type == "Delivery":
                delivery_sales_total += sales_totals[value_name]
            elif sale_type == "Cash":
                shop_sales_total += sales_totals[value_name]
                if value_name == "cash_sales":
                    cash_found_in_data = True
            else:
                shop_sales_total += sales_totals[value_name]
    if cash_sales > 0:
        sales_totals["cash_sales"] = cash_sales
        if not cash_found_in_data:
            shop_sales_total += cash_sales
    total_sales = shop_sales_total + delivery_sales_total
    logger.info(f"Calculated sales totals: {sales_totals}")
    return {
        "sales_totals": sales_totals,
        "shop_sales": shop_sales_total,
        "delivery_sales": delivery_sales_total,
        "cash_sales": cash_sales,
        "total_sales": total_sales,
    }


def update_report_draft_sales_from_detail(report_draft):
    """Update report_draft sales fields from report_sale_detail table."""
    logger.info(
        f"Updating sales for draft {report_draft.id} from report_sale_detail")
    sales_data = calculate_sales_from_report_sale_detail(report_draft.id)
    for value_name, amount in sales_data["sales_totals"].items():
        if hasattr(report_draft, value_name):
            setattr(report_draft, value_name, amount)
    report_draft.shop_sales = sales_data["shop_sales"]
    report_draft.delivery_sales = sales_data["delivery_sales"]
    report_draft.total_sales = sales_data["total_sales"]


def recalculate_report(report_to_update, *, commit=True):
    """Recalculate derived sales and balances for a report/draft object."""
    try:
        report_to_update.shop_sales = (
            (report_to_update.cash_sales or 0.0)
            + (report_to_update.visa_sales or 0.0)
            + (report_to_update.alipay_sales or 0.0)
            + (report_to_update.wechat_sales or 0.0)
            + (report_to_update.master_sales or 0.0)
            + (report_to_update.unionpay_sales or 0.0)
            + (report_to_update.amex_sales or 0.0)
            + (report_to_update.octopus_sales or 0.0)
        )

        report_to_update.delivery_sales = (
            (report_to_update.foodpanda_sales or 0.0)
            + (report_to_update.keeta_sales or 0.0)
            + (report_to_update.openrice_sales or 0.0)
        )
        report_to_update.total_sales = (report_to_update.shop_sales or 0.0) + (
            report_to_update.delivery_sales or 0.0
        )

        opening_balance = report_to_update.opening_balance or 0.0
        cash_addition = report_to_update.cash_addition or 0.0
        expenses = report_to_update.expenses or 0.0
        bank_deposit = report_to_update.bank_deposit or 0.0
        cash_sales = get_cash_sales_from_detail(
            report_to_update.id,
            fallback_value=report_to_update.cash_sales or 0.0)
        report_to_update.closing_balance = (
            opening_balance + cash_addition + cash_sales - expenses - bank_deposit
        ) + (report_to_update.discrepancy_amount or 0.0)
        if commit:
            db.session.commit()
        return report_to_update
    except Exception as e:
        logger.error(f"Error recalculating report: {str(e)}")
        if commit:
            db.session.rollback()
        return None


def propagate_opening_balance_to_next_day_draft(previous_report):
    """Keep the next day's draft in sync when the previous day's closing changes."""
    if previous_report.closing_balance is None:
        return None

    next_day = previous_report.transaction_date + timedelta(days=1)
    next_day_draft = (
        ReportDraft.query.filter(
            ReportDraft.company == previous_report.company,
            ReportDraft.transaction_date == next_day,
            ReportDraft.status == "draft",
        )
        .order_by(ReportDraft.date.desc())
        .first()
    )

    if not next_day_draft:
        return None

    next_day_draft.opening_balance = previous_report.closing_balance
    next_day_draft.adjusted_opening_balance = (
        (next_day_draft.opening_balance or 0.0)
        + (next_day_draft.cash_addition or 0.0)
    )
    return recalculate_report(next_day_draft, commit=False)


def sync_same_day_draft_after_deposit_change(report_to_update, new_bank_deposit):
    """Keep a same-day draft aligned when a posted report deposit is corrected."""
    same_day_draft = (
        ReportDraft.query.filter(
            ReportDraft.company == report_to_update.company,
            ReportDraft.transaction_date == report_to_update.transaction_date,
            ReportDraft.status == "draft",
        )
        .order_by(ReportDraft.date.desc())
        .first()
    )

    if not same_day_draft:
        return None

    same_day_draft.bank_deposit = new_bank_deposit
    return recalculate_report(same_day_draft, commit=False)


def update_report_after_deposit_change(report_to_update, new_bank_deposit):
    """Persist a deposit edit against the canonical report and dependent draft data."""
    report_to_update.bank_deposit = new_bank_deposit
    recalculated_report = recalculate_report(report_to_update, commit=False)
    if recalculated_report is None:
        db.session.rollback()
        return None

    report_v2 = ReportV2.query.filter_by(report_id=report_to_update.id).first()
    if report_v2:
        report_v2.cash_deposit = new_bank_deposit
        report_v2.starting_balance = report_to_update.opening_balance
        report_v2.opening_balance = report_to_update.opening_balance
        report_v2.adjusted_opening_balance = report_to_update.adjusted_opening_balance

    sync_same_day_draft_after_deposit_change(report_to_update, new_bank_deposit)
    propagate_opening_balance_to_next_day_draft(report_to_update)
    db.session.commit()
    return recalculated_report
