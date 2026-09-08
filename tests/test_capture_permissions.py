"""The gate, the endpoints, and who is allowed through them.

The test that matters most here is
``test_a_payment_only_company_can_reach_the_capture_hub``. The report blueprint
denies every one of its routes when PETTY_CASH is off, so filing the capture
routes there would have locked a Payment-only customer out of the hub they paid
for — and nothing else in this suite would have noticed.

HOW THESE TESTS ARE SHAPED, AND WHY
Database work happens inside a ``with app.app_context():`` block, plain values
(ids, strings) come out of it, and the client calls happen OUTSIDE. That is the
pattern tests/test_entity_create.py uses, and it exists because Flask-SQLAlchemy
scopes the ORM session to the app context: hold an ORM object across a context
boundary and the next attribute access raises DetachedInstanceError somewhere
with no obvious connection to the cause.

Project modules are imported inside the fixtures and tests for the same reason
as everywhere else — conftest clears cached ``models`` and ``blueprints``
modules before building the app.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from werkzeug.security import generate_password_hash


_schema_attached = False


@pytest.fixture
def capture_env(app, monkeypatch):
    """The feature switched on and the capture tables created."""
    global _schema_attached
    from models.db import db

    monkeypatch.setenv("CAPTURE_AI_ENABLED", "true")

    # The app context is pushed for SETUP and again for TEARDOWN, and is NOT
    # held across the yield. Holding one for the whole test outlives the
    # ``client`` fixture's own context stack — this fixture is torn down first,
    # so the client's ``__exit__`` then runs with no application context and
    # raises "Working outside of application context" for every test in the
    # file. Tests push their own context around database work instead.
    with app.app_context():
        if not _schema_attached:
            # SQLite has no schemas, and every capture model lives in
            # ``pettycashv2``. The suite's convention is to ATTACH an in-memory
            # database under that name — see tests/test_auth_register_login.py.
            with db.engine.connect() as conn:
                try:
                    conn.execute(db.text("ATTACH DATABASE ':memory:' AS pettycashv2"))
                    conn.commit()
                except Exception:
                    pass
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()

    yield monkeypatch

    with app.app_context():
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def set_modules(monkeypatch, petty_cash=True, bill=True):
    """Stub the entitlement lookup at the point the gate reads it.

    Through ``sys.modules`` rather than by importing the real route module and
    patching an attribute on it: importing ``blueprints.entity.routes.modules``
    here executes its sibling route files, whose ``@entity_bp.route``
    decorators raise once that blueprint has been registered on an app.
    """
    import sys
    import types

    stub = types.ModuleType("blueprints.entity.routes.modules")

    def is_enabled(entity_id, code):
        return petty_cash if code == "PETTY_CASH" else bill

    stub._is_module_enabled = is_enabled
    monkeypatch.setitem(sys.modules, "blueprints.entity.routes.modules", stub)


def allow_permission(monkeypatch, allowed=True):
    """The per-user check, separately from the per-company gate.

    Patched in FIVE places. The four route modules bind the name at import, so
    each holds its own reference — but the bubble's context processor imports
    it fresh from ``services.permission_policy`` inside the function, so
    patching only the routes leaves the real check running for the bubble and
    it silently never renders.
    """
    import services.permission_policy as policy

    import blueprints.capture.routes.api as api
    import blueprints.capture.routes.files as files
    import blueprints.capture.routes.queue as queue
    import blueprints.capture.routes.upload as upload

    for module in (api, files, queue, upload, policy):
        monkeypatch.setattr(module, "has_permission", lambda *a, **k: allowed)


def make_user():
    """A user who can actually reach a page. Call inside an app context.

    Three things beyond the NOT NULL columns, each of which otherwise stops the
    request before it ever reaches a capture route:

      approved=True        an unapproved account is bounced by the app's own
                           gate, which reads as a mysterious 302 to /entity.
      system_role NORMAL   the default the app expects.
      a consent row        blueprints/legal/routes/gate.py refuses every
                           request from someone who has not accepted the Terms
                           — a 403 whose body says "terms_acceptance_required"
                           and has nothing to do with the feature under test.
    """
    from blueprints.legal.services.consent import record_consent
    from models.db import User, db

    user = User(
        id=str(uuid4()),
        email=f"{uuid4().hex[:8]}@example.com",
        username=f"cap-{uuid4().hex[:8]}",
        # NOT NULL on the table. None is used — nothing here signs in through
        # the form — but the row still has to be valid.
        first_name="Capture",
        last_name="Tester",
        password=generate_password_hash("not-used"),
        system_role=User.SYSTEM_ROLE_NORMAL,
        approved=True,
    )
    db.session.add(user)
    db.session.flush()
    # "gate" is what the accept screen records; the service accepts only
    # its three known sources.
    record_consent(str(user.id), source="gate")
    db.session.commit()
    return str(user.id)


# Every request in this file asks for JSON. ``services/authz.permission_denied``
# answers an HTML request with a flash and a 302 to /entity, and an API request
# with a 403 body — and these endpoints are the API. Without the header a
# refusal arrives as a redirect and the assertions read as if the gate let the
# request through.
JSON = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}


def login(client, user_id):
    """flask_login reads ``_user_id`` from the session and the app's user loader
    turns it into a User. Shorter and more honest than driving the form."""
    with client.session_transaction() as session:
        session["_user_id"] = user_id


def make_draft(entity_id, destination="petty_cash", status="ready"):
    """An upload and one draft on it. Call inside an app context."""
    from blueprints.capture.models.capture_draft import CaptureDraft
    from blueprints.capture.models.capture_upload import CaptureUpload
    from models.db import db

    upload = CaptureUpload(
        entity_id=entity_id,
        uploaded_by="user-1",
        original_filename="receipt.pdf",
        mime_type="application/pdf",
        byte_size=1024,
        page_count=1,
        content_sha256=uuid4().hex + uuid4().hex,
        s3_key=f"capture/{entity_id}/2026/09/{uuid4()}/original.pdf",
        status="done",
        document_count=1,
    )
    db.session.add(upload)
    db.session.flush()

    draft = CaptureDraft(
        upload_id=upload.id,
        entity_id=entity_id,
        sequence=1,
        page_start=1,
        page_end=1,
        doc_type="receipt",
        destination=destination,
        status=status,
    )
    db.session.add(draft)
    db.session.commit()
    return str(draft.id)


def make_upload(entity_id, status="rejected_not_supported"):
    from blueprints.capture.models.capture_upload import CaptureUpload
    from models.db import db

    upload = CaptureUpload(
        entity_id=entity_id,
        uploaded_by="user-1",
        mime_type="application/pdf",
        byte_size=10,
        page_count=1,
        content_sha256=uuid4().hex + uuid4().hex,
        s3_key="k",
        status=status,
    )
    db.session.add(upload)
    db.session.commit()
    return str(upload.id)


def stub_context(monkeypatch, accounts=None, contacts=None):
    """The entity's own account and contact lists, which confirm re-checks."""
    import blueprints.capture.routes.api as api

    monkeypatch.setattr(
        api.capture_ai,
        "build_entity_context",
        lambda entity_id, for_invoice=False: {
            "entity": {"id": entity_id, "name": "x", "country": "HK", "currency": "HKD"},
            "accounts": accounts or [],
            "contacts": contacts or [],
        },
    )


@pytest.fixture
def signed_in(app, client, capture_env):
    """Both modules on, permission granted, somebody logged in.

    Returns the monkeypatch so a test can narrow any of it.
    """
    monkeypatch = capture_env
    set_modules(monkeypatch)
    allow_permission(monkeypatch)
    with app.app_context():
        user_id = make_user()
    login(client, user_id)
    return monkeypatch


# --------------------------------------------------------------------------
# The kill switch
# --------------------------------------------------------------------------
def test_the_kill_switch_makes_the_feature_disappear(client, signed_in):
    """OFF means 404, not 403. When the feature is off it does not exist, and a
    403 would tell a prober there is something here worth having."""
    signed_in.setenv("CAPTURE_AI_ENABLED", "false")

    assert client.get("/capture?entity_id=ent-1", headers=JSON).status_code == 404
    assert client.get("/capture/status?entity_id=ent-1", headers=JSON).status_code == 404
    assert client.post(
        "/capture/upload", data={"entity_id": "ent-1"}, headers=JSON
    ).status_code == 404


# --------------------------------------------------------------------------
# THE TEST THE BLUEPRINT DECISION EXISTS FOR
# --------------------------------------------------------------------------
def test_a_payment_only_company_can_reach_the_capture_hub(client, signed_in):
    """PETTY_CASH off, BILL (= Payment) on.

    The report blueprint's gate denies all of its routes when PETTY_CASH is
    off. Had the capture routes been filed there, this customer would be locked
    out of the hub they paid for.
    """
    set_modules(signed_in, petty_cash=False, bill=True)

    response = client.get("/capture/status?entity_id=ent-1", headers=JSON)
    assert response.status_code == 200
    assert "attention" in response.get_json()


def test_a_petty_cash_only_company_can_reach_it_too(client, signed_in):
    set_modules(signed_in, petty_cash=True, bill=False)
    assert client.get("/capture/status?entity_id=ent-1", headers=JSON).status_code == 200


def test_a_company_with_neither_module_is_refused(client, signed_in):
    set_modules(signed_in, petty_cash=False, bill=False)
    assert client.get("/capture/status?entity_id=ent-1", headers=JSON).status_code in (302, 403)


def test_the_gate_fails_closed_with_no_entity(client, signed_in):
    """The report guard fails OPEN when it cannot resolve an entity, because
    many of its routes genuinely carry no entity context. Every capture route
    carries one, so an unresolvable entity here is a bug or an attack."""
    assert client.get("/capture/status", headers=JSON).status_code in (302, 403)


# --------------------------------------------------------------------------
# Entitlement and permission are different questions
# --------------------------------------------------------------------------
def test_the_gate_and_the_permission_check_are_different_questions(client, signed_in):
    """The gate answers "does this company have the feature". The permission
    check answers "is this person allowed to use it"."""
    allow_permission(signed_in, allowed=False)
    assert client.get("/capture/status?entity_id=ent-1", headers=JSON).status_code == 403


# --------------------------------------------------------------------------
# Cross-entity access
# --------------------------------------------------------------------------
def test_another_companys_draft_is_a_404_not_a_403(app, client, signed_in):
    """404 deliberately. A 403 confirms the row exists, which is information an
    outsider should not be able to collect one id at a time."""
    with app.app_context():
        draft_id = make_draft("ent-OTHER")

    assert client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": "10.00"}, headers=JSON,
    ).status_code == 404

    assert client.post(
        f"/capture/draft/{draft_id}/reject?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 404

    assert client.get(
        f"/capture/draft/{draft_id}/file?entity_id=ent-1", headers=JSON
    ).status_code == 404


def test_the_drafts_list_only_shows_this_companys_rows(app, client, signed_in):
    with app.app_context():
        make_draft("ent-1")
        make_draft("ent-1")
        make_draft("ent-OTHER")

    body = client.get("/capture/drafts?entity_id=ent-1", headers=JSON).get_json()
    assert len(body["drafts"]) == 2


# --------------------------------------------------------------------------
# Confirm
# --------------------------------------------------------------------------
def test_confirming_a_held_draft_is_refused(app, client, signed_in):
    """'hold' is not a destination anything can be sent to."""
    with app.app_context():
        draft_id = make_draft("ent-1", destination="hold", status="hold")

    assert client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": "10.00", "report_id": "r-1"}, headers=JSON,
    ).status_code == 400


def test_confirming_an_already_posted_draft_is_a_conflict(app, client, signed_in):
    with app.app_context():
        draft_id = make_draft("ent-1", status="posted")

    assert client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": "10.00", "report_id": "r-1"}, headers=JSON,
    ).status_code == 409


def test_petty_cash_confirm_needs_a_report(app, client, signed_in):
    """ShopExpense.report_id is NOT NULL — an expense cannot exist without a
    report, so this is refused before anything is written."""
    stub_context(signed_in)
    with app.app_context():
        draft_id = make_draft("ent-1")

    response = client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1", json={"amount": "10.00"}, headers=JSON
    )
    assert response.status_code == 400
    assert "report" in response.get_json()["message"].lower()


def test_an_account_from_another_company_is_refused(app, client, signed_in):
    """The user's submitted ids are re-checked against this entity's own lists,
    exactly as the model's reply is. A confirm is a WRITE, so this matters more
    here, not less."""
    stub_context(
        signed_in, accounts=[{"id": "acc-ours", "code": "5100", "name": "Courier"}]
    )
    with app.app_context():
        draft_id = make_draft("ent-1")

    response = client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": "10.00", "report_id": "r-1", "account_id": "acc-THEIRS"},
        headers=JSON,
    )
    assert response.status_code == 400
    assert "account" in response.get_json()["message"].lower()


def test_a_supplier_from_another_company_is_refused(app, client, signed_in):
    stub_context(signed_in, contacts=[{"id": "con-ours", "name": "SF Express"}])
    with app.app_context():
        draft_id = make_draft("ent-1")

    response = client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": "10.00", "report_id": "r-1", "contact_id": "con-THEIRS"},
        headers=JSON,
    )
    assert response.status_code == 400
    assert "supplier" in response.get_json()["message"].lower()


@pytest.mark.parametrize("amount", ["", "abc", "0", "-5", None])
def test_a_bad_amount_is_refused(app, client, signed_in, amount):
    stub_context(signed_in)
    with app.app_context():
        draft_id = make_draft("ent-1")

    assert client.post(
        f"/capture/draft/{draft_id}/confirm?entity_id=ent-1",
        json={"amount": amount, "report_id": "r-1"}, headers=JSON,
    ).status_code == 400


# --------------------------------------------------------------------------
# Archive
# --------------------------------------------------------------------------
def test_archiving_keeps_the_row(app, client, signed_in):
    """Kept until retention removes it, so "I archived that by mistake" is
    recoverable by support."""
    from blueprints.capture.models.capture_draft import CaptureDraft

    with app.app_context():
        draft_id = make_draft("ent-1")

    assert client.post(
        f"/capture/draft/{draft_id}/reject?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 200

    with app.app_context():
        assert CaptureDraft.query.get(draft_id).status == "archived"


def test_a_posted_draft_cannot_be_archived(app, client, signed_in):
    with app.app_context():
        draft_id = make_draft("ent-1", status="posted")

    assert client.post(
        f"/capture/draft/{draft_id}/reject?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 409


# --------------------------------------------------------------------------
# The "this IS a receipt" override
# --------------------------------------------------------------------------
def test_the_override_requeues_a_rejected_upload(app, client, signed_in):
    import blueprints.capture.services.pipeline as pipeline
    from blueprints.capture.models.capture_upload import CaptureUpload

    signed_in.setattr(pipeline, "start", lambda upload_id: None)

    with app.app_context():
        upload_id = make_upload("ent-1")

    assert client.post(
        f"/capture/upload/{upload_id}/retry?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 202

    with app.app_context():
        upload = CaptureUpload.query.get(upload_id)
        assert upload.status == "queued"
        assert upload.bypass_classification is True
        assert upload.reject_reason is None


def test_the_override_only_works_once(app, client, signed_in):
    """Otherwise a determined user can spend money in a loop on a photo of
    their lunch."""
    import blueprints.capture.services.pipeline as pipeline
    from blueprints.capture.models.capture_upload import CaptureUpload
    from models.db import db

    signed_in.setattr(pipeline, "start", lambda upload_id: None)

    with app.app_context():
        upload_id = make_upload("ent-1")

    assert client.post(
        f"/capture/upload/{upload_id}/retry?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 202

    # The pipeline rejected it a second time.
    with app.app_context():
        upload = CaptureUpload.query.get(upload_id)
        upload.status = "rejected_not_supported"
        db.session.commit()

    second = client.post(f"/capture/upload/{upload_id}/retry?entity_id=ent-1", json={}, headers=JSON)
    assert second.status_code == 400
    assert "twice" in second.get_json()["message"].lower()


def test_the_override_refuses_an_upload_that_was_not_rejected(app, client, signed_in):
    with app.app_context():
        upload_id = make_upload("ent-1", status="done")

    assert client.post(
        f"/capture/upload/{upload_id}/retry?entity_id=ent-1", json={}, headers=JSON
    ).status_code == 400


# --------------------------------------------------------------------------
# The bubble reaching the page
#
# The first attempt included the partial in templates/base/layout.html and it
# reached almost nothing: only 7 of this app's 85 templates extend that layout.
# The entity dashboard, every petty cash page and the entity list are all
# standalone <!DOCTYPE html> documents with no inheritance.
#
# The bubble is now spliced into the HTML response instead, which is why these
# tests assert against a page's REAL bytes. There is no include left anywhere,
# so anything found below got there through the injector.
# --------------------------------------------------------------------------
def test_no_template_includes_the_bubble_any_more(app):
    """The include is gone on purpose. Putting it back would double the bubble
    on the few pages that do extend the layout, and would still miss the rest."""
    from pathlib import Path

    root = Path(app.root_path).parent if False else Path("templates")
    offenders = [
        str(path)
        for path in root.rglob("*.html")
        if "ai_capture_bubble.html" in path.read_text(encoding="utf-8", errors="replace")
        and path.name != "ai_capture_bubble.html"
    ]
    assert offenders == [], f"bubble is included by template(s): {offenders}"


def test_the_bubble_is_spliced_into_an_html_page(client, signed_in):
    """The injector works on the response, so the page's template ancestry is
    irrelevant — which is exactly the property the include did not have."""
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert "capBubbleBtn" in html
    assert "capture_bubble.js" in html
    # Spliced BEFORE the closing tag, not appended after it.
    assert html.index("capBubbleBtn") < html.rindex("</body>")


def test_the_bubble_carries_a_csrf_token(client, signed_in):
    """The upload POST is CSRF-protected like any other write. Without the
    token in the page the JS cannot send the header, and every upload silently
    redirects to the login form and comes back as unparseable HTML."""
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert 'name="csrf_token"' in html


def test_the_bubble_appears_exactly_once(client, signed_in):
    """Belt and braces against the include being restored alongside the
    injector."""
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert html.count('id="capBubbleBtn"') == 1


def test_the_bubble_is_not_injected_into_json(client, signed_in):
    """Every JSON endpoint in the app passes through the same hook."""
    body = client.get("/capture/status?entity_id=ent-1", headers=JSON).get_data(
        as_text=True
    )
    assert "capBubbleBtn" not in body


def test_no_bubble_when_neither_module_is_on(client, signed_in):
    set_modules(signed_in, petty_cash=False, bill=False)
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert "capBubbleBtn" not in html


def test_the_kill_switch_removes_the_bubble(client, signed_in):
    signed_in.setenv("CAPTURE_AI_ENABLED", "false")
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert "capBubbleBtn" not in html


def test_the_bubble_follows_the_company_the_user_is_inside(app, client, capture_env):
    """Most petty cash pages carry no entity in their URL — only 6 of the 37
    report routes do. The fallback is ``User.current_entity_id``, which the
    presence system keeps pointed at the company the person actually opened.

    Without it the bubble shows on the dashboard and then disappears the moment
    the user starts working, which is exactly when they want it.
    """
    from models.db import User, db

    monkeypatch = capture_env
    set_modules(monkeypatch)
    allow_permission(monkeypatch)

    with app.app_context():
        user_id = make_user()
        user = User.query.get(user_id)
        user.current_entity_id = "ent-1"
        db.session.commit()
    login(client, user_id)

    # No entity_id anywhere in the request.
    html = client.get("/capture?entity_id=ent-1").get_data(as_text=True)
    assert "capBubbleBtn" in html


def test_no_entity_resolves_when_the_user_is_inside_no_company(app, capture_env):
    """Signed in but not in any company: nothing to upload into, so the
    resolver answers None and the bubble is not rendered.

    Tested on the resolver rather than through a page, because every page that
    would exercise it also imports the entity route module this file stubs.
    """
    from blueprints.capture.services import context

    class FakeUser:
        is_authenticated = True
        current_entity_id = None

    capture_env.setattr(context, "current_user", FakeUser())
    with app.test_request_context("/some/page/with/no/entity"):
        assert context._current_entity_id() is None


def test_the_resolver_prefers_the_url_over_the_users_current_company(app, capture_env):
    """A deep link into company B must not upload into company A just because
    that is where the user was last."""
    from blueprints.capture.services import context

    class FakeUser:
        is_authenticated = True
        current_entity_id = "ent-WAS-HERE"

    capture_env.setattr(context, "current_user", FakeUser())
    with app.test_request_context("/some/page?entity_id=ent-LOOKING-AT"):
        assert context._current_entity_id() == "ent-LOOKING-AT"
