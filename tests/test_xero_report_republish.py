"""Tests for republishing a petty-cash report without duplicating in Xero.

Publishing posts to Xero's collection endpoints, so before this change a
republish created a second copy of every transaction. The fix records the
object ids each publish creates (in ``xero_report_sync``, no migration) and
sends the next publish at those objects instead.

Covers the decision layer and the transport layer, which is where the
behaviour lives: whether a given publish CREATES or UPDATES, and which URL and
verb that turns into.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# uuids since C5: the ids are uuid columns, and xero_report_sync.report_id is a NOT NULL FK
ENTITY_ID = "0e9b1a2c-0000-4000-8000-00000000e001"
REPORT_ID = "0e9b1a2c-0000-4000-8000-00000000f001"
ORG_A = "xero-org-OLD"
ORG_B = "xero-org-NEW"
TOKEN = "fake-token"


@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        _seed_report(db)
        yield db
        # TRUNCATE ... CASCADE on Postgres, per-table deletes on SQLite: the swallowed
        # per-table deletes left the sync row behind between tests on Postgres.
        import char_factories

        char_factories.truncate_all(app)


def _seed_report(db):
    """The company and the report the publish record hangs off (the sync row's FK is
    NOT NULL since C5, so a record needs a real report)."""
    from datetime import date

    from models.db import Entity, Report

    if db.session.get(Entity, ENTITY_ID) is None:
        db.session.add(Entity(id=ENTITY_ID, name="Republish Co", xero_org_id=ORG_B, status="connected"))
    if db.session.get(Report, REPORT_ID) is None:
        db.session.add(Report(id=REPORT_ID, entity_id=ENTITY_ID, transaction_date=date(2026, 9, 1), status="submitted"))
    db.session.commit()


@pytest.fixture
def entity(db_session):
    from models.db import Entity

    return db_session.session.get(Entity, ENTITY_ID)


def _ok(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.text = __import__("json").dumps(payload)
    resp.json.return_value = payload
    return resp


# ────────────────────────────────────────────────────────── the record


class TestPublishRecord:
    def test_round_trips_ids_per_module(self, db_session):
        from blueprints.xero.services import publish_record

        publish_record.record_object(
            REPORT_ID, ORG_B, "invoices", "inv-1", object_type="INVOICE"
        )
        publish_record.record_object(
            REPORT_ID, ORG_B, "expenses", "txn-1", source_id="exp-1",
            object_type="BANK_TRANSACTION",
        )

        record = publish_record.load_record(REPORT_ID, ORG_B)
        assert publish_record.recorded_id(record, "invoices") == "inv-1"
        assert publish_record.recorded_expense_ids(record) == {"exp-1": "txn-1"}

    def test_empty_when_nothing_recorded(self, db_session):
        from blueprints.xero.services import publish_record

        record = publish_record.load_record(REPORT_ID, ORG_B)
        assert record["objects"] == {}
        assert publish_record.recorded_id(record, "invoices") is None

    def test_ignores_a_record_from_another_org(self, db_session):
        """Ids issued by one Xero org do not resolve in another."""
        from blueprints.xero.services import publish_record

        publish_record.record_object(
            REPORT_ID, ORG_A, "invoices", "inv-1", object_type="INVOICE"
        )

        assert publish_record.load_record(REPORT_ID, ORG_A)["objects"], "sanity"
        assert publish_record.load_record(REPORT_ID, ORG_B)["objects"] == {}

    def test_record_without_an_org_still_matches(self, db_session):
        """Nothing written before the org was tracked should regress."""
        from blueprints.xero.services import publish_record

        publish_record.record_object(
            REPORT_ID, "", "invoices", "inv-1", object_type="INVOICE"
        )
        record = publish_record.load_record(REPORT_ID, ORG_B)
        assert publish_record.recorded_id(record, "invoices") == "inv-1"

    def test_unparseable_text_is_treated_as_no_record(self, db_session):
        from blueprints.xero.services import publish_record
        from models.db import XeroReportSync

        db_session.session.add(
            XeroReportSync(report_id=REPORT_ID, xero_response_text="not json")
        )
        db_session.session.commit()

        assert publish_record.load_record(REPORT_ID, ORG_B)["objects"] == {}

    def test_forget_drops_only_the_named_object(self, db_session):
        from blueprints.xero.services import publish_record

        publish_record.record_object(
            REPORT_ID, ORG_B, "deposit", "tr-1", object_type="BANK_TRANSFER"
        )
        publish_record.record_object(
            REPORT_ID, ORG_B, "invoices", "inv-1", object_type="INVOICE"
        )

        publish_record.forget_object(REPORT_ID, "deposit")

        record = publish_record.load_record(REPORT_ID, ORG_B)
        assert publish_record.recorded_id(record, "deposit") is None
        assert publish_record.recorded_id(record, "invoices") == "inv-1"

    def test_forget_one_expense_keeps_the_others(self, db_session):
        from blueprints.xero.services import publish_record

        publish_record.record_object(
            REPORT_ID, ORG_B, "expenses", "txn-1", source_id="exp-1",
            object_type="BANK_TRANSACTION",
        )
        publish_record.record_object(
            REPORT_ID, ORG_B, "expenses", "txn-2", source_id="exp-2",
            object_type="BANK_TRANSACTION",
        )

        publish_record.forget_object(REPORT_ID, "expenses", source_id="exp-1")

        record = publish_record.load_record(REPORT_ID, ORG_B)
        assert publish_record.recorded_expense_ids(record) == {"exp-2": "txn-2"}


class TestExistingIdTypeGuard:
    """A module can change shape between publishes."""

    def test_matching_type_is_used(self):
        from blueprints.xero.services.publish import _existing_id

        entry = {"type": "BANK_TRANSFER", "id": "tr-1"}
        assert _existing_id(entry, "BANK_TRANSFER") == "tr-1"

    def test_mismatched_type_creates_fresh(self):
        """A company withdrawal is a transfer, a personal one is a transaction.

        Feeding a transfer id to the bank-transaction endpoint would fail
        confusingly, so a type change must fall back to creating.
        """
        from blueprints.xero.services.publish import _existing_id

        entry = {"type": "BANK_TRANSFER", "id": "tr-1"}
        assert _existing_id(entry, "BANK_TRANSACTION") is None

    def test_nothing_recorded(self):
        from blueprints.xero.services.publish import _existing_id

        assert _existing_id(None, "INVOICE") is None


# ───────────────────────────────────────────────────── create vs update


class TestBankTransactionRouting:
    def test_create_posts_to_the_collection(self, app, monkeypatch):
        from blueprints.xero.services import publish

        seen = {}

        def fake_post(url, **kwargs):
            seen["url"] = url
            return _ok({"BankTransactions": [{"BankTransactionID": "txn-new"}]})

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            publish.bank_transaction_to_xero(ORG_B, TOKEN, {"bankTransactions": [{}]})

        assert seen["url"].endswith("/BankTransactions")

    def test_update_posts_to_the_object(self, app, monkeypatch):
        from blueprints.xero.services import publish

        seen = {}

        def fake_post(url, **kwargs):
            seen["url"] = url
            return _ok({"BankTransactions": [{"BankTransactionID": "txn-1"}]})

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            publish.bank_transaction_to_xero(
                ORG_B, TOKEN, {"bankTransactions": [{}]}, object_id="txn-1"
            )

        assert seen["url"].endswith("/BankTransactions/txn-1")


class TestInvoiceRouting:
    def test_create_uses_put(self, app, monkeypatch):
        from blueprints.xero.services import publish

        calls = {}
        monkeypatch.setattr(
            publish.requests, "put",
            lambda url, **kw: calls.setdefault("put", url) or _ok({}),
        )
        monkeypatch.setattr(
            publish.requests, "post",
            lambda url, **kw: calls.setdefault("post", url) or _ok({}),
        )
        with app.app_context():
            publish.invoice_to_xero(ORG_B, TOKEN, {"Invoices": [{}]})

        assert calls["put"].endswith("/Invoices")
        assert "post" not in calls

    def test_update_uses_post_on_the_invoice(self, app, monkeypatch):
        from blueprints.xero.services import publish

        calls = {}
        monkeypatch.setattr(
            publish.requests, "put",
            lambda url, **kw: calls.setdefault("put", url) or _ok({}),
        )
        monkeypatch.setattr(
            publish.requests, "post",
            lambda url, **kw: calls.setdefault("post", url) or _ok({}),
        )
        with app.app_context():
            publish.invoice_to_xero(
                ORG_B, TOKEN, {"Invoices": [{}]}, object_id="inv-1"
            )

        assert calls["post"].endswith("/Invoices/inv-1")
        assert "put" not in calls, "a republish must not create a second invoice"


class TestCreateInvoiceUsesTheRecordedId:
    def test_existing_id_is_sent_in_the_payload(self, app, entity, monkeypatch):
        from blueprints.xero.services import publish

        seen = {}

        def fake_post(url, data=None, **kwargs):
            seen["url"] = url
            seen["body"] = __import__("json").loads(data)
            return _ok({"Invoices": [{"InvoiceID": "inv-1"}]})

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            result = publish.create_invoice(
                ENTITY_ID, "contact-1", "Cash Sales", 1, 100.0, "NONE", 100.0,
                "2026-04-01", "2026-04-01", "200",
                access_token=TOKEN, existing_id="inv-1",
            )

        assert result == "inv-1"
        assert seen["url"].endswith("/Invoices/inv-1")
        assert seen["body"]["Invoices"][0]["InvoiceID"] == "inv-1"


# ──────────────────────────────────────────────── bank transfer replace


class TestBankTransferReplace:
    def test_delete_posts_status_deleted_in_the_body(self, app, monkeypatch):
        """Xero names this parameter "ByUrlParam"; it is really a body field."""
        from blueprints.xero.services import publish

        seen = {}

        def fake_post(url, data=None, **kwargs):
            seen["url"] = url
            seen["body"] = __import__("json").loads(data)
            return _ok({"BankTransfers": [{"BankTransferID": "tr-1"}]})

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            ok, reason = publish.delete_bank_transfer_in_xero(ORG_B, TOKEN, "tr-1")
            assert ok is True and reason is None

        assert seen["url"].endswith("/BankTransfers/tr-1")
        assert seen["body"] == {"Status": "DELETED"}

    def test_republish_deletes_then_creates(self, app, entity, db_session, monkeypatch):
        from blueprints.xero.services import publish

        calls = []

        def fake_post(url, data=None, **kwargs):
            calls.append(url)
            return _ok({"BankTransfers": [{"BankTransferID": "tr-2"}]})

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            result = publish.create_bank_transfer(
                ENTITY_ID, "2026-04-01", bank_account="acct-a",
                withdrawal_amount=100.0, to_bank_account_id="acct-b",
                access_token=TOKEN, existing_id="tr-1",
                report_id=REPORT_ID, record_module="deposit",
            )

        assert result == "tr-2"
        assert calls[0].endswith("/BankTransfers/tr-1"), "delete the old one first"
        assert calls[1].endswith("/BankTransfers"), "then create the replacement"

    def test_failed_delete_does_not_create(self, app, entity, db_session, monkeypatch):
        """Creating after a failed delete is exactly the duplicate we are fixing."""
        from blueprints.xero.services import publish

        calls = []

        def fake_post(url, data=None, **kwargs):
            calls.append(url)
            resp = MagicMock()
            resp.status_code = 400
            resp.text = "cannot delete"
            return resp

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            result = publish.create_bank_transfer(
                ENTITY_ID, "2026-04-01", bank_account="acct-a",
                withdrawal_amount=100.0, to_bank_account_id="acct-b",
                access_token=TOKEN, existing_id="tr-1",
                report_id=REPORT_ID, record_module="deposit",
            )

        assert result is False
        assert len(calls) == 1, "no replacement may be created"

    def test_old_id_is_forgotten_before_the_replacement_is_created(
        self, app, entity, db_session, monkeypatch
    ):
        """A create that fails after the delete must not leave a stale id.

        Otherwise the next republish tries to delete a transfer Xero no longer
        has, and never recovers.
        """
        from blueprints.xero.services import publish, publish_record

        publish_record.record_object(
            REPORT_ID, ORG_B, "deposit", "tr-1", object_type="BANK_TRANSFER"
        )

        state = {"n": 0}

        def fake_post(url, data=None, **kwargs):
            state["n"] += 1
            if state["n"] == 1:  # the delete succeeds
                return _ok({"BankTransfers": [{"BankTransferID": "tr-1"}]})
            resp = MagicMock()  # the create fails
            resp.status_code = 400
            resp.text = "boom"
            return resp

        monkeypatch.setattr(publish.requests, "post", fake_post)
        with app.app_context():
            publish.create_bank_transfer(
                ENTITY_ID, "2026-04-01", bank_account="acct-a",
                withdrawal_amount=100.0, to_bank_account_id="acct-b",
                access_token=TOKEN, existing_id="tr-1",
                report_id=REPORT_ID, record_module="deposit",
            )

            record = publish_record.load_record(REPORT_ID, ORG_B)

        assert publish_record.recorded_id(record, "deposit") is None


# ──────────────────────────────────────────────── failure reasons


class TestRepublishFailureReasons:
    """Updating in place lets Xero refuse where it used to accept a duplicate.

    The two refusals a user can act on get named wording; everything else keeps
    falling through to the existing generic handling.
    """

    def test_reconciled_transaction(self):
        from blueprints.xero.services.publish_errors import (XERO_RECONCILED,
                                                             translate_xero_error)

        body = (
            '{"Elements":[{"ValidationErrors":[{"Message":'
            '"The bank transaction is reconciled and cannot be modified"}]}]}'
        )
        assert translate_xero_error(400, body) == XERO_RECONCILED

    def test_reconciled_wording_variants(self):
        from blueprints.xero.services.publish_errors import (XERO_RECONCILED,
                                                             translate_xero_error)

        for message in (
            "You cannot edit a reconciled transaction",
            "Bank transfer has been reconciled",
            "Reconciliation prevents this change",
        ):
            body = '{"Detail":"%s"}' % message
            assert translate_xero_error(400, body) == XERO_RECONCILED, message

    def test_invoice_with_a_payment(self):
        from blueprints.xero.services.publish_errors import (XERO_HAS_PAYMENT,
                                                             translate_xero_error)

        body = (
            '{"Elements":[{"ValidationErrors":[{"Message":'
            '"Invoice cannot be edited as it has payments or credit notes '
            'allocated to it"}]}]}'
        )
        assert translate_xero_error(400, body) == XERO_HAS_PAYMENT

    def test_reconciled_beats_the_account_mapping(self):
        """A reconciled entry naming an account must not read as a mapping problem."""
        from blueprints.xero.services.publish_errors import (XERO_RECONCILED,
                                                             translate_xero_error)

        body = (
            '{"Detail":"Account code 090 transaction is reconciled and '
            'cannot be modified"}'
        )
        assert translate_xero_error(400, body, subject="account") == XERO_RECONCILED

    def test_unrelated_errors_are_unchanged(self):
        from blueprints.xero.services.publish_errors import translate_xero_error

        body = '{"Detail":"Account code 999 is not a valid code"}'
        assert translate_xero_error(400, body, subject="account") == (
            "account is no longer active in Xero"
        )

    def test_reconciled_transfer_reason_reaches_the_user(self, app, entity, monkeypatch):
        """A transfer that cannot be deleted must say WHY, not just that it failed."""
        from blueprints.xero.services import publish
        from blueprints.xero.services.publish_errors import (PublishFailureReason,
                                                             XERO_RECONCILED)

        def fake_post(url, data=None, **kwargs):
            resp = MagicMock()
            resp.status_code = 400
            resp.text = '{"Detail":"This transfer is reconciled"}'
            return resp

        monkeypatch.setattr(publish.requests, "post", fake_post)
        pfr = PublishFailureReason()
        with app.app_context():
            result = publish.create_bank_transfer(
                ENTITY_ID, "2026-04-01", bank_account="acct-a",
                withdrawal_amount=100.0, to_bank_account_id="acct-b",
                access_token=TOKEN, existing_id="tr-1",
                report_id=REPORT_ID, record_module="deposit",
                pfr=pfr, module_label="Deposit",
            )

        assert result is False
        assert any(XERO_RECONCILED in text for text in pfr.to_reason_bullets()), (
            pfr.to_reason_bullets()
        )


# ──────────────────────────────────────────── receipts on a republish


class TestReceiptUpload:
    """Republishing re-runs every module, so the receipt path must be idempotent."""

    @staticmethod
    def _expense_and_entity():
        from types import SimpleNamespace

        expense = SimpleNamespace(
            s3_key="https://cdn.example.test/receipt.png",  # the first receipt's key (C4)
            remarks="fuel receipt",
            item="fuel",
        )
        entity = SimpleNamespace(id=ENTITY_ID, xero_org_id=ORG_B)
        return expense, entity

    @staticmethod
    def _wire(monkeypatch, publish, *, associations, meta, file_bytes=b"abc"):
        """Fake the S3 fetch and every Files API call. Returns a call log."""
        calls = []

        def fake_get(url, **kwargs):
            calls.append(("GET", url))
            if url.startswith("https://cdn.example.test"):
                resp = MagicMock()
                resp.status_code = 200
                resp.content = file_bytes
                resp.raise_for_status = lambda: None
                return resp
            if "/Associations/" in url:
                return _ok(associations)
            return _ok(meta)

        def fake_post(url, **kwargs):
            calls.append(("POST", url))
            if url.endswith("/Files"):
                return _ok({"FileId": "file-new"})
            return _ok({"Id": "assoc-1"})

        def fake_delete(url, **kwargs):
            calls.append(("DELETE", url))
            return _ok({})

        monkeypatch.setattr(publish.requests, "get", fake_get)
        monkeypatch.setattr(publish.requests, "post", fake_post)
        monkeypatch.setattr(publish.requests, "delete", fake_delete)
        return calls

    def test_unchanged_receipt_is_left_alone(self, app, monkeypatch):
        """The whole point: a republish must not churn an identical receipt."""
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = self._wire(
            monkeypatch, publish,
            associations=[{"FileId": "file-1", "Name": "fuel_receipt.png", "Size": 3}],
            meta={},
        )

        with app.app_context():
            assert publish.upload_each_file(
                expense, entity, "bt-1", access_token=TOKEN
            ) is True

        assert not [c for c in calls if c[0] in ("POST", "DELETE")], (
            f"nothing should have been written: {calls}"
        )

    def test_changed_receipt_is_replaced(self, app, monkeypatch):
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = self._wire(
            monkeypatch, publish,
            associations=[{"FileId": "file-old", "Name": "old_name.png", "Size": 99}],
            meta={},
        )

        with app.app_context():
            assert publish.upload_each_file(
                expense, entity, "bt-1", access_token=TOKEN
            ) is True

        verbs = [c[0] for c in calls]
        assert "POST" in verbs and "DELETE" in verbs
        assert verbs.index("POST") < verbs.index("DELETE"), (
            "the replacement must be attached before the old file is removed"
        )
        assert ("DELETE", f"{publish.XERO_FILES_API_BASE}/Files/file-old") in calls

    def test_failed_upload_leaves_the_existing_receipt(self, app, monkeypatch):
        """Deleting first would strand the transaction with no receipt at all."""
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = self._wire(
            monkeypatch, publish,
            associations=[{"FileId": "file-old", "Name": "old_name.png", "Size": 99}],
            meta={},
        )

        def failing_post(url, **kwargs):
            calls.append(("POST", url))
            resp = MagicMock()
            resp.status_code = 400
            resp.text = "upload rejected"
            return resp

        monkeypatch.setattr(publish.requests, "post", failing_post)

        with app.app_context():
            assert publish.upload_each_file(
                expense, entity, "bt-1", access_token=TOKEN
            ) is False

        assert not [c for c in calls if c[0] == "DELETE"], (
            "the existing receipt must survive a failed upload"
        )

    def test_first_publish_uploads_with_nothing_to_remove(self, app, monkeypatch):
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = self._wire(monkeypatch, publish, associations=[], meta={})

        with app.app_context():
            assert publish.upload_each_file(
                expense, entity, "bt-1", access_token=TOKEN
            ) is True

        assert not [c for c in calls if c[0] == "DELETE"]
        assert any(url.endswith("/Files") for verb, url in calls if verb == "POST")

    def test_association_lookup_uses_the_object_route(self, app, monkeypatch):
        """Regression: the wrong route here makes receipts pile up silently.

        /Associations/{ObjectId} asks "what is attached to this transaction".
        /Files/{FileId}/Associations asks the mirror question. Calling
        /Files/Associations/{id} -- which is neither -- fails, the caller reads
        it as "nothing attached", deletes nothing, and every republish adds
        another copy of the same receipt.
        """
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = self._wire(
            monkeypatch, publish,
            associations=[{"FileId": "file-1", "Name": "fuel_receipt.png", "Size": 3}],
            meta={},
        )

        with app.app_context():
            publish.upload_each_file(expense, entity, "bt-1", access_token=TOKEN)

        lookups = [url for verb, url in calls if verb == "GET" and "ssociation" in url]
        assert lookups == [f"{publish.XERO_FILES_API_BASE}/Associations/bt-1"], lookups

    def test_unknown_association_state_does_not_delete(self, app, monkeypatch):
        """A failed lookup must not be read as "nothing attached"."""
        from blueprints.xero.services import publish

        expense, entity = self._expense_and_entity()
        calls = []

        def fake_get(url, **kwargs):
            calls.append(("GET", url))
            if url.startswith("https://cdn.example.test"):
                resp = MagicMock()
                resp.status_code, resp.content = 200, b"abc"
                resp.raise_for_status = lambda: None
                return resp
            resp = MagicMock()  # association lookup fails
            resp.status_code, resp.text = 500, "boom"
            return resp

        monkeypatch.setattr(publish.requests, "get", fake_get)
        monkeypatch.setattr(
            publish.requests, "post",
            lambda url, **kw: calls.append(("POST", url)) or _ok({"FileId": "f-new"}),
        )
        monkeypatch.setattr(
            publish.requests, "delete",
            lambda url, **kw: calls.append(("DELETE", url)) or _ok({}),
        )

        with app.app_context():
            publish.upload_each_file(expense, entity, "bt-1", access_token=TOKEN)

        assert not [c for c in calls if c[0] == "DELETE"], (
            "must not delete on a guess when the attached set is unknown"
        )
