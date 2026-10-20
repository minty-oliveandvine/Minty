"""What the Petty Cash pages are drawn from (Parts 13-15; docs/features/petty-cash-design.md).

Cheap checks, no database:
- the ``money`` filter writes "HKD 4,800.00" (the user's choice, 2026-10-14);
- the five Daily Closing stages over the wizard's six sections, and the report status tones
  (``report/services/daily_closing.py``, which the Petty Cash API hands minty-petty-cash-web).

The token sheet, template and icon checks went with Flask's HTML frontend (2026-10-20).
"""
from __future__ import annotations

import pytest

from blueprints.report.services.daily_closing import (
    STAGES,
    not_started_progress,
    report_status,
    stage_of,
    stage_progress,
    submitted_progress,
)
from services.helpers.formatter import money


@pytest.mark.parametrize(
    "value, code, expected",
    [
        (4800, "HKD", "HKD 4,800.00"),
        ("1234.5", "HKD", "HKD 1,234.50"),
        (-20, "HKD", "HKD -20.00"),
        (0.1 + 0.2, "HKD", "HKD 0.30"),
        (-0.001, "HKD", "HKD 0.00"),
        (99_999_999_999.99, "SGD", "SGD 99,999,999,999.99"),
        (12, "$", "$ 12.00"),
        (12, "", "12.00"),
        (None, "HKD", ""),
        ("", "HKD", ""),
    ],
)
def test_money(value, code, expected):
    assert money(value, code) == expected


def test_money_refuses_what_is_not_an_amount():
    with pytest.raises(ValueError):
        money("twelve", "HKD")


# --- the five stages over the six sections ------------------------------------------------------


def _states(progress):
    return [(step.stage.key, step.state) for step in progress.steps]


def test_the_five_stages_in_order():
    assert [s.label for s in STAGES] == ["Addition to Drawer", "Sales", "Expenses", "Cash Count", "Close"]
    assert [s.short for s in STAGES] == ["Drawer", "Sales", "Expenses", "Cash Count", "Close"]


@pytest.mark.parametrize(
    "section, stage",
    [("opening", "drawer"), ("sales", "sales"), ("expenses", "expenses"), ("deposit", "cash_count"),
     ("cash_count", "cash_count"), ("ending", "close"), ("submitted", None), (None, None), ("", None)],
)
def test_stage_of(section, stage):
    found = stage_of(section)
    assert (found.key if found else None) == stage


def test_a_fresh_draft_is_on_the_drawer():
    progress = stage_progress(None, None)
    assert progress.done == 0 and progress.next.key == "drawer"
    assert _states(progress)[0] == ("drawer", "current")


def test_deposit_done_is_not_cash_count_done():
    progress = stage_progress("cash_count", ["opening", "sales", "expenses", "deposit"])
    assert progress.done == 3
    assert progress.next.key == "cash_count"
    assert _states(progress) == [("drawer", "done"), ("sales", "done"), ("expenses", "done"),
                                 ("cash_count", "current"), ("close", "upcoming")]


def test_the_deposit_section_lands_in_cash_count():
    assert stage_progress("deposit", ["opening", "sales", "expenses"]).next.key == "cash_count"


def test_going_back_to_a_done_stage_draws_it_current():
    progress = stage_progress("sales", ["opening", "sales", "expenses"])
    assert progress.done == 3
    assert _states(progress)[1] == ("sales", "current")
    assert _states(progress)[2] == ("expenses", "done")


def test_an_unknown_section_resumes_at_the_first_stage_still_to_do():
    assert stage_progress("submitted", ["opening", "sales"]).next.key == "expenses"
    assert stage_progress("submitted", ["opening", "sales", "expenses", "deposit", "cash_count", "ending"]).next is None


def test_not_started_and_submitted():
    assert not_started_progress().done == 0 and not_started_progress().next.key == "drawer"
    assert submitted_progress().done == 5 and submitted_progress().next is None
    assert {s.state for s in submitted_progress().steps} == {"done"}


@pytest.mark.parametrize(
    "args, expected",
    [
        (("draft",), ("Draft", "neutral")),
        (("draft", "completed", True), ("Draft", "neutral")),
        (("submitted",), ("Submitted", "info")),
        ((None,), ("Submitted", "info")),
        (("submitted", "unpublished", False), ("Submitted", "info")),
        (("submitted", "publishing"), ("Publishing to Xero", "info")),
        # edited after publishing: Xero holds an older copy, so it is Submitted again
        (("submitted", "completed", False), ("Submitted", "info")),
        (("submitted", "completed", True), ("Published to Xero", "success")),
        (("submitted", None, True), ("Published to Xero", "success")),
        (("submitted", "failed"), ("Publish failed", "danger")),
    ],
)
def test_report_status(args, expected):
    assert report_status(*args) == expected
