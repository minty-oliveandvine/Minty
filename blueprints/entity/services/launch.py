"""What the Petty Cash launch page draws (Part 15.6a / 15.15a, the Action Dashboard).

"Launch state derives from the open report (stage, last save) and the gate rule (previous day
finalised)." The rules are the ones the old dashboard's calendar enforced in the browser, now
decided here once:

- an open draft is the work: Continue it (the EARLIEST draft - an earlier day is finished first);
- no draft and no submitted report: first use - start today;
- otherwise the next day is the day after the latest submitted report (consecutive days, no gaps):
  after today means today's report is done; before today means the gate - "Finish Sun 4 Oct first";
- starting a day whose previous day banked a deposit first asks "Before You Start" (was that deposit
  made as stated?), as the old Start New Report did.

Queries only what the page shows: the earliest draft, the 3 latest submitted reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from blueprints.report.services.daily_closing import (
    StageProgress,
    not_started_progress,
    report_status,
    stage_progress,
    submitted_progress,
)
from models.db import Report, User, tz

RECENT = 3


@dataclass(frozen=True)
class RecentReport:
    id: str
    transaction_date: date
    closing_balance: float
    bank_deposit: float
    status: tuple[str, str]
    submitted_by: str | None


@dataclass(frozen=True)
class LaunchState:
    #: "in_progress" | "not_started" | "done" | "first_use"
    state: str
    #: The day the work card is about.
    work_date: date
    today: date
    progress: StageProgress
    #: The open draft (in_progress only).
    draft: Report | None
    #: When the draft was last saved, in Hong Kong time (in_progress only).
    saved_at: datetime | None
    #: The day that must be finished before today's can start - None when there is no gate.
    gate_date: date | None
    recent: tuple[RecentReport, ...]
    #: The latest submitted report (None on first use).
    latest: RecentReport | None
    #: Starting asks "Before You Start": the previous day banked a deposit.
    confirm_deposit: bool


def _hk(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz)


def _recent(entity_id: str) -> tuple[RecentReport, ...]:
    rows = (
        Report.query.filter(Report.company == str(entity_id), Report.status != "draft")
        .order_by(Report.transaction_date.desc())
        .limit(RECENT)
        .all()
    )
    names: dict[str, str | None] = {}
    usernames = {r.uploaded_by for r in rows if r.uploaded_by}
    if usernames:
        for user in User.query.filter(User.username.in_(usernames)).all():
            names[user.username] = (user.first_name or "").strip() or None
    return tuple(
        RecentReport(
            id=str(r.id),
            transaction_date=r.transaction_date,
            closing_balance=r.closing_balance or 0.0,
            bank_deposit=r.bank_deposit or 0.0,
            status=report_status(r.status, r.publishing_status, r.xero_integrated_yes),
            submitted_by=names.get(r.uploaded_by),
        )
        for r in rows
    )


def launch_state(entity_id: str, today: date | None = None) -> LaunchState:
    today = today or datetime.now(tz).date()
    draft = (
        Report.query.filter(Report.company == str(entity_id), Report.status == "draft")
        .order_by(Report.transaction_date.asc())
        .first()
    )
    recent = _recent(entity_id)
    latest = recent[0] if recent else None

    if draft is not None:
        work_date = draft.transaction_date
        return LaunchState(
            state="in_progress",
            work_date=work_date,
            today=today,
            progress=stage_progress(draft.current_section, draft.completed_sections),
            draft=draft,
            saved_at=_hk(draft.updated_at or draft.created_at),
            gate_date=work_date if work_date < today else None,
            recent=recent,
            latest=latest,
            confirm_deposit=False,
        )
    if latest is None:
        return LaunchState("first_use", today, today, not_started_progress(), None, None, None, recent, None, False)

    next_day = latest.transaction_date + timedelta(days=1)
    if next_day > today:
        return LaunchState("done", latest.transaction_date, today, submitted_progress(), None, None, None, recent, latest, False)
    return LaunchState(
        state="not_started",
        work_date=next_day,
        today=today,
        progress=not_started_progress(),
        draft=None,
        saved_at=None,
        gate_date=next_day if next_day < today else None,
        recent=recent,
        latest=latest,
        confirm_deposit=latest.bank_deposit > 0,
    )



def greeting(now: datetime) -> str:
    """The launch page's greeting by the Hong Kong hour (15.6a)."""
    if now.hour < 12:
        return "Good morning"
    if now.hour < 18:
        return "Good afternoon"
    return "Good evening"
