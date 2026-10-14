"""The Daily Closing as the redesigned Petty Cash pages draw it (Part 15.9 / 15.15).

The five stages - Addition to Drawer, Sales, Expenses, Cash Count, Close - drawn over the six
sections the report wizard still keeps in ``report.current_section`` / ``completed_sections``
(Bank Deposit is folded into Cash Count, D15-05; the keys and URLs stay as they are):

- opening    -> Addition to Drawer
- sales      -> Sales
- expenses   -> Expenses
- deposit    -> Cash Count ... (Bank Deposit is the first block of the Cash Count page)
- cash_count -> Cash Count ... done only once the cash count itself is done
- ending     -> Close

Pure: the launch page, the stage pages and their tests only draw what this says. A Python port
of minty-petty-cash-web's ``lib/dailyClosing.ts`` (redesign/part-15), so both apps agree.
"""
from __future__ import annotations

from dataclasses import dataclass

SECTIONS = ("opening", "sales", "expenses", "deposit", "cash_count", "ending")


@dataclass(frozen=True)
class Stage:
    key: str
    #: The stage's name ("Next: Addition to Drawer").
    label: str
    #: The Step progress label - Part 15.9's short form.
    short: str
    #: The wizard sections inside the stage, in order; the first is where the stage opens.
    sections: tuple[str, ...]
    #: The section whose completion completes the stage.
    done_when: str


STAGES: tuple[Stage, ...] = (
    Stage("drawer", "Addition to Drawer", "Drawer", ("opening",), "opening"),
    Stage("sales", "Sales", "Sales", ("sales",), "sales"),
    Stage("expenses", "Expenses", "Expenses", ("expenses",), "expenses"),
    Stage("cash_count", "Cash Count", "Cash Count", ("deposit", "cash_count"), "cash_count"),
    Stage("close", "Close", "Close", ("ending",), "ending"),
)

#: The wizard page each section is (the routes keep their old names and URLs).
SECTION_ENDPOINT = {
    "opening": "report.report_opening",
    "sales": "report.report_sale",
    "expenses": "report.report_expense",
    "deposit": "report.report_deposit",
    "cash_count": "report.report_cash_count",
    "ending": "report.report_ending",
}
#: The page each stage opens: Cash Count's is the cash_count page (the deposit is its first block).
STAGE_SECTION = {"drawer": "opening", "sales": "sales", "expenses": "expenses", "cash_count": "cash_count", "close": "ending"}


def stage_of(section: str | None) -> Stage | None:
    """The stage a wizard section belongs to; None for no section or a key the wizard does not use."""
    if not section:
        return None
    for stage in STAGES:
        if section in stage.sections:
            return stage
    return None


@dataclass(frozen=True)
class StageStep:
    stage: Stage
    #: "done" | "current" | "upcoming"
    state: str


@dataclass(frozen=True)
class StageProgress:
    steps: tuple[StageStep, ...]
    #: How many of the five are done ("3 of 5 done").
    done: int
    #: Where Continue lands - None once every stage is done.
    next: Stage | None

    @property
    def total(self) -> int:
        return len(self.steps)


def stage_progress(current_section: str | None, completed_sections) -> StageProgress:
    """An open report's progress over the five stages.

    "Next" is where Continue lands: the wizard's resume opens ``current_section`` (or the first
    section when there is none), so it is that section's stage - even when the person went back to
    a stage already done. A stage is done when its ``done_when`` section is completed; the current
    stage is drawn as current whether done or not. ``completed_sections`` may be None (legacy
    drafts hold NULL).
    """
    completed = set(completed_sections or ())

    def is_done(stage: Stage) -> bool:
        return stage.done_when in completed

    done = sum(1 for stage in STAGES if is_done(stage))
    current = stage_of(current_section)
    if current is None:
        if current_section:
            # A key the wizard no longer uses ("submitted" on a reopened report): the first stage
            # still to do, else none.
            current = next((stage for stage in STAGES if not is_done(stage)), None)
        else:
            current = STAGES[0]
    return StageProgress(
        steps=tuple(
            StageStep(stage, "current" if stage is current else "done" if is_done(stage) else "upcoming")
            for stage in STAGES
        ),
        done=done,
        next=current,
    )


def not_started_progress() -> StageProgress:
    """No report yet: every stage ahead."""
    return StageProgress(tuple(StageStep(stage, "upcoming") for stage in STAGES), 0, STAGES[0])


def submitted_progress() -> StageProgress:
    """A submitted day: every stage done."""
    return StageProgress(tuple(StageStep(stage, "done") for stage in STAGES), len(STAGES), None)


def report_status(status, publishing_status=None, xero_integrated_yes=False) -> tuple[str, str]:
    """A report's Status pill: (label, tone), the tones of Part 13 / Stage 4.

    Draft is Neutral; Submitted is Info in every module (S4-03); Published to Xero is Success
    (completed, nothing further needed); a failed publish is Danger (failures only); a publish
    under way is Info ("Xero pending", 15.12e).

    "Published" is ``xero_integrated`` - what Xero holds is this report as it stands. An edit
    after publishing clears it while ``publishing_status`` stays ``completed``, and that report
    reads Submitted again (it needs publishing again), as the old badge had it.
    """
    status = getattr(status, "value", status)
    publishing_status = getattr(publishing_status, "value", publishing_status)
    if (status or "submitted") == "draft":
        return "Draft", "neutral"
    if xero_integrated_yes:
        return "Published to Xero", "success"
    if publishing_status == "failed":
        return "Publish failed", "danger"
    if publishing_status == "publishing":
        return "Publishing to Xero", "info"
    return "Submitted", "info"


def stage_hrefs(entity_id, day, report_id=None, edit=False, report_edit=False) -> dict[str, str]:
    """Where each stage opens for one day's report: {stage key: url}. A submitted report's stages
    are addressed by its id (the wizard's ``/reports/<id>/<step>`` routes), with the edit flags the
    wizard reads (``edit=true``, ``report_edit=true``)."""
    from flask import url_for

    query = {"transaction_date": day.isoformat() if hasattr(day, "isoformat") else day}
    if edit:
        query["edit"] = "true"
    if report_edit:
        query["report_edit"] = "true"
    if report_id:
        query["id"] = str(report_id)
    return {
        stage.key: url_for(SECTION_ENDPOINT[STAGE_SECTION[stage.key]], entity_id=str(entity_id), **query)
        for stage in STAGES
    }
