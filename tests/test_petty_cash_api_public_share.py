"""The public share read (``blueprints/petty_cash_api/routes/public_share.py``):
``GET /api/petty-cash/v1/public/share/<initials>/<date>/<secret>``, the JSON the petty-cash web apps'
``/share/<path>`` page shows - the read-only Daily Report Flask's ``/Minty_Report/<path>/`` shows.

It is the ONE route beside the bearer API with no token: these tests pin that it is the only one,
that it answers no more than the shared page shows (no ids, permissions, options or receipt
access), that every refusal reads the same except an expired link (410, row deleted), and that the
secret never reaches the log. Flask's page and this route open a link through the same
``share.resolve_share`` (pinned by tests/test_share_link_access.py).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import char_factories as F
import pytest
from test_report_actions_state import _set, _submitted  # noqa: F401
from test_report_submit_state import D3, _ready, db, shop  # noqa: F401  (fixtures)

pytestmark = pytest.mark.char

WEB = "http://localhost:3010"
PUBLIC = "/api/petty-cash/v1/public/share/"
GONE = {"error": "This link doesn't work. Ask the person who shared it for a new link."}
EXPIRED = {"error": "This link has expired. Ask the person who shared it for a new link."}


def _share(app, client, entity, owner, report):
    resp = client.post(
        f"/api/petty-cash/v1/companies/{entity.id}/reports/{report}/share-link",
        headers=F.petty_cash_headers(app, owner.id, origin=WEB),
    )
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def _read(app, path, origin=WEB):
    # a fresh client: no session, no token - anyone holding the link
    return app.test_client().get(PUBLIC + path, headers={"Origin": origin})


def _link(app, entity_id):
    from models.db import ShareLink

    with app.app_context():
        return ShareLink.query.filter_by(entity_id=entity_id).one_or_none()


def _keys(value, prefix=""):
    """Every key in a JSON answer, dotted."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{prefix}{k}"
            yield from _keys(v, f"{prefix}{k}.")
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v, prefix)


@pytest.fixture
def shared(app, client, db, shop):  # noqa: F811
    owner, entity = shop
    report = _submitted(app, client, db, entity, owner)
    return owner, entity, report, _share(app, client, entity, owner, report)


# --- the share-link answer -----------------------------------------------------------------------


def test_the_share_link_answers_the_path_the_apps_build_their_own_page_from(app, shared):
    _owner, _entity, _report, body = shared

    assert set(body) == {"url", "path", "expires_at"}
    assert re.fullmatch(r"[A-Za-z]+/\d{2}_[A-Z][a-z]{2}_\d{4}/[A-Za-z0-9_-]{32}", body["path"])
    assert body["url"].endswith(f"/Minty_Report/{body['path']}/")
    expires = datetime.fromisoformat(body["expires_at"])
    assert expires.tzinfo is not None
    assert timedelta(days=29) < expires - datetime.now(timezone.utc) <= timedelta(days=30)


# --- the read ------------------------------------------------------------------------------------


def test_anyone_with_the_link_reads_the_day_and_nothing_more(app, db, shared):  # noqa: F811
    from models.db import ReportExpense

    owner, entity, report, body = shared
    with app.app_context():
        line = ReportExpense.query.filter_by(report_id=report).one()
        line.set_receipt_keys([f"{entity.id}/receipts/lunch.jpg"])
        db.session.commit()

    resp = _read(app, body["path"])

    assert resp.status_code == 200, resp.get_json()
    day = resp.get_json()
    assert set(day) == {
        "company_name", "transaction_date", "currency_code", "status", "status_label", "status_tone",
        "publishing_status", "submitted_at", "submitted_by", "kpis", "sales", "expenses", "cash",
        "closing_balance", "expires_at",
    }
    assert day["company_name"] == entity.name and day["transaction_date"] == F.iso(D3)
    assert (day["status"], day["status_label"], day["status_tone"]) == ("submitted", "Submitted", "info")
    assert day["submitted_by"] == "Olive User" and day["submitted_at"]
    assert day["kpis"] == {"total_sales": 0, "total_expenses": 15, "cash_position": 55}
    assert set(day["sales"]) == {"methods", "cash", "total"}
    assert day["expenses"] == {
        "lines": [{"item": "Advertising", "supplier_name": None, "amount": 15, "receipts": [{"name": "lunch.jpg"}]}],
        "total": 15,
    }
    assert day["cash"]["difference"] == {"amount": 0, "kind": "none", "reason": ""}
    assert day["cash"]["expected"] == 55 and day["closing_balance"] == 55
    assert day["expires_at"] == body["expires_at"]
    # no ids, no permissions, no options, no file keys
    keys = set(_keys(day))
    assert not [k for k in keys if k.split(".")[-1] in {"id", "sale_id", "report_id", "key", "s3_key", "mime_type"}
                or k.endswith("_id") or k.split(".")[0] in {"permissions", "options"}], keys
    assert f"{entity.id}" not in resp.get_data(as_text=True)


def test_the_answer_is_never_cached_or_leaked_by_referrer_and_only_our_web_may_read_it(app, shared, monkeypatch):
    path = shared[3]["path"]

    resp = _read(app, path)
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["Access-Control-Allow-Origin"] == WEB
    assert "Access-Control-Allow-Credentials" not in resp.headers
    assert resp.headers["Access-Control-Allow-Methods"] == "GET, OPTIONS"

    assert _read(app, path, origin="https://evil.example").headers["Access-Control-Allow-Origin"] == WEB
    preview = "https://pr-feat-x-pettycash.dailyminty.com"
    monkeypatch.setenv("PREVIEW_ORIGIN_REGEX", r"^https://pr-[a-z0-9-]+-(?:my|pettycash)\.dailyminty\.com$")
    assert _read(app, path, origin=preview).headers["Access-Control-Allow-Origin"] == preview
    # a refusal carries them too
    refused = _read(app, "AB/01_Jan_2026/" + "B" * 32)
    assert refused.headers["Cache-Control"] == "no-store" and refused.headers["Referrer-Policy"] == "no-referrer"
    assert refused.headers["Access-Control-Allow-Origin"] == WEB


# --- refusals ------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["old two-part form", "not a secret", "guessed secret", "date edited", "empty"])
def test_a_wrong_address_is_one_404(app, shared, kind):
    path = shared[3]["path"]
    prefix, secret = path.rsplit("/", 1)
    initials, date = prefix.split("/")
    guess = {
        "old two-part form": prefix,
        "not a secret": f"{prefix}/short",
        "guessed secret": f"{prefix}/{'B' * 32}",
        "date edited": f"{initials}/01_Jan_2020/{secret}",
        "empty": "",
    }[kind]

    resp = _read(app, guess)
    assert resp.status_code == 404
    if kind != "empty":  # Flask's own 404 for a rule that never matched
        assert resp.get_json() == GONE


def test_a_token_that_fails_its_signature_is_404_and_removed(app, db, shared):  # noqa: F811
    from models.db import ShareLink

    _owner, entity, _report, body = shared
    with app.app_context():
        ShareLink.query.filter_by(entity_id=entity.id).one().token = "tampered"
        db.session.commit()

    resp = _read(app, body["path"])
    assert (resp.status_code, resp.get_json()) == (404, GONE)
    assert _link(app, entity.id) is None


def test_a_token_for_another_day_is_404_and_kept(app, db, shared):  # noqa: F811
    from models.db import ShareLink
    from utils import generate_share_token

    _owner, entity, _report, body = shared
    with app.app_context():
        link = ShareLink.query.filter_by(entity_id=entity.id).one()
        link.token = generate_share_token(entity.id, "2020-01-01", app.config["SECRET_KEY"])
        db.session.commit()

    resp = _read(app, body["path"])
    assert (resp.status_code, resp.get_json()) == (404, GONE)
    assert _link(app, entity.id) is not None


@pytest.mark.parametrize("change", ["draft", "deleted"])
def test_a_day_back_to_draft_or_gone_is_404(app, db, shared, change):  # noqa: F811
    from models.db import Report

    _owner, entity, report, body = shared
    if change == "draft":
        _set(app, report, status="draft")
    else:
        with app.app_context():
            Report.query.filter_by(id=report).delete()  # the database cascades its lines
            db.session.commit()

    resp = _read(app, body["path"])
    assert (resp.status_code, resp.get_json()) == (404, GONE)


def test_an_expired_link_is_410_and_removed(app, db, shared):  # noqa: F811
    from models.db import ShareLink

    _owner, entity, _report, body = shared
    with app.app_context():
        ShareLink.query.filter_by(entity_id=entity.id).one().expires_at = (
            datetime.now(timezone.utc) - timedelta(minutes=1))
        db.session.commit()

    resp = _read(app, body["path"])
    assert (resp.status_code, resp.get_json()) == (410, EXPIRED)
    assert _link(app, entity.id) is None
    # then it is simply unknown
    assert _read(app, body["path"]).status_code == 404


def test_a_failure_is_a_generic_500_and_the_secret_never_reaches_the_log(app, shared, monkeypatch):
    from loguru import logger

    import blueprints.petty_cash_api.routes.public_share as public_share

    path = shared[3]["path"]
    secret = path.rsplit("/", 1)[1]

    def boom(*_a, **_k):
        raise RuntimeError(f"database fell over near {secret}")

    monkeypatch.setattr(public_share, "shared_payload", boom)
    lines = []
    sink = logger.add(lines.append, level="DEBUG")
    try:
        resp = _read(app, path)
    finally:
        logger.remove(sink)

    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Something went wrong on our side. Please try again."}
    assert resp.headers["Access-Control-Allow-Origin"] == WEB
    assert any("public share failure: RuntimeError" in str(line) for line in lines)
    assert not [line for line in lines if secret in str(line)]


def test_opening_a_link_logs_its_row_never_its_secret(app, shared):
    from loguru import logger

    _owner, entity, _report, body = shared
    secret = body["path"].rsplit("/", 1)[1]
    lines = []
    sink = logger.add(lines.append, level="DEBUG")
    try:
        assert _read(app, body["path"]).status_code == 200
        assert _read(app, body["path"].rsplit("/", 1)[0] + "/" + "C" * 32).status_code == 404
    finally:
        logger.remove(sink)

    assert any(f"link={_link(app, entity.id).id}" in str(line) for line in lines)
    assert not [line for line in lines if secret in str(line) or "C" * 32 in str(line)]


# --- only this route is public ---------------------------------------------------------------------


def test_the_only_route_beside_the_bearer_api_is_this_one_get(app):
    """Everything under /api/petty-cash/ is behind the guard (``petty_cash_api``'s rules, each
    naming the company), except this one read."""
    outside = [
        (str(r), r.endpoint, sorted(r.methods - {"HEAD", "OPTIONS"}))
        for r in app.url_map.iter_rules()
        if str(r).startswith("/api/petty-cash/") and not r.endpoint.startswith("petty_cash_api.")
    ]
    assert outside == [("/api/petty-cash/v1/public/share/<path:share_path>", "petty_cash_public.shared_report", ["GET"])]
    # and the guard is not registered on the public blueprint (nor it on the guarded one)
    assert "petty_cash_public" not in app.before_request_funcs
    assert app.blueprints["petty_cash_public"].before_request_funcs == {}


def test_it_writes_nothing_but_an_expired_or_forged_links_removal(app, client, shared):
    """A POST to it is not served: the route is GET only."""
    assert client.post(PUBLIC + shared[3]["path"]).status_code == 405
