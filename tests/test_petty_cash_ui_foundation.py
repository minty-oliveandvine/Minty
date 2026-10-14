"""The redesigned Petty Cash pages' foundation (Parts 13-15; docs/features/petty-cash-design.md).

Cheap source checks, no database:
- minty_tokens.css carries the Part 13 values that matter (the Primary CTA chain, the scrim, the
  radius and type floor) - it is a copy of @minty/shared's tokens.css and must not drift;
- no raw colour outside that sheet (Part 13 V-01): pc_ui.css and templates/petty_cash/ bind roles;
- the icons are Material Symbols Rounded (D-20), never Outlined, and no page loads Tailwind's CDN;
- the ``money`` filter writes "HKD 4,800.00" (the user's choice, 2026-10-14);
- the five Daily Closing stages over the wizard's six sections, and the report status tones.
"""
from __future__ import annotations

import re
from pathlib import Path

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

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "static" / "css" / "minty_tokens.css"
PC_CSS = ROOT / "static" / "css" / "pc_ui.css"
PC_TEMPLATES = ROOT / "templates" / "petty_cash"
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _tokens() -> dict[str, str]:
    """The FIRST (light) value of every custom property in the sheet."""
    found: dict[str, str] = {}
    for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", TOKENS.read_text(encoding="utf-8")):
        found.setdefault(name, value.strip())
    return found


@pytest.mark.parametrize(
    "name, value",
    [
        # Primary CTA: Minty Action, hover, pressed (D-02, S4-01) - never brand 400 as a fill
        ("--minty-mint-action-500", "#3cbcc3"),
        ("--minty-mint-action-600", "#35b2b9"),
        ("--minty-mint-action-700", "#2fa4ab"),
        ("--color-action-primary", "var(--minty-mint-action-500)"),
        ("--color-action-primary-hover", "var(--minty-mint-action-600)"),
        ("--color-action-primary-pressed", "var(--minty-mint-action-700)"),
        ("--color-brand-primary", "var(--minty-brand-400)"),
        ("--minty-brand-400", "#54d3da"),
        # scrim #111313 at 48% (S4-04)
        ("--color-overlay-scrim", "rgb(17 19 19 / 0.48)"),
        # buttons/inputs radius 12; the 12px type floor
        ("--radius-lg", "12px"),
        ("--text-caption", "12px"),
        ("--text-label", "12px"),
        ("--text-button", "14px"),
        # Submitted is Info (blue) in every module
        ("--color-status-info-ink", "var(--minty-blue-800)"),
    ],
)
def test_the_token_sheet_carries_part_13(name, value):
    assert _tokens()[name] == value


def test_every_semantic_role_is_defined_at_root_not_in_a_tailwind_theme_block():
    source = TOKENS.read_text(encoding="utf-8")
    assert not re.search(r"^@theme\s*\{", source, re.M)  # Flask has no Tailwind to read it
    assert "--color-surface-page:" in source


def test_no_raw_colour_outside_the_token_sheet():
    offenders = []
    for path in [PC_CSS, *PC_TEMPLATES.rglob("*.html")]:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # entity references (&#8230;) are text, not colours
            for match in HEX.findall(re.sub(r"&#x?[0-9a-fA-F]+;", "", line)):
                offenders.append(f"{path.relative_to(ROOT)}:{lineno} {match}")
    assert offenders == []


def test_icons_are_rounded_and_there_is_no_tailwind_cdn():
    for path in PC_TEMPLATES.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        assert "Outlined" not in source and "material-symbols-outlined" not in source, path.name
        assert "cdn.tailwindcss.com" not in source, path.name
    assert "Material+Symbols+Rounded" in (PC_TEMPLATES / "base.html").read_text(encoding="utf-8")


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
