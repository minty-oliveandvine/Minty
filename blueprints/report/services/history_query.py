"""Report history routes."""

from datetime import datetime
from typing import Any, cast

from loguru import logger
from sqlalchemy.orm import joinedload

from blueprints.shared.entity_display import build_entity_acronym
from blueprints.xero.services.publish_errors import latest_publish_reason_items
from blueprints.xero.services.publish_resolution import annotate_resolution
from models.db import Entity, Report, ReportDraft, User
from utils.entity import ensure_hk_timezone


def _to_report_history_item(data):
    if not isinstance(data, dict):
        raise TypeError("Report history row must be a dict")

    class ReportHistoryItem:
        def __init__(self, payload):
            for key, value in payload.items():
                setattr(self, key, value)
            if not hasattr(self, "report_histories") or self.report_histories is None:
                self.report_histories = []

    return ReportHistoryItem(data)


def get_entity_report_history(
    entity_id,
    start_date="",
    end_date="",
    page=1,
    report_id=None,
    per_page=10,
    uploaded_by=None,
):
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    report_query = Report.query.options(
        joinedload(cast(Any, Report.report_histories))
    ).filter(Report.company == entity_id)
    draft_query = ReportDraft.query.options(
        joinedload(cast(Any, ReportDraft.report_history_drafts))
    ).filter(ReportDraft.company == entity_id)

    if start_date and end_date:
        report_query = report_query.filter(
            Report.transaction_date >= start_date,
            Report.transaction_date <= end_date,
        )
        draft_query = draft_query.filter(
            ReportDraft.transaction_date >= start_date,
            ReportDraft.transaction_date <= end_date,
        )

    if report_id:
        report_query = report_query.filter(Report.id == report_id)
        draft_query = draft_query.filter(ReportDraft.id == report_id)

    if uploaded_by:
        report_query = report_query.filter(Report.uploaded_by == uploaded_by)
        draft_query = draft_query.filter(ReportDraft.uploaded_by == uploaded_by)

    all_reports = report_query.all()
    all_drafts = draft_query.all()

    logger.info(
        f"Query results - Reports found: {len(all_reports)}, Drafts found: {len(all_drafts)}"
    )

    merged_reports = {}
    nov5_reference = datetime(2025, 11, 5).date()
    # Shared across all reports on the page so live Xero contacts are fetched
    # at most once (every report here belongs to the same entity).
    resolution_cache = {}

    for report in all_reports:
        user = User.query.filter_by(username=report.uploaded_by).first()
        report_histories_list = (
            list(report.report_histories) if report.report_histories else []
        )
        report_date = ensure_hk_timezone(report.date)

        merged_reports[report.id] = {
            "id": report.id,
            "transaction_date": report.transaction_date,
            "date": report_date,
            "status": "posted",
            "uploaded_by": report.uploaded_by,
            "first_name": user.first_name if user else "",
            "xero_integrated_yes": report.xero_integrated_yes or False,
            "publishing_status": report.publishing_status,
            "publish_reasons": (
                annotate_resolution(
                    report.company,
                    latest_publish_reason_items(report_histories_list),
                    report_id=report.id,
                    cache=resolution_cache,
                )
                if report.publishing_status in ("failed", "partially_published")
                else []
            ),
            "total_sales": report.total_sales or 0.0,
            "expenses": report.expenses or 0.0,
            "report_histories": report_histories_list,
            "is_report": True,
            "is_draft": False,
        }

    for draft in all_drafts:
        if draft.id in merged_reports:
            continue

        user = User.query.filter_by(username=draft.uploaded_by).first()
        draft_histories_list = (
            list(draft.report_history_drafts) if draft.report_history_drafts else []
        )
        draft_date = ensure_hk_timezone(draft.date)

        merged_reports[draft.id] = {
            "id": draft.id,
            "transaction_date": draft.transaction_date,
            "date": draft_date,
            "status": draft.status or "draft",
            "uploaded_by": draft.uploaded_by,
            "first_name": user.first_name if user else "",
            "xero_integrated_yes": draft.xero_integrated_yes or False,
            "publishing_status": getattr(draft, "publishing_status", None),
            "publish_reasons": [],
            "total_sales": draft.total_sales or 0.0,
            "expenses": draft.expenses or 0.0,
            "report_histories": draft_histories_list,
            "is_report": False,
            "is_draft": True,
        }

    report_list = list(merged_reports.values())
    report_list.sort(key=lambda item: item["transaction_date"], reverse=True)

    deduped = {}
    for report_item in report_list:
        key = (entity_id, report_item["transaction_date"])
        if key not in deduped:
            deduped[key] = report_item
        else:
            existing = deduped[key]
            if report_item.get("is_report") and not existing.get("is_report"):
                deduped[key] = report_item
            elif report_item.get("is_report") == existing.get(
                "is_report"
            ) and report_item.get("id", "") > existing.get("id", ""):
                deduped[key] = report_item

    report_list = list(deduped.values())
    report_list.sort(key=lambda item: item["transaction_date"], reverse=True)

    nov5_in_merged = [r for r in report_list if r["transaction_date"] == nov5_reference]
    logger.info(
        f"After merge - Total reports: {len(report_list)}, November 5 reports: {len(nov5_in_merged)}"
    )

    total_count = len(report_list)
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    report_history_page = report_list[start_idx:end_idx]

    nov5_in_paginated = [
        r for r in report_history_page if r["transaction_date"] == nov5_reference
    ]
    logger.info(
        f"After pagination (page {page}) - Reports on page: {len(report_history_page)}, November 5 in page: {len(nov5_in_paginated)}"
    )

    report_history = [_to_report_history_item(item) for item in report_history_page]

    latest_report_obj = (
        Report.query.filter(Report.company == entity_id)
        .order_by(Report.transaction_date.desc())
        .first()
    )
    # Draft-only: this is compared against latest_report_obj to decide which
    # of the two is newer, so it must not itself return a posted report.
    latest_draft_obj = (
        Report.query.filter(
            Report.company == entity_id,
            Report.status == "draft",
        )
        .order_by(Report.transaction_date.desc())
        .first()
    )

    if latest_report_obj and latest_draft_obj:
        latest_report = (
            latest_report_obj
            if latest_report_obj.transaction_date >= latest_draft_obj.transaction_date
            else latest_draft_obj
        )
    elif latest_report_obj:
        latest_report = latest_report_obj
    elif latest_draft_obj:
        latest_report = latest_draft_obj
    else:
        latest_report = None

    latest_transaction_date = latest_report.transaction_date if latest_report else None
    latest_report_id = latest_report.id if latest_report else None
    today_date = datetime.now().date()

    entity = Entity.query.get(entity_id)
    entity_acronym = ""
    display_date = None
    if entity and entity.name:
        entity_acronym = build_entity_acronym(entity.name)
        display_date = (
            entity.created_at.date()
            if isinstance(entity.created_at, datetime)
            else entity.created_at
        )

    return {
        "report_history": report_history,
        "latest_transaction_date": latest_transaction_date,
        "latest_report_id": latest_report_id,
        "today_date": today_date,
        "entity": entity,
        "entity_id": entity_id,
        "entity_acronym": entity_acronym,
        "display_date": display_date,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
    }
