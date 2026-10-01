from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import char_factories as F

_SECRET = "A" * 32


class _FakeFilterQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *_args, **_kwargs):
        return self

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._result


class _FakeGetQuery:
    def __init__(self, result):
        self._result = result

    def get(self, *_args, **_kwargs):
        return self._result


def test_generate_share_link_route_does_not_call_permission_checks(
    app, monkeypatch
):
    from blueprints.report.routes import api

    handler = getattr(api.generate_share_link, "__wrapped__", api.generate_share_link)
    called = {}

    def fake_create_share_link(user_id, payload):
        called["user_id"] = user_id
        called["payload"] = payload
        return {"url": "https://example.test/Minty_Report/AB/01_Jan_2026"}, 200

    with app.app_context():
        with app.test_request_context(
            "/api/generate_share_link",
            method="POST",
            json={"entity_id": "entity-1", "transaction_date": "2026-01-01"},
        ):
            monkeypatch.setattr(
                api,
                "has_permission",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    AssertionError("generate_share_link should not check has_permission")
                ),
            )
            monkeypatch.setattr(api, "current_user", SimpleNamespace(id="user-1"))
            monkeypatch.setattr(
                api, "create_share_link_for_report", fake_create_share_link
            )

            response, status = handler()

    assert status == 200
    assert response.get_json()["url"] == "https://example.test/Minty_Report/AB/01_Jan_2026"
    assert called["user_id"] == "user-1"
    assert called["payload"]["entity_id"] == "entity-1"


def test_create_share_link_for_report_uses_membership_not_role_permissions(
    app, monkeypatch
):
    from blueprints.report.services import share

    captured = {}

    with app.app_context():
        monkeypatch.setattr(
            share.UserEntity, "query", _FakeFilterQuery(SimpleNamespace(id="membership"))
        )
        monkeypatch.setattr(
            share.Entity, "query", _FakeGetQuery(SimpleNamespace(name="Acme Bistro"))
        )
        monkeypatch.setattr(share.ShareLink, "query", _FakeFilterQuery(None))

        monkeypatch.setattr(
            share,
            "generate_share_token",
            lambda *_args, **_kwargs: captured.setdefault("token", "token-value"),
        )

        def fake_add(link):
            captured["added_link"] = link

        def fake_commit():
            captured["committed"] = True

        monkeypatch.setattr(share.db.session, "add", fake_add)
        monkeypatch.setattr(share.db.session, "delete", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(share.db.session, "commit", fake_commit)

        with app.test_request_context("/"):
            response, status = share.create_share_link_for_report(
                "user-1",
                {"entity_id": "entity-1", "transaction_date": "2026-01-01"},
            )

    assert status == 200
    assert captured["committed"] is True
    added = captured["added_link"]
    assert re.fullmatch(r"AB/01_Jan_2026/[A-Za-z0-9_-]{32}", added.path_segment)
    assert response["url"].endswith(f"/Minty_Report/{added.path_segment}/")
    assert added.entity_id == "entity-1"
    assert added.transaction_date == date(2026, 1, 1)


def test_generate_share_link_denies_membership_missing(app, monkeypatch):
    from blueprints.report.services import share

    with app.app_context():
        monkeypatch.setattr(share.UserEntity, "query", _FakeFilterQuery(None))

        response, status = share.create_share_link_for_report(
            "user-1",
            {"entity_id": "entity-1", "transaction_date": "2026-01-01"},
        )

    assert status == 403
    assert response["error"] == "You don't have access to this entity"


def test_public_share_route_calls_report_ending_without_auth_gate(app, monkeypatch):
    from blueprints.report.routes import legacy
    from blueprints.report.services import ending as ending_service

    called = {}
    future = datetime.now() + timedelta(days=1)
    share_link = SimpleNamespace(
        id="link-1",
        token="signed-token",
        entity_id="entity-1",
        transaction_date=date(2026, 3, 11),
        expires_at=future,
    )

    with app.app_context():
        monkeypatch.setattr(legacy.ShareLink, "query", _FakeFilterQuery(share_link))
        monkeypatch.setattr(legacy.Entity, "query", _FakeGetQuery(SimpleNamespace()))
        monkeypatch.setattr(
            legacy.Report, "query", _FakeFilterQuery(SimpleNamespace(id="report-1"))
        )
        monkeypatch.setattr(
            legacy,
            "verify_share_token",
            lambda *_args, **_kwargs: (
                True,
                {"entity_id": "entity-1", "transaction_date": "2026-03-11"},
            ),
        )

        def fake_report_ending(id=None, entity_id=None, skip_auth=False):
            called["id"] = id
            called["entity_id"] = entity_id
            called["skip_auth"] = skip_auth
            return ("shared-report", 200)

        monkeypatch.setattr(ending_service, "report_ending", fake_report_ending)

        with app.test_request_context(f"/Minty_Report/AB/11_Mar_2026/{_SECRET}/"):
            response = legacy.minty_report_share(f"AB/11_Mar_2026/{_SECRET}")

    assert response == ("shared-report", 200)
    assert called["id"] == "report-1"
    assert called["entity_id"] == "entity-1"
    assert called["skip_auth"] is True


# --- Through the real database: guessing and same-initials collisions ------------------

SHARE_DAY = date(2026, 9, 27)


@pytest.fixture
def db(app):
    from models.db import db as _db

    with app.app_context():
        F.reset_database(app)
    yield _db
    with app.app_context():
        F.truncate_all(app)


@pytest.fixture
def twins(app, db):
    """Two companies whose share-link initials match ("DAV"), each with a submitted
    report on SHARE_DAY and the day before."""
    from blueprints.shared.enums import ReportStatus
    from models.db import Report

    with app.app_context():
        owner = F.make_user(db, "owner@test.com")
        venus = F.make_entity(db, owner, name="Dine at Venus")
        venus2 = F.make_entity(db, owner, name="Dine at Venus 2")
        for entity in (venus, venus2):
            for day in (SHARE_DAY, SHARE_DAY - timedelta(days=1)):
                db.session.add(Report(entity_id=entity.id, transaction_date=day,
                                      status=ReportStatus.SUBMITTED, created_by=owner.id))
        db.session.commit()
    return owner, venus, venus2


@pytest.fixture
def rendered(monkeypatch):
    """Stand in for the ending page: record which company the link rendered."""
    from blueprints.report.services import ending as ending_service

    seen = []

    def fake_report_ending(id=None, entity_id=None, skip_auth=False):
        seen.append(str(entity_id))
        return f"report-of-{entity_id}"

    monkeypatch.setattr(ending_service, "report_ending", fake_report_ending)
    return seen


def _share(app, user_id, entity_id, day=SHARE_DAY) -> str:
    """Create the link through the service; return its path after /Minty_Report/."""
    from blueprints.report.services import share

    with app.test_request_context("/"):
        body, status = share.create_share_link_for_report(
            user_id, {"entity_id": entity_id, "transaction_date": day.isoformat()})
    assert status == 200, body
    return body["url"].split("/Minty_Report/", 1)[1]


def _open(client, path):
    return client.get(f"/Minty_Report/{path}", follow_redirects=False)


def test_same_initials_get_separate_links_that_each_show_their_own_company(
        app, client, twins, rendered):
    owner, venus, venus2 = twins

    venus_path = _share(app, owner.id, venus.id)
    venus2_path = _share(app, owner.id, venus2.id)

    assert venus_path.startswith("DAV/27_Sep_2026/")
    assert venus2_path.startswith("DAV/27_Sep_2026/")
    assert venus_path != venus2_path

    assert _open(client, venus_path).status_code == 200
    assert _open(client, venus2_path).status_code == 200
    # The first company's link still shows the first company after the second shared.
    assert rendered == [str(venus.id), str(venus2.id)]


def test_sharing_the_same_day_again_keeps_the_url_and_renews_expiry(app, db, twins):
    from models.db import ShareLink

    owner, venus, _ = twins
    first = _share(app, owner.id, venus.id)
    with app.app_context():
        link = ShareLink.query.filter_by(entity_id=venus.id).one()
        link.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.session.commit()

    assert _share(app, owner.id, venus.id) == first
    with app.app_context():
        links = ShareLink.query.filter_by(entity_id=venus.id).all()
        assert len(links) == 1
        assert links[0].expires_at > datetime.now(timezone.utc) + timedelta(days=29)


def test_guessed_or_edited_paths_are_refused(app, client, twins, rendered):
    owner, venus, _ = twins
    path = _share(app, owner.id, venus.id)
    prefix, secret = path.rstrip("/").rsplit("/", 1)

    for guess in (
        "DAV/27_Sep_2026/",                       # no secret: the old guessable form
        f"DAV/26_Sep_2026/{secret}/",             # date edited
        f"{prefix}/{'B' * 32}/",                  # secret guessed
        f"{prefix}/{secret[:-1]}/",               # secret truncated
    ):
        resp = _open(client, guess)
        assert resp.status_code == 302, guess
        assert "/entity" in resp.headers["Location"], guess
    assert rendered == []


def test_an_old_form_row_still_in_the_database_is_refused_and_replaced(
        app, db, client, twins, rendered):
    from models.db import ShareLink

    owner, venus, _ = twins
    with app.app_context():
        db.session.add(ShareLink(
            path_segment="DAV/27_Sep_2026", token="legacy", entity_id=venus.id,
            transaction_date=SHARE_DAY,
            expires_at=datetime.now(timezone.utc) + timedelta(days=10)))
        db.session.commit()

    assert _open(client, "DAV/27_Sep_2026/").status_code == 302
    assert rendered == []

    # Sharing that day again moves the row to a secret path; the old address stays dead.
    new_path = _share(app, owner.id, venus.id)
    assert new_path.startswith("DAV/27_Sep_2026/") and new_path != "DAV/27_Sep_2026/"
    assert _open(client, new_path).status_code == 200
    with app.app_context():
        assert ShareLink.query.filter_by(entity_id=venus.id).count() == 1


def test_expired_link_is_refused_and_removed(app, db, client, twins, rendered):
    from models.db import ShareLink

    owner, venus, _ = twins
    path = _share(app, owner.id, venus.id)
    with app.app_context():
        link = ShareLink.query.filter_by(entity_id=venus.id).one()
        link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.session.commit()

    resp = _open(client, path)
    assert resp.status_code == 302
    assert rendered == []
    with app.app_context():
        assert ShareLink.query.filter_by(entity_id=venus.id).count() == 0
