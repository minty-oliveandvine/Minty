"""Shared setup for the characterisation suite (docs/modernisation/modernisation_plan.md, Part 1 B3).

These tests pin behaviour *through routes and services* so the schema redesign can be
applied underneath them. Everything here therefore goes through the real code path
where one exists (``replace_sales_methods`` seeds sales methods, the wizard routes
create reports) and falls back to the model only for reference data that has no
service (currency, country, denominations, the module catalogue).

Two rules, because the models are what the redesign changes:

* Never assert on a model attribute in a characterisation test. Read what the user
  sees: a page, a JSON payload, a row count through a service.
* Build ids as real uuid4 strings. SQLite accepted anything; the redesigned schema
  has ``uuid`` columns and rejects ``"report-1"``.
* Factories return plain snapshots (``SimpleNamespace`` of ids and names), never ORM
  rows - see ``snapshot``.

Runs on the PostgreSQL build of ``docs/schema/01_schema_rebased.sql`` (tests/pg_harness.py;
the only fixture since C10 - the SQLite path built the models' shape, not the schema's).
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

from werkzeug.security import generate_password_hash


def snapshot(row, *fields):
    """Plain values copied off an ORM row.

    ``pettycash/core/hooks.py`` removes the session at the end of every request -
    including the fake one ``client.session_transaction()`` makes - so an instance a
    test holds across a request is detached and its attributes expire. Tests keep
    ids and names, never live rows.
    """
    return SimpleNamespace(**{f: getattr(row, f) for f in fields})


def reset_database(app):
    """Session settings for a characterisation module (call inside an app context).

    Mirrors the per-file ``db_session`` fixtures the suite already has, so a new
    characterisation file needs one fixture line, not thirty.
    """
    from models.db import db

    db.session.expire_on_commit = False


def truncate_all(app):
    """Empty every table the models know: one ``TRUNCATE ... CASCADE``.

    The schema's real foreign keys (many of which the models do not declare) make
    per-table DELETEs fail in the wrong order, and a swallowed failure left
    ``currency_info`` rows behind for the next test to trip on.
    """
    from models.db import db

    db.session.rollback()
    names = ", ".join(t.fullname for t in db.metadata.sorted_tables)
    db.session.execute(db.text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    db.session.commit()


def new_id() -> str:
    return str(uuid.uuid4())


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def co(app_or_client, entity_id) -> str:
    """A company's address prefix, ``/entity/<shortid>/<name>`` - what every company page
    hangs off since 2026-10-05 (blueprints/shared/entity_ref.py). Takes the app or a test
    client."""
    from blueprints.shared.entity_ref import canonical_ref

    app = getattr(app_or_client, "application", app_or_client)
    with app.app_context():
        return "/entity/" + canonical_ref(entity_id)


def login(client, user, *, accepted_terms=True) -> None:
    """Sign in as ``user``. The terms gate (blueprints/legal) blocks every route until the
    live Terms version is accepted, so a signed-in user has agreed unless a test says
    otherwise - recorded through the real service so the consent row is real."""
    if accepted_terms:
        from blueprints.legal.services.consent import record_consent
        from models.db import db

        with client.application.app_context():
            record_consent(user.id, source="gate")
            db.session.commit()
    with client.session_transaction() as sess:
        sess["_user_id"] = user.id


# ---- reference data ------------------------------------------------------------


def seed_currency(db, code="HKD", *, denominations=(1000, 500, 100, 50, 20, 10, 5, 2, 1, 0.5, 0.2, 0.1)):
    """A currency with its cash denominations (what a cash count is made of).

    ``denominations=()`` seeds the currency alone - for tests that never count cash
    (identity, tokens, entities). ``cash_info`` changes shape in C4; until then its
    rows cannot be written to the rebased schema, and a test that does not need them
    should not fail on them.
    """
    from models.db import CashInfo, CurrencyInfo

    currency = CurrencyInfo(
        id=new_id(), currency_code=code, currency_name=code, symbol="$", decimal_places=2, is_active=True
    )
    db.session.add(currency)
    db.session.flush()
    for order, value in enumerate(denominations, start=1):
        db.session.add(
            CashInfo(
                currency_id=currency.id,
                cash_value=value,
                type="note" if value >= 10 else "coin",
                cash_name=str(value),
                display_order=order,
                is_active=True,
            )
        )
    db.session.commit()
    return snapshot(currency, "id", "currency_code")


def seed_country(db, currency, code="HK"):
    from models.db import CountryInfo

    row = CountryInfo(
        country_code=code, alpha3_code="HKG", country_name_en="Hong Kong",
        currency_id=currency.id, is_active=True, display_order=1,
    )
    db.session.add(row)
    db.session.commit()
    return snapshot(row, "country_code", "currency_id")


def seed_module(db, code="PETTY_CASH", name="Petty Cash"):
    from models.db import EntityFunction

    row = EntityFunction.query.filter_by(function_code=code).first()
    if row is None:
        now = _now()
        row = EntityFunction(id=new_id(), function_code=code, function_name=name, is_active=True,
                             description=name, created_at=now, updated_at=now)
        db.session.add(row)
        db.session.commit()
    return row


# ---- people and companies -------------------------------------------------------


def make_user(db, email="user@test.com", *, system_role=None, first_name="Test", last_name="User"):
    from models.db import User

    row = User(
        id=new_id(),
        email=email,
        username=email,
        first_name=first_name,
        last_name=last_name,
        password=generate_password_hash("password123", method="pbkdf2:sha256"),  # the app's method; scrypt overflows the 150-char column on Postgres
        system_role=system_role or User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(row)
    db.session.commit()
    return snapshot(row, "id", "email", "username", "first_name", "last_name")


def make_entity(db, owner, *, name="Acme Shop", role="admin", currency=None, country=None,
                modules=("PETTY_CASH",), status="disconnected"):
    """An entity the owner belongs to, with the given modules switched on.

    ``status`` is the ``entity_status`` enum: a live company with no Xero organisation is
    ``disconnected`` (``connect_xero`` makes it ``connected``). ``created_by`` on the module
    map row is the owner, as the app writes it (schema section 4).
    """
    from models.db import Entity, EntityFunctionMap, UserEntity

    entity = Entity(
        id=new_id(),
        name=name,
        status=status,
        currency_id=currency.id if currency is not None else None,
        country_code=country.country_code if country is not None else None,
    )
    db.session.add(entity)
    db.session.flush()
    db.session.add(UserEntity(user_id=owner.id, entity_id=entity.id, role=role, approved=True))
    for code in modules:
        fn = seed_module(db, code, code.replace("_", " ").title())
        now = _now()
        db.session.add(
            EntityFunctionMap(
                entity_id=entity.id, entity_function_id=fn.id,
                is_enabled=True, created_by=owner.id, enabled_at=now,
                created_at=now, updated_at=now,
            )
        )
    db.session.commit()
    return snapshot(entity, "id", "name", "status")


def seed_sales_methods(db, owner, entity, *, electronic=("Visa", "Alipay"), delivery=("Foodpanda",)):
    """Through the real service, so the catalogue + per-entity rows land as production writes them."""
    from blueprints.entity.services.payment_methods import replace_sales_methods

    result = replace_sales_methods(owner.id, entity.id, list(electronic), list(delivery))
    payload, status = result if isinstance(result, tuple) else (result, 200)
    assert status == 200, payload
    return payload


def enabled_sales_methods(app, entity_id):
    """value_name -> (type, sale_name) for the methods the sales form will show."""
    from blueprints.report.routes.sales import get_unique_sale_info_for_entity

    with app.app_context():
        return {m.value_name: (m.type, m.sale_name) for m in get_unique_sale_info_for_entity(entity_id)}


def denomination_fields(app, entity_id):
    """form field name -> face value, in the order the cash-count form renders them."""
    from blueprints.report.services.cash_denominations import (form_field_for,
                                                               resolve_denominations_for_entity)

    with app.app_context():
        return {form_field_for(d): float(d.cash_value) for d in resolve_denominations_for_entity(entity_id)}


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---- the S3 boundary --------------------------------------------------------------


class FakeS3:
    """In-memory stand-in for the boto3 S3 client, installed at ``get_s3_client``.

    Stubbing OUR function (``upload_file_to_s3``) would skip the code that names the
    key and records it on the expense - the onboarding suite learned that lesson the
    hard way. The transport is the right seam: every call the report code makes is
    here, and ``objects`` lets a test assert what was stored or deleted.
    """

    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def upload_fileobj(self, fileobj, bucket, key, **kwargs):
        self.objects[key] = fileobj.read()

    def put_object(self, *, Bucket, Key, Body=b"", **kwargs):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.read()

    def get_object(self, *, Bucket, Key, **kwargs):
        from io import BytesIO

        if Key not in self.objects:
            raise KeyError(Key)
        return {"Body": BytesIO(self.objects[Key]), "ContentLength": len(self.objects[Key])}

    def head_object(self, *, Bucket, Key, **kwargs):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}

    def delete_object(self, *, Bucket, Key, **kwargs):
        self.objects.pop(Key, None)
        self.deleted.append(Key)

    def delete_objects(self, *, Bucket, Delete, **kwargs):
        for obj in Delete.get("Objects", []):
            self.delete_object(Bucket=Bucket, Key=obj["Key"])
        return {"Deleted": Delete.get("Objects", [])}

    def generate_presigned_url(self, operation, Params=None, ExpiresIn=3600, **kwargs):
        return f"https://fake-s3.test/{(Params or {}).get('Key', '')}"


def install_fake_s3(monkeypatch) -> FakeS3:
    from blueprints.report.services import s3_storage

    fake = FakeS3()
    real = s3_storage.get_s3_client
    monkeypatch.setattr(s3_storage, "get_s3_client", lambda: fake)
    # Route modules import the function by name (``from ...s3_storage import
    # get_s3_client``), so the name they bound must be patched too - or the delete
    # paths in report_detail.py reach for the real endpoint while the uploads land here.
    import sys

    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").startswith("blueprints.") and getattr(module, "get_s3_client", None) is real:
            monkeypatch.setattr(module, "get_s3_client", lambda: fake)
    return fake


def receipt(name="receipt.jpg"):
    """A file upload for an expense line (every expense must carry one)."""
    from io import BytesIO

    return (BytesIO(b"\xff\xd8\xff\xe0fake-jpeg-bytes"), name)


# ---- the mail boundary ------------------------------------------------------------


class FakeMail:
    """Records every Flask-Mail message instead of sending it.

    Installed on ``flask_mail._MailMixin.send`` - the library boundary, so the code that
    builds the message (sender, recipients, the accept link in the body) still runs. The
    app configures ``TESTING`` *after* ``Mail(app)``, so Flask-Mail does not suppress
    delivery in tests and really tries SMTP on localhost (connection refused); routes
    then report ``email_sent: false`` or, for invitation resend, a 502. ``_MailMixin``
    rather than ``Mail`` because ``current_app.extensions["mail"]`` is the ``_Mail`` state
    object, which only shares the mixin.
    """

    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def to(self, address):
        return [m for m in self.messages if address in (m.recipients or [])]


def install_fake_mail(monkeypatch) -> FakeMail:
    import flask_mail

    fake = FakeMail()
    monkeypatch.setattr(flask_mail._MailMixin, "send", lambda self, message: fake.send(message))
    return fake


# ---- Xero connection state ---------------------------------------------------------


def store_xero_tokens(db, user, tokens: dict):
    """Through the real service - the same call the OAuth callback and every refresh make
    (services/auth/token_service.apply_refreshed_tokens). Today that writes the user_token
    row AND the shadow columns on ``user``; C1 collapses it to the row."""
    from models.db import User
    from services.auth.token_service import apply_refreshed_tokens

    assert apply_refreshed_tokens(User.query.get(user.id), tokens), "apply_refreshed_tokens stored nothing"


def connect_xero(db, user, entity, *, tenant_id: str, tokens: dict):
    """The end state of a successful OAuth callback for ``entity`` by ``user``."""
    from datetime import datetime, timezone

    from models.db import Entity

    row = Entity.query.get(entity.id)
    row.xero_org_id = tenant_id
    row.connected_by_user_id = user.id
    row.last_connected_at = datetime.now(timezone.utc)
    row.status = "connected"  # what the callback writes (xero/routes/routes.py)
    db.session.commit()
    store_xero_tokens(db, user, tokens)


def age_xero_token(db, user, *, seconds: int):
    """Make the stored access token look ``seconds`` old (setup, not an assertion)."""
    from datetime import datetime, timedelta

    from models.db import UserToken

    row = UserToken.query.filter_by(user_id=user.id).first()
    assert row is not None
    row.access_token_obtained_at = datetime.now() - timedelta(seconds=seconds)
    db.session.commit()
