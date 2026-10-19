"""Reading a receipt with the model, through each door that asks for it:

* ``POST /report/expense/extract`` - the Jinja Expenses page (``report/routes/expense_ai.py``);
* ``POST /api/petty-cash/v1/companies/<id>/reports/expenses/extract`` - the Petty Cash API
  (``petty_cash_api/routes/expenses.py::extract_answer``);
* ``POST /api/internal/petty-cash/expense-extract`` - the same answer for minty-petty-cash-api,
  which holds no model code and forwards the receipt here under a service assertion.

All three end in ``report/services/expense_ai.py`` (the only module that talks to the model,
pinned by tests/test_expense_ai.py). The model is never called: ``expense_ai._get_client`` is a
stand-in throughout.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import char_factories as F
import jwt
import pytest

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"
JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
INTERNAL = "/api/internal/petty-cash/expense-extract"
SCOPE = "petty-cash-expense-extract"


def _reply(**overrides):
    body = {
        "supplier_contact_id": "con-0001", "supplier_name": "ABC Supplies", "supplier_confidence": 0.93,
        "account_id": "acc-0001", "account_code": "400", "account_name": "Advertising",
        "account_confidence": 0.88, "amount_value": 120.0, "amount_confidence": 0.97,
        "description_value": "Flyers", "description_confidence": 0.81, "currency": "HKD",
        "document_date": "2026-10-18", "document_date_confidence": 0.9,
    }
    body.update(overrides)
    return json.dumps(body)


class _Usage:
    total_input_tokens = 5000
    total_output_tokens = 300
    total_thought_tokens = 0
    total_cached_tokens = 0


class _Interaction:
    def __init__(self, text):
        self.id = "interaction-1"
        self.output_text = text
        self.status = "completed"
        self.errors = []
        self.usage = _Usage()


class _Model:
    """The stand-in client: records each call, answers ``reply``."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []
        self.interactions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Interaction(self.reply)


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def model(monkeypatch):
    """The feature on, the cut-offs pinned, the rate limits empty and the model a stand-in."""
    from blueprints.report.services import expense_ai

    monkeypatch.setenv("EXPENSE_AI_ENABLED", "1")
    monkeypatch.setenv("EXPENSE_AI_CONF_HIGH", "0.85")
    monkeypatch.setenv("EXPENSE_AI_CONF_MEDIUM", "0.60")
    monkeypatch.setattr(expense_ai, "_user_hits", type(expense_ai._user_hits)(expense_ai._user_hits.default_factory))
    monkeypatch.setattr(expense_ai, "_entity_hits",
                        type(expense_ai._entity_hits)(expense_ai._entity_hits.default_factory))
    stand_in = _Model(_reply())
    monkeypatch.setattr(expense_ai, "_get_client", lambda: stand_in)
    return stand_in


@pytest.fixture
def shop(app, db):
    from models.db import AccountInfo, CountryInfo, CurrencyInfo, EntityAccountXero, XeroContactSync

    with app.app_context():
        currency = CurrencyInfo.query.filter_by(currency_code="HKD").first() or F.seed_currency(db)
        country = CountryInfo.query.filter_by(country_code="HK").first() or F.seed_country(db, currency)
        owner = F.make_user(db, "owner@test.com")
        entity = F.make_entity(db, owner, currency=currency, country=country)
        db.session.add(XeroContactSync(entity_id=entity.id, xero_contact_id="con-0001", name="ABC Supplies"))
        row = AccountInfo(id=str(uuid.uuid4()), entity_id=entity.id, xero_account_id="acc-0001", xero_code="400",
                          name="Advertising", type="EXPENSE", status="ACTIVE")
        db.session.add(row)
        db.session.flush()
        db.session.add(EntityAccountXero(account_id=row.id, name="Advertising", type="EXPENSE",
                                         xero_account_id="acc-0001", is_active=True))
        base = F.make_user(db, "base@test.com")
        from models.db import UserEntity

        db.session.add(UserEntity(user_id=base.id, entity_id=entity.id, role="entity_base", approved=True))
        db.session.commit()
    return owner, entity, base


# --- the Jinja page's route (pinned 2026-10-19, before the API shared its tail) ---------------------


def _page(client, who, entity, data=JPEG, name="slip.jpg"):
    F.login(client, who)
    form = {"entity_id": entity.id}
    if data is not None:
        form["file"] = (BytesIO(data), name)
    return client.post("/report/expense/extract", data=form, content_type="multipart/form-data")


def test_page_switched_off_suggests_nothing_and_asks_nothing(app, client, db, shop, model, monkeypatch):
    owner, entity, _ = shop
    monkeypatch.setenv("EXPENSE_AI_ENABLED", "0")

    resp = _page(client, owner, entity)

    assert resp.status_code == 200 and resp.get_json() == {"suggestions": None, "reason": "disabled"}
    assert model.calls == []


def test_page_reads_a_receipt_into_checked_suggestions(app, client, db, shop, model):
    owner, entity, _ = shop

    resp = _page(client, owner, entity)

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["reason"] is None
    assert body["suggestions"]["supplier"]["contact_id"] == "con-0001"
    assert body["suggestions"]["account"]["account_id"] == "acc-0001"
    assert body["suggestions"]["amount"]["value"] == "120.00"
    assert len(model.calls) == 1


def test_page_refusals_are_silent(app, client, db, shop, model):
    owner, entity, base = shop

    assert _page(client, owner, entity, data=b"GIF89a-nope").get_json() == {
        "suggestions": None, "reason": "unsupported_file"}
    assert _page(client, owner, entity, data=None).get_json()["reason"] == "unsupported_file"
    assert _page(client, base, entity).get_json() == {"suggestions": None, "reason": "no_context"}
    assert model.calls == []


# --- the Petty Cash API: POST /reports/expenses/extract ----------------------------------------------


def _api(app, client, who, entity, data=JPEG, name="slip.jpg", files=None):
    form = {}
    if files is not None:
        form["receipt"] = files
    elif data is not None:
        form["receipt"] = (BytesIO(data), name)
    return client.post(f"/api/petty-cash/v1/companies/{entity.id}/reports/expenses/extract", data=form,
                       content_type="multipart/form-data", headers=F.petty_cash_headers(app, who.id, origin=WEB))


def test_api_reads_a_receipt_into_the_page_s_suggestions(app, client, db, shop, model):
    owner, entity, _ = shop

    resp = _api(app, client, owner, entity)

    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert set(body) == {"suggestions", "reason"} and body["reason"] is None
    suggestions = body["suggestions"]
    assert suggestions["supplier"] == {"value": "ABC Supplies", "confidence": 0.93, "band": "high",
                                       "applied": True, "contact_id": "con-0001"}
    assert suggestions["account"]["account_id"] == "acc-0001" and suggestions["account"]["code"] == "400"
    assert suggestions["amount"]["value"] == "120.00" and suggestions["description"]["value"] == "Flyers"
    assert suggestions["entity_currency"] == "HKD"
    # the model saw the company's own lists and the receipt's bytes, typed by its bytes
    [call] = model.calls
    assert "acc-0001" in json.dumps(call["input"]) and "con-0001" in json.dumps(call["input"])
    assert any(part.get("mime_type") == "image/jpeg" for part in call["input"] if isinstance(part, dict))
    assert resp.headers["Access-Control-Allow-Origin"] == WEB and resp.headers["Cache-Control"] == "no-store"


def test_api_an_id_the_company_does_not_have_is_dropped(app, client, db, shop, model):
    owner, entity, _ = shop
    model.reply = _reply(supplier_contact_id="con-someone-else", account_id="acc-someone-else")

    body = _api(app, client, owner, entity).get_json()

    assert body["suggestions"]["supplier"]["contact_id"] == ""
    assert body["suggestions"]["supplier"]["detected_name"] == "ABC Supplies"
    assert body["suggestions"]["account"]["account_id"] == ""


def test_api_switched_off_suggests_nothing_and_asks_nothing(app, client, db, shop, model, monkeypatch):
    owner, entity, _ = shop
    monkeypatch.delenv("EXPENSE_AI_ENABLED")  # the default is off

    resp = _api(app, client, owner, entity)

    assert resp.status_code == 200 and resp.get_json() == {"suggestions": None, "reason": "disabled"}
    assert model.calls == []


def test_api_silent_outcomes_are_200_with_a_reason(app, client, db, shop, model, monkeypatch):
    owner, entity, _ = shop
    model.reply = "not json"
    assert _api(app, client, owner, entity).get_json() == {"suggestions": None, "reason": "invalid_reply"}

    monkeypatch.setenv("EXPENSE_AI_RATE_USER_PER_MIN", "1")
    resp = _api(app, client, owner, entity)
    assert resp.status_code == 200 and resp.get_json() == {"suggestions": None, "reason": "rate_limited"}
    assert len(model.calls) == 1


@pytest.mark.parametrize("data, message", [
    (None, "Attach the receipt to read it."),
    (b"GIF89a-not-allowed", "Attach a PDF, JPEG or PNG file."),
    (b"", "That file is empty. Attach the receipt again."),
    (b"%PDF" + b"0" * (10 * 1024 * 1024), "Attach a file of 10 MB or less."),
], ids=["missing", "gif", "empty", "too-big"])
def test_api_a_file_that_is_not_a_receipt_is_a_422(app, client, db, shop, model, data, message):
    owner, entity, _ = shop

    resp = _api(app, client, owner, entity, data=data)

    assert resp.status_code == 422 and resp.get_json() == {"error": message}
    assert model.calls == []


def test_api_two_files_are_a_422(app, client, db, shop, model):
    owner, entity, _ = shop

    resp = _api(app, client, owner, entity, files=[(BytesIO(JPEG), "a.jpg"), (BytesIO(JPEG), "b.jpg")])

    assert resp.status_code == 422 and resp.get_json() == {"error": "Attach one receipt at a time."}


def test_api_who_may_ask(app, client, db, shop, model):
    owner, entity, base = shop
    with app.app_context():
        stranger = F.make_user(db, "stranger@test.com")

    refused = _api(app, client, base, entity)
    assert refused.status_code == 403
    assert refused.get_json() == {"error": "You do not have permission to edit reports for this entity."}
    assert _api(app, client, stranger, entity).status_code == 403  # the door: not a member
    no_token = client.post(f"/api/petty-cash/v1/companies/{entity.id}/reports/expenses/extract",
                           data={"receipt": (BytesIO(JPEG), "slip.jpg")}, content_type="multipart/form-data")
    assert no_token.status_code == 401
    assert model.calls == []


# --- the internal route minty-petty-cash-api forwards to ----------------------------------------------


def _internal(app, client, entity_id, user_id, data=JPEG, scope=SCOPE, secret=None, token=True):
    now = datetime.now(timezone.utc)
    claims = {"scope": scope, "entity_id": str(entity_id), "user_id": str(user_id), "iat": now,
              "exp": now + timedelta(seconds=60)}
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + jwt.encode(claims, secret or app.config["SECRET_KEY"],
                                                          algorithm="HS256")
    form = {"receipt": (BytesIO(data), "slip.jpg")} if data is not None else {}
    return client.post(INTERNAL, data=form, content_type="multipart/form-data", headers=headers)


def test_internal_answers_exactly_what_the_api_answers(app, client, db, shop, model):
    owner, entity, _ = shop

    forwarded = _internal(app, client, entity.id, owner.id)
    direct = _api(app, client, owner, entity)

    assert forwarded.status_code == 200
    assert forwarded.get_json() == direct.get_json()
    assert forwarded.get_json()["suggestions"]["amount"]["value"] == "120.00"
    assert len(model.calls) == 2


def test_internal_rechecks_the_person_and_the_file(app, client, db, shop, model):
    owner, entity, base = shop

    assert _internal(app, client, entity.id, base.id).status_code == 403
    bad = _internal(app, client, entity.id, owner.id, data=b"GIF89a")
    assert bad.status_code == 422 and bad.get_json() == {"error": "Attach a PDF, JPEG or PNG file."}
    assert _internal(app, client, entity.id, owner.id, data=None).status_code == 422
    assert model.calls == []


def test_internal_refuses_a_caller_without_the_scope_or_the_key(app, client, db, shop, model):
    owner, entity, _ = shop

    assert _internal(app, client, entity.id, owner.id, scope="petty-cash-publish").status_code == 401
    assert _internal(app, client, entity.id, owner.id, secret="x" * 40).status_code == 401
    assert _internal(app, client, entity.id, owner.id, token=False).status_code == 401
    assert _internal(app, client, entity.id, F.new_id()).status_code == 401
    assert model.calls == []


def test_internal_route_takes_no_csrf_token(app):
    assert "blueprints.report.routes.expense_ai.internal_expense_extract" in app.extensions["csrf"]._exempt_views
