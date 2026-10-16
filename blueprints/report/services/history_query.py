"""Report history's list - the Jinja page's and the Petty Cash API's."""

from datetime import datetime

from blueprints.shared.entity_display import build_entity_acronym
from blueprints.xero.services.publish_errors import latest_publish_reason_items
from blueprints.xero.services.publish_resolution import annotate_resolution
from models.db import Entity, Report
from utils.entity import ensure_hk_timezone


#: The history page's filter chips -> the Status pill labels each one keeps.
STATUS_FILTERS = {
    "draft": ("Draft",),
    "submitted": ("Submitted",),
    "published": ("Published to Xero",),
    "failed": ("Publish failed", "Publishing to Xero"),
}


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


def _status_clause(status):
    """``report_status()``'s pills as SQL, so the filter runs before the page is cut."""
    from sqlalchemy import and_, or_

    draft = Report.status == "draft"
    in_xero = Report.xero_integrated.is_(True)
    not_in_xero = or_(Report.xero_integrated.is_(None), Report.xero_integrated.is_(False))
    working = Report.publishing_status.in_(("failed", "publishing"))
    return {
        "draft": draft,
        "published": and_(~draft, in_xero),
        "failed": and_(~draft, not_in_xero, working),
        "submitted": and_(~draft, not_in_xero, ~working),
    }[status]


def get_entity_report_history(
    entity_id,
    start_date="",
    end_date="",
    page=1,
    report_id=None,
    per_page=10,
    uploaded_by=None,
    status=None,
):
    """One page of a company's reports, newest day first. ``status`` narrows the list to one
    Status pill (the history page's filter chips): ``draft``, ``submitted``, ``published`` or
    ``failed`` - the tones report_status() gives. A date range needs both dates (one alone is
    ignored, as the page always did).

    Filtered, counted and cut in SQL; the submitter comes with each row (``Report.creator`` is
    joined), and a failed row's publish reasons - which may ask Xero - are worked out only for the
    rows on the page (2026-10-15: it used to load every report and resolve every failed one)."""
    if start_date and end_date and start_date > end_date:
        raise ValueError("Start date cannot be after end date.")

    query = Report.query.filter(Report.company == entity_id)
    if start_date and end_date:
        query = query.filter(Report.transaction_date >= start_date, Report.transaction_date <= end_date)
    if report_id:
        query = query.filter(Report.id == report_id)
    if uploaded_by:
        query = query.filter(Report.uploaded_by == uploaded_by)
    if status:
        query = query.filter(_status_clause(status))

    total_count = query.order_by(None).count()
    total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
    rows = query.order_by(Report.transaction_date.desc()).offset((page - 1) * per_page).limit(per_page).all()

    # Shared across the page so live Xero contacts are fetched at most once (one company).
    resolution_cache = {}
    report_history = []
    for report in rows:
        is_draft = (getattr(report.status, "value", report.status) or "submitted") == "draft"
        failed = getattr(report.publishing_status, "value", report.publishing_status) == "failed"
        histories = list(report.report_histories) if failed else []
        report_history.append(_to_report_history_item({
            "id": report.id,
            "transaction_date": report.transaction_date,
            "date": ensure_hk_timezone(report.date),
            "status": report.status or "submitted",
            "current_section": report.current_section,
            "submitted_at": ensure_hk_timezone(report.submitted_at) if report.submitted_at else None,
            "published_at": ensure_hk_timezone(report.published_at) if report.published_at else None,
            "uploaded_by": report.uploaded_by,
            "first_name": (report.creator.first_name or "") if report.creator else "",
            "xero_integrated_yes": report.xero_integrated_yes or False,
            "publishing_status": report.publishing_status,
            "publish_reasons": (
                annotate_resolution(report.company, latest_publish_reason_items(histories),
                                    report_id=report.id, cache=resolution_cache)
                if failed else []
            ),
            "total_sales": report.total_sales or 0.0,
            "expenses": report.expenses or 0.0,
            "report_histories": histories,
            "is_report": not is_draft,
            "is_draft": is_draft,
        }))

    # The newest day of any status, a draft included (the page offers Delete on it).
    latest_report = (
        Report.query.with_entities(Report.id, Report.transaction_date)
        .filter(Report.company == entity_id)
        .order_by(Report.transaction_date.desc())
        .first()
    )

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
