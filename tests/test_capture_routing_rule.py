"""The routing rule, and the Pass 1 validation that feeds it.

``decide_destination`` is a pure function, which is the whole point of putting
the decision in Python instead of leaving it to the model: a routing bug is
reproducible and covered by a table, rather than probabilistic and covered by
hoping. This file is that table.

The Pass 1 validation tests below cover the other half — what happens when the
model returns something that is not quite right, which it will.
"""

from __future__ import annotations

import pytest

# models.db FIRST, and deliberately. It imports every model submodule to
# register them with SQLAlchemy, and those submodules do `from models.db import
# db`. Importing a model module before models.db has finished executing
# re-enters it half-initialised and raises "cannot import name ... from
# partially initialized module". ``pettycash/core/blueprint_loader.py`` does the
# same pre-load, for the same reason, with a comment about the day it bit.
import models.db  # noqa: F401  isort:skip

from blueprints.capture.models.capture_draft import (DEST_HOLD, DEST_PAYMENT,
                                                     DEST_PETTY_CASH,
                                                     DEST_REJECTED,
                                                     DOC_TYPE_INVOICE,
                                                     DOC_TYPE_OTHER,
                                                     DOC_TYPE_RECEIPT)
from blueprints.capture.services import capture_ai as ai
from blueprints.capture.services.routing import decide_destination


# --------------------------------------------------------------------------
# Every row of the table in the implementation guide, section 11.4.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "doc_type,petty_cash,bill,expected",
    [
        # A receipt goes to Petty Cash when the company has it.
        (DOC_TYPE_RECEIPT, True, True, DEST_PETTY_CASH),
        (DOC_TYPE_RECEIPT, True, False, DEST_PETTY_CASH),
        # ...and is held, not rejected, when they do not.
        (DOC_TYPE_RECEIPT, False, True, DEST_HOLD),
        # An invoice goes to Payment when the company has it.
        (DOC_TYPE_INVOICE, True, True, DEST_PAYMENT),
        (DOC_TYPE_INVOICE, False, True, DEST_PAYMENT),
        # ...and is held when they do not.
        (DOC_TYPE_INVOICE, True, False, DEST_HOLD),
        # Anything else is rejected regardless of what they own.
        (DOC_TYPE_OTHER, True, True, DEST_REJECTED),
        (DOC_TYPE_OTHER, False, False, DEST_REJECTED),
        # Both modules off: unreachable in practice because the blueprint gate
        # already refused the request, but it must still answer safely.
        (DOC_TYPE_RECEIPT, False, False, DEST_HOLD),
        (DOC_TYPE_INVOICE, False, False, DEST_HOLD),
    ],
)
def test_routing_table(doc_type, petty_cash, bill, expected):
    assert decide_destination(doc_type, petty_cash, bill) == expected


def test_a_module_the_company_lacks_is_never_a_destination():
    """The property that matters most: entitlement cannot leak.

    If this ever fails, a customer is being given a module they did not buy on
    the say-so of a language model.
    """
    for doc_type in (DOC_TYPE_RECEIPT, DOC_TYPE_INVOICE, DOC_TYPE_OTHER):
        assert decide_destination(doc_type, False, True) != DEST_PETTY_CASH
        assert decide_destination(doc_type, True, False) != DEST_PAYMENT


def test_an_unknown_doc_type_is_rejected_not_guessed():
    """A value outside the three we asked for is not routed anywhere real."""
    assert decide_destination("statement", True, True) == DEST_REJECTED
    assert decide_destination("", True, True) == DEST_REJECTED
    assert decide_destination(None, True, True) == DEST_REJECTED


def test_module_lookup_fails_closed(monkeypatch):
    """A database hiccup must not become a way into a module.

    Both false sends everything to 'hold', which is visible, reversible, and
    honest about the fact that we could not tell.

    The lookup is stubbed through ``sys.modules`` rather than by importing the
    real route module and patching an attribute on it. Importing
    ``blueprints.entity.routes.modules`` here would execute its sibling route
    files, whose ``@entity_bp.route`` decorators raise once that blueprint has
    been registered on an app — which it has been, by any test that used the
    ``app`` fixture earlier in the run. ``routing.entity_modules`` imports
    inside the function, so it picks the stub up from ``sys.modules``.
    """
    import sys
    import types

    from blueprints.capture.services import routing

    def boom(*args, **kwargs):
        raise RuntimeError("database is having a moment")

    stub = types.ModuleType("blueprints.entity.routes.modules")
    stub._is_module_enabled = boom
    monkeypatch.setitem(sys.modules, "blueprints.entity.routes.modules", stub)

    assert routing.entity_modules("ent-1") == (False, False)


def test_module_lookup_reports_each_module_separately(monkeypatch):
    """The two modules are independent — a company can hold either, both, or
    (briefly, mid-signup) neither."""
    import sys
    import types

    from blueprints.capture.services import routing

    stub = types.ModuleType("blueprints.entity.routes.modules")
    stub._is_module_enabled = lambda entity_id, code: code == "BILL"
    monkeypatch.setitem(sys.modules, "blueprints.entity.routes.modules", stub)

    assert routing.entity_modules("ent-1") == (False, True)


# --------------------------------------------------------------------------
# Pass 1 validation. Everything here exists because the model gets one of these
# wrong sooner or later.
# --------------------------------------------------------------------------
def test_split_clamps_pages_past_the_end_of_the_document():
    """Unclamped, page 9 of a 3-page PDF crashes pikepdf inside a background
    thread, a long way from the cause."""
    documents = ai._validate_split(
        [
            {
                "page_start": 2,
                "page_end": 9,
                "locator": "x",
                "doc_type": "receipt",
                "doc_type_confidence": 0.9,
                "other_reason": "",
            }
        ],
        page_count=3,
    )
    assert documents[0]["page_start"] == 2
    assert documents[0]["page_end"] == 3


def test_split_fixes_an_end_before_its_start():
    documents = ai._validate_split(
        [
            {
                "page_start": 3,
                "page_end": 1,
                "locator": "",
                "doc_type": "invoice",
                "doc_type_confidence": 0.8,
                "other_reason": "",
            }
        ],
        page_count=3,
    )
    assert documents[0]["page_start"] == 3
    assert documents[0]["page_end"] == 3


def test_split_treats_an_unknown_type_as_other():
    """Dropped would hide it; guessed would be worse. 'other' is honest, and
    the user still sees that something was there."""
    documents = ai._validate_split(
        [
            {
                "page_start": 1,
                "page_end": 1,
                "locator": "",
                "doc_type": "bank_statement",
                "doc_type_confidence": 0.9,
                "other_reason": "",
            }
        ],
        page_count=1,
    )
    assert documents[0]["doc_type"] == DOC_TYPE_OTHER


def test_split_caps_untrusted_text():
    """The locator came off a photograph somebody else supplied. It is capped
    well inside the column's 200 characters."""
    documents = ai._validate_split(
        [
            {
                "page_start": 1,
                "page_end": 1,
                "locator": "A" * 500,
                "doc_type": "receipt",
                "doc_type_confidence": 0.9,
                "other_reason": "B" * 500,
            }
        ],
        page_count=1,
    )
    assert len(documents[0]["locator"]) == 150
    assert len(documents[0]["other_reason"]) == 150


def test_split_returns_documents_in_reading_order():
    """So "Document 2 of 5" matches what the user sees scrolling the file."""
    documents = ai._validate_split(
        [
            {"page_start": 3, "page_end": 3, "locator": "c", "doc_type": "receipt",
             "doc_type_confidence": 0.9, "other_reason": ""},
            {"page_start": 1, "page_end": 1, "locator": "a", "doc_type": "receipt",
             "doc_type_confidence": 0.9, "other_reason": ""},
            {"page_start": 2, "page_end": 2, "locator": "b", "doc_type": "receipt",
             "doc_type_confidence": 0.9, "other_reason": ""},
        ],
        page_count=3,
    )
    assert [d["locator"] for d in documents] == ["a", "b", "c"]


def test_split_survives_junk_entries():
    """A list with a string in it must not take down the upload."""
    documents = ai._validate_split(
        [
            "not a dict",
            None,
            {"page_start": 1, "page_end": 1, "locator": "ok", "doc_type": "receipt",
             "doc_type_confidence": 0.9, "other_reason": ""},
        ],
        page_count=1,
    )
    assert len(documents) == 1
    assert documents[0]["locator"] == "ok"


def test_two_receipts_on_one_page_are_two_documents():
    """The case the whole feature exists for. Both sit on page 1, and the
    locator is the only thing telling Pass 2 which is which."""
    documents = ai._validate_split(
        [
            {"page_start": 1, "page_end": 1, "locator": "top, Starbucks",
             "doc_type": "receipt", "doc_type_confidence": 0.9, "other_reason": ""},
            {"page_start": 1, "page_end": 1, "locator": "bottom, taxi",
             "doc_type": "receipt", "doc_type_confidence": 0.9, "other_reason": ""},
        ],
        page_count=1,
    )
    assert len(documents) == 2
    assert {d["locator"] for d in documents} == {"top, Starbucks", "bottom, taxi"}


def test_a_two_page_invoice_stays_one_document():
    documents = ai._validate_split(
        [
            {"page_start": 1, "page_end": 2, "locator": "CLP invoice",
             "doc_type": "invoice", "doc_type_confidence": 0.95, "other_reason": ""},
        ],
        page_count=2,
    )
    assert len(documents) == 1
    assert (documents[0]["page_start"], documents[0]["page_end"]) == (1, 2)


# --------------------------------------------------------------------------
# Pass 1 must account for every page.
#
# Found in testing: a three-page upload — two receipts and an HK Electric bill
# — came back with TWO documents. Page 3 was simply absent from the reply, so
# no draft was made for it and nothing was logged. The user saw two drafts from
# a three-page file with nothing to explain the third.
# --------------------------------------------------------------------------
def test_the_prompt_demands_every_page_be_accounted_for():
    """A prompt is the only place this can be asked for, so assert it is."""
    assert "ACCOUNT FOR EVERY PAGE" in ai._PASS1_SYSTEM
    assert "Never leave a page out" in ai._PASS1_SYSTEM
    # And that an unidentifiable page is still to be returned, not omitted.
    assert "STILL a document" in ai._PASS1_SYSTEM


def test_a_shortfall_in_coverage_is_detected(monkeypatch, caplog):
    """A prompt is a request, not a guarantee. This is the check that makes a
    shortfall visible instead of silently losing a page."""
    import json

    class FakeInteraction:
        id = "i1"
        status = "completed"
        errors: list = []
        usage = None
        # Three pages in, two documents out — exactly the observed failure.
        output_text = json.dumps({
            "documents": [
                {"page_start": 1, "page_end": 1, "locator": "receipt",
                 "doc_type": "receipt", "doc_type_confidence": 1.0,
                 "other_reason": ""},
                {"page_start": 2, "page_end": 2, "locator": "receipt",
                 "doc_type": "receipt", "doc_type_confidence": 1.0,
                 "other_reason": ""},
            ]
        })

    monkeypatch.setattr(ai, "_get_client", lambda: object())
    monkeypatch.setattr(ai, "_call_model", lambda *a, **k: (FakeInteraction(), None))

    result = ai.split_and_classify(b"%PDF-1.7 pretend", "application/pdf", 3)

    assert len(result.documents) == 2
    # The missing page is recorded rather than passed over.
    assert result.audit["missing_pages"] == [3]


def test_full_coverage_records_nothing_missing(monkeypatch):
    import json

    class FakeInteraction:
        id = "i1"
        status = "completed"
        errors: list = []
        usage = None
        output_text = json.dumps({
            "documents": [
                {"page_start": 1, "page_end": 2, "locator": "invoice",
                 "doc_type": "invoice", "doc_type_confidence": 0.9,
                 "other_reason": ""},
                {"page_start": 3, "page_end": 3, "locator": "receipt",
                 "doc_type": "receipt", "doc_type_confidence": 0.9,
                 "other_reason": ""},
            ]
        })

    monkeypatch.setattr(ai, "_get_client", lambda: object())
    monkeypatch.setattr(ai, "_call_model", lambda *a, **k: (FakeInteraction(), None))

    result = ai.split_and_classify(b"%PDF-1.7 pretend", "application/pdf", 3)
    assert result.audit["missing_pages"] == []
