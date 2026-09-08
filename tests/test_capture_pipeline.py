"""The background pipeline: one upload in, N drafts out.

The model is stubbed throughout. A test that reached Google would be a test of
Google; these are about OUR decisions — how many calls we make, when we stop
making them, and what ends up in the database.

The most important test here is ``test_a_bank_statement_costs_one_call_not_
eleven``. It asserts a call COUNT, because the whole two-pass design exists to
keep that number small, and a refactor that quietly reintroduced per-document
extraction on a rejected upload would pass every other test in this file.

NOTE ON IMPORTS
Project modules are imported INSIDE the fixtures and tests, never at module
level. ``tests/conftest.py`` clears cached ``models`` and ``blueprints``
modules before building the app, so anything bound at collection time is a
different object from the one the app is wired to — and the symptom is a
baffling "current Flask app is not registered with this 'SQLAlchemy' instance".
Every DB-backed test in this suite does it this way.
"""

from __future__ import annotations

import io
from uuid import uuid4

import pytest


# --------------------------------------------------------------------------
# Helpers that need no project imports
# --------------------------------------------------------------------------
def make_pdf(pages: int) -> bytes:
    import pikepdf

    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page(page_size=(595, 842))
    buffer = io.BytesIO()
    pdf.save(buffer)
    return buffer.getvalue()


def doc(page_start=1, page_end=1, doc_type="receipt", locator="", confidence=0.9):
    return {
        "page_start": page_start,
        "page_end": page_end,
        "locator": locator,
        "doc_type": doc_type,
        "doc_type_confidence": confidence,
        "other_reason": "a bank statement" if doc_type == "other" else "",
    }


def suggestion(amount="120.00", date="2026-09-03"):
    """A Pass 2 reply in the shape ``validate_suggestion`` produces."""

    def field(value, confidence=0.95):
        return {
            "value": value,
            "confidence": confidence,
            "band": "high" if value else "low",
            "applied": bool(value),
        }

    return {
        "supplier": dict(field("SF Express"), contact_id="con-sf"),
        "account": dict(
            field("5100 Courier"), account_id="acc-1", code="5100", name="Courier"
        ),
        "amount": field(amount),
        "description": field("Courier delivery"),
        "document_date": field(date),
        "currency": "HKD",
        "entity_currency": "HKD",
    }


CONTEXT = {
    "entity": {"id": "ent-1", "name": "Vine Ltd", "country": "HK", "currency": "HKD"},
    "accounts": [{"id": "acc-1", "code": "5100", "name": "Courier"}],
    "contacts": [{"id": "con-sf", "name": "SF Express"}],
}


class Rig:
    """Everything a test needs, imported after the app exists.

    Holds the module objects rather than re-importing in each test, so a test
    body reads as the behaviour it is checking and not as plumbing.
    """

    def __init__(self, monkeypatch):
        from blueprints.capture.models.capture_draft import CaptureDraft
        from blueprints.capture.models.capture_upload import CaptureUpload
        from blueprints.capture.services import (capture_ai, pipeline, routing,
                                                 storage)
        from models.db import db

        self.monkeypatch = monkeypatch
        self.ai = capture_ai
        self.pipeline = pipeline
        self.routing = routing
        self.storage = storage
        self.db = db
        self.CaptureDraft = CaptureDraft
        self.CaptureUpload = CaptureUpload

        self.files = {}
        self.pass1 = 0
        self.pass2 = 0

    # ---------------------------------------------------------------- stubs
    def stub_storage(self):
        def put_bytes(key, data, mime):
            self.files[key] = data
            return key

        self.monkeypatch.setattr(self.storage, "put_bytes", put_bytes)
        self.monkeypatch.setattr(self.storage, "get_bytes", self.files.get)

    def stub_context(self):
        self.monkeypatch.setattr(
            self.ai,
            "build_entity_context",
            lambda entity_id, for_invoice=False: CONTEXT,
        )
        # Downsizing is Pillow's job and is covered elsewhere; keep the bytes
        # intact so page counts stay meaningful.
        self.monkeypatch.setattr(
            self.ai, "prepare_document", lambda data, mime: (data, mime)
        )

    def stub_model(self, documents, suggestions=None, reason=None):
        def split(document, mime, page_count):
            self.pass1 += 1
            return self.ai.SplitResult(
                documents=documents or None,
                reason=None if documents else self.ai.REASON_NO_DOCUMENT_FOUND,
                audit={"model_id": "test", "latency_ms": 5,
                       "input_tokens": 100, "output_tokens": 20},
            )

        def extract(document, mime, context, doc_type, locator=""):
            self.pass2 += 1
            return self.ai.Extraction(
                suggestions=suggestion() if suggestions is None else suggestions,
                reason=reason,
                audit={"model_id": "test", "latency_ms": 5,
                       "input_tokens": 200, "output_tokens": 40},
            )

        self.monkeypatch.setattr(self.ai, "split_and_classify", split)
        self.monkeypatch.setattr(self.ai, "extract", extract)

    def modules(self, petty_cash=True, bill=True):
        self.monkeypatch.setattr(
            self.routing, "entity_modules", lambda entity_id: (petty_cash, bill)
        )

    # ------------------------------------------------------------- fixtures
    def seed_upload(self, page_count=1, bypass=False, entity_id="ent-1"):
        """A committed capture_upload row with its bytes in the fake store.

        The entity and user foreign keys are not satisfied — SQLite does not
        enforce them by default, and these tests are about the pipeline, not
        about referential integrity, which the migration's constraints cover.
        """
        upload_id = str(uuid4())
        key = f"capture/{entity_id}/2026/09/{upload_id}/original.pdf"
        self.files[key] = make_pdf(page_count)
        upload = self.CaptureUpload(
            id=upload_id,
            entity_id=entity_id,
            uploaded_by="user-1",
            original_filename="receipts.pdf",
            mime_type="application/pdf",
            byte_size=len(self.files[key]),
            page_count=page_count,
            content_sha256="0" * 64,
            s3_key=key,
            status="queued",
            bypass_classification=bypass,
        )
        self.db.session.add(upload)
        self.db.session.commit()
        return upload

    def drafts_for(self, upload):
        return (
            self.CaptureDraft.query.filter_by(upload_id=upload.id)
            .order_by(self.CaptureDraft.sequence)
            .all()
        )

    def run(self, upload):
        self.pipeline.process(upload.id)


# SQLite has no schemas, and every model here lives in ``pettycashv2``. The
# suite's convention is to ATTACH an in-memory database under that name so the
# qualified table names resolve. Done once per session, exactly as
# tests/test_auth_register_login.py does it.
_schema_attached = False


@pytest.fixture
def rig(app, monkeypatch):
    global _schema_attached
    from models.db import db

    with app.app_context():
        if not _schema_attached:
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        # The pipeline commits several times per upload, and the tests then read
        # the same objects back. Without this every attribute access after a
        # commit would be a fresh SELECT against a session the test has moved on
        # from.
        db.session.expire_on_commit = False
        db.create_all()

        instance = Rig(monkeypatch)
        instance.stub_storage()
        instance.stub_context()
        yield instance

        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()
        db.session.remove()


# --------------------------------------------------------------------------
# The headline behaviour: one PDF, several drafts.
# --------------------------------------------------------------------------
def test_three_receipts_in_one_pdf_become_three_drafts(rig):
    rig.modules()
    rig.stub_model([doc(1, 1), doc(2, 2), doc(3, 3)])

    upload = rig.seed_upload(page_count=3)
    rig.run(upload)

    drafts = rig.drafts_for(upload)
    assert len(drafts) == 3
    assert [d.sequence for d in drafts] == [1, 2, 3]
    assert [d.page_start for d in drafts] == [1, 2, 3]
    assert upload.status == "done"
    assert upload.document_count == 3
    # One split call, three extractions.
    assert (rig.pass1, rig.pass2) == (1, 3)


def test_a_two_page_invoice_is_one_draft(rig):
    rig.modules()
    rig.stub_model([doc(1, 2, doc_type="invoice")])

    upload = rig.seed_upload(page_count=2)
    rig.run(upload)

    drafts = rig.drafts_for(upload)
    assert len(drafts) == 1
    assert (drafts[0].page_start, drafts[0].page_end) == (1, 2)
    assert rig.pass2 == 1


def test_two_receipts_on_one_page_become_two_drafts(rig):
    """Both sit on page 1, so the locator is the only thing telling Pass 2
    which one to read. It must reach the call."""
    rig.modules()
    rig.stub_model(
        [doc(1, 1, locator="top, Starbucks"), doc(1, 1, locator="bottom, taxi")]
    )

    seen = []
    stubbed = rig.ai.extract

    def spy(document, mime, context, doc_type, locator=""):
        seen.append(locator)
        return stubbed(document, mime, context, doc_type, locator)

    rig.monkeypatch.setattr(rig.ai, "extract", spy)

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert len(rig.drafts_for(upload)) == 2
    assert seen == ["top, Starbucks", "bottom, taxi"]


def test_a_single_document_upload_sends_no_locator(rig):
    """With one document there is nothing to disambiguate, and the extra
    sentence would only be tokens and a chance to confuse the model."""
    rig.modules()
    rig.stub_model([doc(1, 1, locator="the only receipt")])

    seen = []
    stubbed = rig.ai.extract

    def spy(document, mime, context, doc_type, locator=""):
        seen.append(locator)
        return stubbed(document, mime, context, doc_type, locator)

    rig.monkeypatch.setattr(rig.ai, "extract", spy)

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert seen == [""]


# --------------------------------------------------------------------------
# THE COST CONTROL. This is the test the design exists for.
# --------------------------------------------------------------------------
def test_a_bank_statement_costs_one_call_not_eleven(rig):
    """Pass 1 classifies in order to split, so we learn it is a statement
    BEFORE paying for per-document extraction.

    Asserting the count is the point: a refactor that reintroduced Pass 2 here
    would pass every other test in this file.
    """
    rig.modules()
    rig.stub_model(
        [
            doc(1, 1, doc_type="other"),
            doc(2, 2, doc_type="other"),
            doc(3, 3, doc_type="other"),
        ]
    )

    upload = rig.seed_upload(page_count=3)
    rig.run(upload)

    assert rig.pass1 == 1
    assert rig.pass2 == 0
    assert rig.drafts_for(upload) == []
    assert upload.status == "rejected_not_supported"
    assert upload.reject_reason == "not_a_financial_document"


def test_too_many_documents_stops_before_extraction(rig):
    """Deliberately not "process the first ten". Finding more than the limit
    usually means the split went wrong, and ten wrong drafts are worse than one
    clear message."""
    rig.modules()
    rig.monkeypatch.setenv("CAPTURE_AI_MAX_DOCUMENTS", "3")
    rig.stub_model([doc(1, 1) for _ in range(5)])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert rig.pass2 == 0
    assert upload.status == "rejected_too_many"
    assert upload.reject_reason == "too_many_documents"
    assert rig.drafts_for(upload) == []


def test_a_covering_letter_beside_a_receipt_does_not_reject_the_upload(rig):
    """A mixed upload keeps what is real. The stray 'other' is dropped without
    a draft, because there is nothing the user could do with one."""
    rig.modules()
    rig.stub_model([doc(1, 1, doc_type="other"), doc(2, 2, doc_type="receipt")])

    upload = rig.seed_upload(page_count=2)
    rig.run(upload)

    assert upload.status == "done"
    drafts = rig.drafts_for(upload)
    assert len(drafts) == 1
    assert drafts[0].doc_type == "receipt"
    # Only the real document was extracted.
    assert rig.pass2 == 1


def test_the_override_reads_a_rejected_upload_as_receipts(rig):
    """"This IS a receipt, process it anyway" — the escape hatch for a
    legitimate crumpled receipt the model refused."""
    rig.modules()
    rig.stub_model([doc(1, 1, doc_type="other")])

    upload = rig.seed_upload(page_count=1, bypass=True)
    rig.run(upload)

    assert upload.status == "done"
    drafts = rig.drafts_for(upload)
    assert len(drafts) == 1
    assert drafts[0].doc_type == "receipt"
    assert rig.pass2 == 1


# --------------------------------------------------------------------------
# Routing and status
# --------------------------------------------------------------------------
def test_an_invoice_without_the_payment_module_is_held_not_lost(rig):
    rig.modules(petty_cash=True, bill=False)
    rig.stub_model([doc(1, 1, doc_type="invoice")])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    draft = rig.drafts_for(upload)[0]
    assert draft.destination == "hold"
    assert draft.status == "hold"


def test_a_receipt_with_petty_cash_is_ready_for_review(rig):
    rig.modules()
    rig.stub_model([doc(1, 1)])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    draft = rig.drafts_for(upload)[0]
    assert draft.destination == "petty_cash"
    assert draft.status == "ready"


def test_a_missing_amount_needs_clarification(rig):
    """Nobody can post an expense without an amount, so the draft says so
    rather than presenting itself as ready."""
    rig.modules()
    blank = suggestion()
    blank["amount"] = {"value": "", "confidence": 0.2, "band": "low",
                       "applied": False}
    rig.stub_model([doc(1, 1)], suggestions=blank)

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert rig.drafts_for(upload)[0].status == "needs_clarification"


def test_sortable_values_are_lifted_out_of_the_json(rig):
    """The queue sorts on these on every page load; unpacking JSON per row to
    do it would be a needless cost on the one query users wait for."""
    rig.modules()
    rig.stub_model([doc(1, 1)])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    draft = rig.drafts_for(upload)[0]
    assert str(draft.amount) == "120.00"
    assert draft.currency == "HKD"
    assert draft.supplier_name == "SF Express"
    assert draft.document_date.isoformat() == "2026-09-03"


def test_a_supplier_that_matched_nothing_still_fills_the_column(rig):
    """The model read a real name off the document. Throwing it away makes the
    user retype something we already have."""
    rig.modules()
    unmatched = suggestion()
    unmatched["supplier"] = {
        "value": "", "confidence": 0.0, "band": "low", "applied": False,
        "contact_id": "", "detected_name": "Kowloon Taxi",
    }
    rig.stub_model([doc(1, 1)], suggestions=unmatched)

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert rig.drafts_for(upload)[0].supplier_name == "Kowloon Taxi"


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------
def test_one_bad_document_does_not_lose_the_others(rig):
    """The user keeps what worked and can re-upload the page that did not.

    This is why the pipeline commits per draft rather than once at the end.
    """
    rig.modules()
    rig.stub_model([doc(1, 1), doc(2, 2), doc(3, 3)])

    calls = {"n": 0}
    good = rig.ai.extract

    def flaky(document, mime, context, doc_type, locator=""):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("that page was a mess")
        return good(document, mime, context, doc_type, locator)

    rig.monkeypatch.setattr(rig.ai, "extract", flaky)

    upload = rig.seed_upload(page_count=3)
    rig.run(upload)

    assert len(rig.drafts_for(upload)) == 2
    assert upload.status == "done"


def test_an_empty_split_is_rejected_not_failed(rig):
    """"There is no document in here" and "the provider fell over" are
    different things and must not look the same to the user: one is worth
    retrying and the other never will be."""
    rig.modules()
    rig.stub_model([])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert upload.status == "rejected_not_supported"
    assert rig.pass2 == 0


def test_a_provider_failure_is_failed_not_rejected(rig):
    rig.modules()

    def split(document, mime, page_count):
        rig.pass1 += 1
        return rig.ai.SplitResult(
            reason=rig.ai.REASON_TIMEOUT, audit={"model_id": "test"}
        )

    rig.monkeypatch.setattr(rig.ai, "split_and_classify", split)

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    assert upload.status == "failed"
    assert rig.pass2 == 0


def test_a_file_missing_from_storage_fails_cleanly(rig):
    """No model call is made for a file we cannot read."""
    rig.modules()
    rig.stub_model([doc(1, 1)])

    upload = rig.seed_upload(page_count=1)
    rig.files.clear()
    rig.run(upload)

    assert upload.status == "failed"
    assert rig.pass1 == 0


def test_an_upload_deleted_mid_flight_is_not_an_error(rig):
    """The retention sweeper and a user's Archive can both remove a row while a
    thread still holds its id."""
    rig.modules()
    rig.stub_model([doc(1, 1)])

    rig.run(type("Gone", (), {"id": str(uuid4())})())
    assert rig.pass1 == 0


def test_an_audit_row_is_written_for_every_call(rig):
    """Cost and latency have to be answerable later, per pass."""
    from blueprints.capture.models.capture_ai_audit import CaptureAiAudit

    rig.modules()
    rig.stub_model([doc(1, 1), doc(2, 2)])

    upload = rig.seed_upload(page_count=2)
    rig.run(upload)

    rows = CaptureAiAudit.query.filter_by(upload_id=upload.id).all()
    assert len(rows) == 3  # one split, two extractions
    assert sorted(r.pass_number for r in rows) == [1, 2, 2]


def test_the_audit_never_records_a_value_off_the_document(rig):
    """Amounts, suppliers and descriptions are a client's financial details.
    They live in capture_draft.suggested, behind the same authorisation as
    everything else — never in a metrics table."""
    from blueprints.capture.models.capture_ai_audit import CaptureAiAudit

    rig.modules()
    rig.stub_model([doc(1, 1)])

    upload = rig.seed_upload(page_count=1)
    rig.run(upload)

    for row in CaptureAiAudit.query.filter_by(upload_id=upload.id).all():
        blob = repr(row.confidence_by_field or {})
        assert "SF Express" not in blob
        assert "120.00" not in blob
        assert "Courier delivery" not in blob
