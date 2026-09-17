"""Tests for billing email.

The subscription engine used to be silent: every lifecycle event was computed, stored
and acted on, and the customer found out either by opening the settings page or by being
locked out. These cover the three properties that make wiring email into it safe.

1. **It never sends twice.** The jobs that trigger these emails are documented as safe to
   re-run at any cadence, and that is only true of state reconciliation — a send is not
   idempotent. Most of the file is this.
2. **It never raises.** These are called from inside jobs that move money. A dead SMTP
   host must not abort a renewal run halfway through a batch of payers.
3. **It never says the wrong thing.** In particular the trial-ending warning, whose whole
   value is telling a customer whether their trial WILL convert — getting that backwards
   either nags someone who was fine or reassures someone about to lose access.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from werkzeug.security import generate_password_hash

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_session(app):
    from models.db import db

    with app.app_context():

        db.session.expire_on_commit = False
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


def _company(db, label):
    """A real company row for a test label: entity_module_subscription.entity_id is a uuid FK
    to entities since C7, so the labels the tests used to write ("e1") become rows."""
    from models.db import Entity

    eid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"notify-company-{label}"))
    if db.session.get(Entity, eid) is None:
        db.session.add(Entity(id=eid, name=f"Company {label}", status="disconnected"))
        db.session.flush()
    return eid


def _make_payer(db, email="payer@test.com"):
    from models.db import User

    uid = str(uuid.uuid4())
    user = User(
        id=uid,
        email=email,
        username=f"{uid}@u",
        first_name="Sam",
        last_name="Payer",
        password=generate_password_hash("x"),
        system_role=User.SYSTEM_ROLE_DEFAULT,
        approved=True,
    )
    db.session.add(user)
    db.session.commit()
    return uid


class _Mail:
    """Stands in for Flask-Mail. ``fail`` makes ``send`` raise, like a dead SMTP host."""

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, message):
        if self.fail:
            raise RuntimeError("smtp refused")
        self.sent.append(message)


@pytest.fixture
def mail(app):
    """Install a fake mailer and a public base url for the duration of a test."""
    original = app.extensions.get("mail")
    original_url = app.config.get("PUBLIC_URL")
    fake = _Mail()
    app.extensions["mail"] = fake
    app.config["PUBLIC_URL"] = "https://app.minty.test"
    app.config.setdefault("BREVO_EMAIL", "noreply@minty.test")
    yield fake
    app.extensions["mail"] = original
    app.config["PUBLIC_URL"] = original_url


# ---------------------------------------------------------------------------
# Deduplication — the property the whole email log exists for
# ---------------------------------------------------------------------------


def test_the_same_notification_is_only_ever_sent_once(app, db_session, mail):
    """``retry-dunning`` and ``sweep-access`` are safe to run hourly BECAUSE re-running
    them changes nothing. Email is the one effect that breaks that, so it is deduped in
    the database rather than by the runner remembering."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)

        first = notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={}
        )
        second = notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={}
        )

        assert first is True
        assert second is False
        assert len(mail.sent) == 1


def test_a_different_dedupe_key_is_a_different_email(app, db_session, mail):
    """A payer who lapses, recovers, and lapses again months later must hear about the
    second episode. The key is per-episode for exactly this."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)

        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={})
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-2", context={})

        assert len(mail.sent) == 2


def test_a_send_that_failed_is_retried_on_the_next_run(app, db_session, mail):
    """A mail outage must not silently swallow a dunning notice. The claim row is left at
    ``failed``, which the next pass picks up — unlike a successful one, which is never
    touched again."""
    from blueprints.subscription.services import notify
    from blueprints.subscription.models.subscription_email_log import (
        STATUS_FAILED,
        STATUS_SENT,
        SubscriptionEmailLog,
    )

    with app.app_context():
        payer = _make_payer(db_session)

        mail.fail = True
        assert notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={}
        ) is False
        row = SubscriptionEmailLog.query.filter_by(dedupe_key="ep-1").one()
        assert row.status == STATUS_FAILED
        assert "smtp refused" in (row.error or "")

        mail.fail = False
        assert notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={}
        ) is True
        assert len(mail.sent) == 1
        db_session.session.expire_all()
        assert SubscriptionEmailLog.query.filter_by(dedupe_key="ep-1").one().status == (
            STATUS_SENT
        )


def test_one_claim_row_per_notification_not_one_per_attempt(app, db_session, mail):
    """The unique constraint is on (event, dedupe_key). A retried send reuses its row, so
    a fortnight of SMTP trouble leaves one row, not fourteen."""
    from blueprints.subscription.models.subscription_email_log import SubscriptionEmailLog
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        mail.fail = True
        for _ in range(3):
            notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="ep-1", context={})

        assert SubscriptionEmailLog.query.filter_by(dedupe_key="ep-1").count() == 1


# ---------------------------------------------------------------------------
# Never raising — these run inside jobs that move money
# ---------------------------------------------------------------------------


def test_a_dead_mail_server_does_not_raise(app, db_session, mail):
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        mail.fail = True
        assert notify.notify(
            payer, notify.RENEWAL_FAILED, dedupe_key="k", context={"total": 40000}
        ) is False


def test_no_mail_extension_configured_does_not_raise(app, db_session):
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        original = app.extensions.pop("mail", None)
        try:
            assert notify.notify(
                payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={}
            ) is False
        finally:
            if original is not None:
                app.extensions["mail"] = original


def test_a_payer_with_no_email_address_is_skipped_without_claiming(app, db_session, mail):
    """Checked before the claim, so an address added later still gets the email rather
    than deduping against a send that never happened."""
    from blueprints.subscription.models.subscription_email_log import SubscriptionEmailLog
    from blueprints.subscription.services import notify
    from models.db import User

    with app.app_context():
        payer = _make_payer(db_session, email="nobody@test.com")
        User.query.filter_by(id=payer).update({"email": None, "xero_email": None})
        db_session.session.commit()

        assert notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={}
        ) is False
        assert SubscriptionEmailLog.query.filter_by(dedupe_key="k").count() == 0


def test_every_event_renders_from_an_empty_context(app, db_session, mail):
    """Nothing in ``_COPY`` may require a context key to render.

    These are composed inside exception handlers in billing jobs, where the context is
    assembled from whatever the failure path happened to know. A builder that assumes a
    key would turn a missing entity name into a swallowed notification — the customer
    hears nothing, and the only trace is a log line."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        for index, event in enumerate(notify.EVENTS):
            assert notify.notify(
                payer, event, dedupe_key=f"k{index}", context={}
            ) is True, f"{event} did not render from an empty context"

        assert len(mail.sent) == len(notify.EVENTS)
        for message in mail.sent:
            assert message.subject
            assert "None" not in message.subject


def test_an_unknown_event_is_refused_rather_than_rendered(app, db_session, mail):
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        assert notify.notify(payer, "invented_event", dedupe_key="k", context={}) is False
        assert mail.sent == []


def test_a_batch_drains_even_when_one_entry_is_broken(app, db_session, mail):
    """``notify_many`` is called at the end of a billing run. One malformed event must not
    cost the other payers their notification."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        sent = notify.notify_many([
            (payer, "invented_event", "a", {}),
            (payer, notify.PAYMENT_RECOVERED, "b", {}),
        ])
        assert sent == 1
        assert len(mail.sent) == 1


# ---------------------------------------------------------------------------
# Copy — what the customer actually reads
# ---------------------------------------------------------------------------


def test_a_trial_that_needs_action_says_what_to_do_and_by_when(app, db_session, mail,
                                                              monkeypatch):
    """The single most valuable email in the system: it arrives while the customer can
    still prevent the lapse.

    The clock is frozen rather than left to run. The heading and subject are a COUNTDOWN
    now, so a fixed ``trial_end`` would quietly start rendering "ends today" the moment
    the date passed, and the test would fail for a reason that has nothing to do with the
    behaviour it is guarding.
    """
    from blueprints.subscription.services import notify

    frozen = datetime(2026, 9, 1, tzinfo=UTC)
    monkeypatch.setattr(notify.clock, "now", lambda: frozen)

    with app.app_context():
        payer = _make_payer(db_session)
        notify.notify(payer, notify.TRIAL_ENDING, dedupe_key="k", context={
            "entity_id": _company(db_session, "e1"),
            "entity_name": "Olive Ltd",
            "codes": ["PETTY_CASH"],
            "trial_end": frozen + timedelta(days=7),
            "amount": 28000,
            "currency": "HKD",
            "needs_card": True,
        })

        message = mail.sent[0]
        # The subject echoes the heading rather than naming the company. That makes the
        # company name in the BODY load-bearing, not decorative: a payer with several
        # companies cannot act on "your trial" without it.
        assert message.subject == "Your Minty trial ends in 7 days"
        assert "Trial Ending in 7 days" in message.html
        assert "Olive Ltd" in message.html
        assert "choose a subscription plan" in message.html
        assert "8 Sep 2026" in message.html
        assert "Go to Manage Subscription" in message.html
        assert f"https://app.minty.test/entity/settings/module/{_company(db_session, 'e1')}" in message.html


def test_the_trial_countdown_never_reads_as_a_negative(app, db_session, mail,
                                                       monkeypatch):
    """The warning job can run late. "Trial Ending in -1 days" is the kind of thing
    customers screenshot, so the countdown degrades to a phrase that stays true."""
    from blueprints.subscription.services import notify

    frozen = datetime(2026, 9, 1, tzinfo=UTC)
    monkeypatch.setattr(notify.clock, "now", lambda: frozen)

    with app.app_context():
        payer = _make_payer(db_session)
        for key, offset, expected in (("past", -3, "today"),
                                      ("same", 0, "today"),
                                      ("one", 1, "in 1 day")):
            notify.notify(payer, notify.TRIAL_ENDING, dedupe_key=key, context={
                "entity_id": _company(db_session, "e1"), "entity_name": "Olive Ltd", "codes": ["PAYMENT_REQUEST"],
                "trial_end": frozen + timedelta(days=offset), "needs_card": True,
            })
            assert mail.sent[-1].subject == f"Your Minty trial ends {expected}"


def test_the_two_blocked_trial_states_now_read_identically(app, db_session, mail):
    """``needs_card`` and ``needs_consent`` used to produce different wording. They no
    longer do — one "action needed" body covers both, and the in-app banner is what still
    distinguishes "add a payment method" from "confirm billing for this company".

    Asserted rather than assumed, because the merge is easy to half-undo: re-adding a
    branch here would resurrect the bug where a consent-blocked payer was told to add a
    card they could already see on their own billing page.
    """
    from blueprints.subscription.services import notify

    base = {
        "entity_id": _company(db_session, "e1"),
        "entity_name": "Olive Ltd",
        "codes": ["PETTY_CASH"],
        "trial_end": datetime(2026, 9, 1, tzinfo=UTC),
    }

    with app.app_context():
        payer = _make_payer(db_session)
        notify.notify(payer, notify.TRIAL_ENDING, dedupe_key="no-card",
                      context={**base, "needs_card": True, "needs_consent": False})
        notify.notify(payer, notify.TRIAL_ENDING, dedupe_key="consent",
                      context={**base, "needs_card": False, "needs_consent": True})

        no_card, consent = mail.sent[0], mail.sent[1]
        assert no_card.subject == consent.subject
        assert no_card.html == consent.html


def test_the_trial_email_states_no_price(app, db_session, mail):
    """Deliberate, and worth pinning so nobody helpfully adds one back.

    A converting trial on an entity that already pays for a sibling module is charged the
    marginal step up to the bundle, NOT the full line price. The old email printed the
    line price under "Monthly after trial" precisely because labelling it "First charge"
    would have stated a number the customer never sees on their card. The redesign drops
    the figure entirely, which is safe — but re-adding it without that context is how it
    comes back labelled wrongly.
    """
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        notify.notify(payer, notify.TRIAL_ENDING, dedupe_key="k", context={
            "entity_id": _company(db_session, "e1"), "entity_name": "Olive Ltd", "codes": ["PAYMENT_REQUEST"],
            "trial_end": datetime(2026, 9, 1, tzinfo=UTC),
            "amount": 40000, "currency": "HKD", "needs_card": True,
        })

        html = mail.sent[0].html
        assert "400.00" not in html
        assert "First charge" not in html
        assert "Monthly after trial" not in html


def test_a_receipt_states_the_amount_and_the_period(app, db_session, mail):
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        notify.notify(payer, notify.RENEWAL_PAID, dedupe_key="k", context={
            "total": 40000,
            "currency": "HKD",
            "period_start": datetime(2026, 8, 1, tzinfo=UTC),
            "period_end": datetime(2026, 9, 1, tzinfo=UTC),
            "lines": ["Olive Ltd — Super Minty"],
        })

        message = mail.sent[0]
        assert "HKD 400.00" in message.subject
        assert "HKD 400.00" in message.html
        assert "Olive Ltd — Super Minty" in message.html
        assert "1 Aug 2026" in message.html and "1 Sep 2026" in message.html


def test_links_are_dropped_rather_than_pointed_at_localhost(app, db_session, mail):
    """Sent from CLI jobs, where ``url_for(_external=True)`` silently yields
    http://localhost — a link that looks real and goes nowhere."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        app.config["PUBLIC_URL"] = None
        notify.notify(payer, notify.TRIAL_EXPIRED, dedupe_key="k", context={
            "entity_id": _company(db_session, "e1"), "entity_name": "Olive Ltd", "codes": ["PAYMENT_REQUEST"],
        })

        html = mail.sent[0].html
        assert "localhost" not in html
        assert "Go to Manage Subscription" not in html
        # The words still carry the message without the button.
        assert "switched off" in html


def test_the_images_travel_with_the_message_not_over_http(app, db_session, mail):
    """A remote <img> is a broken grey box whenever the client blocks images — which
    Gmail and Outlook both do by default — or whenever PUBLIC_URL isn't publicly
    reachable. The first live send went out with a logo pointing at localhost:5001.

    Attached, they render offline, behind image blocking, and whatever PUBLIC_URL says.
    Both parts get the same treatment: the masthead logo and the event's illustration.
    """
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        notify._image_cache.clear()
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={})

        message = mail.sent[0]
        assert f'src="cid:{notify.LOGO_CID}"' in message.html
        assert f'src="cid:{notify.ILLUSTRATION_CID}"' in message.html
        # Nothing is fetched over the wire to render either image.
        assert "/static/img/" not in message.html

        assert len(message.attachments) == 2
        for part, cid in zip(message.attachments,
                             (notify.LOGO_CID, notify.ILLUSTRATION_CID)):
            assert part.content_type == "image/png"
            assert part.disposition == "inline"
            assert part.data[:8] == b"\x89PNG\r\n\x1a\n"
            # Angle brackets in the header, none in the src — mismatching the pair is the
            # usual reason an inline image silently fails to resolve.
            assert part.headers["Content-ID"] == f"<{cid}>"


def test_a_missing_image_drops_it_rather_than_dangling(app, db_session, mail,
                                                       monkeypatch):
    """No bytes means no <img> — never a reference to a part that isn't attached, which
    renders as the same broken box the attachment exists to avoid.

    This is also what lets an event ship before its illustration has been drawn.
    """
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        monkeypatch.setattr(notify, "image_bytes", lambda *parts: None)
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={})

        message = mail.sent[0]
        assert "cid:" not in message.html
        assert "<img" not in message.html
        assert message.attachments == []
        # The email still says everything it needs to.
        assert "successfully received your payment" in message.html


def test_an_event_with_no_illustration_still_sends(app, db_session, mail, monkeypatch):
    """The logo is present, the event's art is not. Half-dressed has to work, because
    three events are shipping ahead of their illustrations."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        real = notify.image_bytes
        # Matched on the exact path, not on a substring: the logo now lives under
        # ``img/email/`` too, so anything looser suppresses both and tests nothing.
        art_path = notify.illustration_path(notify.PAYMENT_RECOVERED)
        monkeypatch.setattr(
            notify, "image_bytes",
            lambda *parts: None if parts == art_path else real(*parts),
        )
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={})

        message = mail.sent[0]
        assert f"cid:{notify.LOGO_CID}" in message.html
        assert notify.ILLUSTRATION_CID not in message.html
        assert len(message.attachments) == 1


def test_billing_mail_comes_from_its_own_address(app, db_session, mail):
    """Billing does not share a From with invitations and sign-in codes.

    An invitation comes from a colleague; a dunning notice comes from the company about to
    switch your access off. Recipients filter and search on the sender, so a customer
    hunting for "that email about my payment" should not have to know it arrived from an
    address with `invite` in it.
    """
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        app.config["SUBSCRIPTION_EMAIL"] = "subscription@minty.test"
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={})

        assert mail.sent[0].sender == "subscription@minty.test"


def test_billing_mail_falls_back_to_the_shared_address(app, db_session, mail):
    """An environment that has not yet verified the dedicated sender with the relay keeps
    sending. An unverified From is rejected or spam-filed and ``notify`` swallows SMTP
    errors by design, so failing over to the working address beats failing invisibly."""
    from blueprints.subscription.services import notify

    with app.app_context():
        payer = _make_payer(db_session)
        app.config["SUBSCRIPTION_EMAIL"] = None
        notify.notify(payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={})

        assert mail.sent[0].sender == app.config["BREVO_EMAIL"]


def test_an_inline_logo_makes_the_message_related_not_mixed(app):
    """``multipart/mixed`` says "a body, and separately some files" — the wrong statement
    about an image the body references by cid. Under it several Outlook builds render the
    logo inline AND list it as a paperclip, so a billing notice looks like it encloses a
    file. ``multipart/related`` (RFC 2387) says the parts are one document."""
    from blueprints.subscription.services import notify

    with app.app_context():
        message = notify.InlineImageMessage(
            subject="s", sender="a@b.c", recipients=["x@y.z"], html="<p>hi</p>"
        )
        message.attach("logo.png", "image/png", b"\x89PNG\r\n\x1a\n", "inline",
                       headers={"Content-ID": f"<{notify.LOGO_CID}>"})
        raw = message.as_bytes().decode("utf-8", "replace")

        assert 'Content-Type: multipart/related; type="multipart/alternative"' in raw
        assert "multipart/mixed" not in raw


def test_a_real_enclosure_stays_mixed(app):
    """The flip is only correct for parts the body references. A genuine enclosure — a
    PDF invoice, say — belongs in ``mixed``, and must not be dragged along."""
    from blueprints.subscription.services import notify

    with app.app_context():
        message = notify.InlineImageMessage(
            subject="s", sender="a@b.c", recipients=["x@y.z"], html="<p>hi</p>"
        )
        message.attach("invoice.pdf", "application/pdf", b"%PDF-1.4", "attachment")
        raw = message.as_bytes().decode("utf-8", "replace")

        assert "multipart/mixed" in raw
        assert "multipart/related" not in raw


def test_an_unreachable_public_url_is_reported_once(app, db_session, mail, monkeypatch):
    """A developer's PUBLIC_URL reaching production mail is otherwise silent: every
    message looks perfect and every button lands on a host only the sender can resolve.

    Once per process, not per send — a nightly run mailing forty payers must not print
    forty copies of one configuration problem."""
    from blueprints.subscription.services import notify

    warnings = []
    monkeypatch.setattr(notify, "_warned_unreachable", False)
    monkeypatch.setattr(
        notify.logger, "warning", lambda msg, *a, **k: warnings.append(msg)
    )

    with app.app_context():
        app.config["PUBLIC_URL"] = "https://localhost:5001"
        payer = _make_payer(db_session)
        for index in range(3):
            notify.notify(
                payer, notify.PAYMENT_RECOVERED, dedupe_key=f"k{index}", context={}
            )

        assert len(mail.sent) == 3
        unreachable = [w for w in warnings if "no recipient can reach" in w]
        assert len(unreachable) == 1, warnings


def test_a_xero_only_user_is_still_reachable(app, db_session, mail):
    """A user who signed up through Xero may have no personal ``email`` at all, and is
    just as capable of owing money as anyone else."""
    from blueprints.subscription.services import notify
    from models.db import User

    with app.app_context():
        payer = _make_payer(db_session)
        User.query.filter_by(id=payer).update(
            {"email": None, "xero_email": "sam@xero.test"}
        )
        db_session.session.commit()

        assert notify.notify(
            payer, notify.PAYMENT_RECOVERED, dedupe_key="k", context={}
        ) is True
        assert mail.sent[0].recipients == ["sam@xero.test"]


# ---------------------------------------------------------------------------
# Call sites — that the billing jobs hand over the right events
# ---------------------------------------------------------------------------


def test_a_retry_that_then_succeeded_does_not_send_a_failure_notice():
    """A recovered payer lands in BOTH ``retried`` and ``recovered``. Mailing from inside
    the loop would send "failed again" moments before "you're all settled"."""
    from blueprints.subscription.services import dunning

    captured = []
    original = dunning.__dict__.get("_notify_dunning")
    assert original is not None

    import blueprints.subscription.services.notify as notify_mod

    real_many = notify_mod.notify_many
    notify_mod.notify_many = lambda events: captured.extend(events) or len(events)
    try:
        dunning._notify_dunning(
            retried=[{"user_id": "u1", "attempts": 1, "_episode": "u1:E"}],
            recovered=[{"user_id": "u1", "attempts": 1, "_episode": "u1:E"}],
            given_up=[],
        )
    finally:
        notify_mod.notify_many = real_many

    events = {event for _, event, _, _ in captured}
    assert notify_mod.PAYMENT_RECOVERED in events
    assert notify_mod.DUNNING_RETRY_FAILED not in events


def test_dunning_scaffolding_does_not_leak_into_the_reported_result():
    """``_episode`` exists to build a dedupe key. ``collect_due``'s documented return
    shape is unchanged by notification being bolted on."""
    from blueprints.subscription.services import dunning
    import blueprints.subscription.services.notify as notify_mod

    entries = [{"user_id": "u1", "attempts": 0, "_episode": "u1:E"}]
    real_many = notify_mod.notify_many
    notify_mod.notify_many = lambda events: 0
    try:
        dunning._notify_dunning(retried=[], recovered=entries, given_up=[])
    finally:
        notify_mod.notify_many = real_many

    assert entries[0] == {"user_id": "u1", "attempts": 0}


def test_the_retired_events_stay_retired(app):
    """Five emails were deliberately switched off. Each removal has a consequence that is
    invisible from the call site, so re-adding one should be a decision, not a reflex:

      trial_converted            a converting trial is silent; the first charge is
                                 receipted by ``renewal_paid`` in the same daily pass
      trial_ending/will-convert  a cleanly converting trial gets no advance warning at all
      account_closed             superseded, then the thing meant to supersede it went too
      subscriber_transfer_failed the accepting user sees the decline in the browser
      access_revoked             NOTHING now announces a revocation -- a dunning give-up
                                 ends in silence, and a cancellation is never confirmed

    The strings themselves must never be reused for a different meaning either: a dedupe
    row written years ago would suppress the new email for anyone who received the old.
    """
    from blueprints.subscription.services import notify

    retired = ("trial_converted", "account_closed", "subscriber_transfer_failed",
               "access_revoked")
    assert [e for e in retired if e in notify._COPY] == []
    assert [e for e in retired if e in notify.EVENTS] == []
    # The live set, stated once so a silent addition shows up here.
    assert len(notify._COPY) == 10


def test_renewal_receipts_are_deduped_on_the_billing_period(app, db_session, mail):
    """The same key that stops the payer being CHARGED twice for a period stops them
    being MAILED twice about it, so a re-run is consistent in both."""
    from blueprints.subscription.services import renewals

    with app.app_context():
        payer = _make_payer(db_session)
        entry = {
            "user_id": payer,
            "period_start": datetime(2026, 8, 1, tzinfo=UTC),
            "period_end": datetime(2026, 9, 1, tzinfo=UTC),
            "total": 40000,
            "currency": "HKD",
            "lines": ["Olive Ltd — Super Minty"],
        }
        renewals._notify_renewals(issued=[entry], failed=[])
        renewals._notify_renewals(issued=[entry], failed=[])

        assert len(mail.sent) == 1


def test_trials_ending_soon_are_found_in_a_one_day_window(app, db_session):
    """A daily run tiles the calendar exactly once per trial. A cumulative "within N
    days" filter would re-match the same trial every day and lean entirely on the email
    log to stay quiet."""
    from blueprints.subscription.services import store
    from models.db import EntityModuleSubscription

    with app.app_context():
        now = datetime(2026, 8, 4, 12, tzinfo=UTC)
        payer = _make_payer(db_session)
        for days, code in ((3, "PAYMENT_REQUEST"), (5, "PETTY_CASH")):
            db_session.session.add(EntityModuleSubscription(
                id=str(uuid.uuid4()),
                entity_id=_company(db_session, f"e{days}"),
                function_code=code,
                payer_user_id=payer,
                phase="trial",
                trial_end=now + timedelta(days=days),
            ))
        db_session.session.commit()

        start = now + timedelta(days=3)
        found = store.trials_ending_between(start, start + timedelta(days=1))

        assert [row.function_code for row in found] == ["PAYMENT_REQUEST"]


def test_the_warning_window_is_day_aligned_not_run_time_aligned(
    app, db_session, mail, monkeypatch
):
    """A window of ``[now + 3d, now + 4d)`` only tiles if the job runs at EXACTLY
    24-hour intervals. Cron does not: a run at 08:10 followed by one at 08:15 leaves a
    five-minute hole, and a trial ending inside it is never warned about at all.

    Found against real data. A trial ending 13:00 HKT — 05:00 UTC — fell before a window
    that opened at 08:10 UTC and was silently skipped, which is the worst failure this
    email has, because it is the one notification that could have prevented the lapse.
    """
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription

    with app.app_context():
        payer = _make_payer(db_session)
        # Ends EARLIER in the day than the job runs — the case that used to be missed.
        trial_end = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e1"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="trial",
            trial_end=trial_end,
        ))
        db_session.session.commit()

        # Job runs at 08:10 UTC, three days out. Run-time-aligned this finds nothing.
        # ``monkeypatch.setattr`` rather than a plain assignment: ``clock.now`` is a
        # module-level function, so assigning to it and then ``del``-ing removes the real
        # one from the module namespace for every test that follows.
        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 17, 8, 10, tzinfo=UTC)
        )
        result = checkout.notify_trials_ending(days_before=3)

        assert [w["entity_id"] for w in result["warned"]] == [_company(db_session, "e1")]


def test_a_trial_that_will_convert_cleanly_is_not_warned_at_all(app, db_session,
                                                                monkeypatch):
    """The filter moved from the COPY to the SEND.

    This email used to go to every trial in the window and pick one of three wordings,
    one of which amounted to "your trial ends soon, do nothing". That trains people to
    skim past the one trial email that does need acting on, so a trial with a card saved
    and this company authorised is now not mailed at all — its first word about the
    charge is the receipt.
    """
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription

    with app.app_context():
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e1"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="trial",
            trial_end=datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        ))
        db_session.session.commit()

        monkeypatch.setattr(checkout, "_trial_has_card", lambda uid: True)
        monkeypatch.setattr(checkout.store, "has_billing_consent",
                            lambda eid, uid: True)
        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 17, 8, 10, tzinfo=UTC)
        )

        result = checkout.notify_trials_ending(days_before=7)

        assert result["warned"] == []
        assert [s["reason"] for s in result["skipped"]] == ["will_convert"]


def test_a_trial_blocked_only_on_consent_is_still_warned(app, db_session, monkeypatch):
    """A card IS saved; this company just was not authorised for it. That trial lapses
    exactly as hard as one with no card at all, so it must still be warned — the send
    gates on ``needs_card OR needs_consent``, not on the card alone."""
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription

    with app.app_context():
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e1"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="trial",
            trial_end=datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        ))
        db_session.session.commit()

        monkeypatch.setattr(checkout, "_trial_has_card", lambda uid: True)
        monkeypatch.setattr(checkout.store, "has_billing_consent",
                            lambda eid, uid: False)
        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 17, 8, 10, tzinfo=UTC)
        )

        result = checkout.notify_trials_ending(days_before=7)

        assert [w["entity_id"] for w in result["warned"]] == [_company(db_session, "e1")]


def test_a_cancelled_trial_is_not_warned_about(app, db_session):
    """Cancelling a trial is a deliberate act. Telling the customer the thing they asked
    to end is about to end is noise, not a service — and unlike ``due_trials``, this
    query has no row to close out, so there is no reason to include them."""
    from blueprints.subscription.services import store
    from models.db import EntityModuleSubscription

    with app.app_context():
        now = datetime(2026, 8, 4, 12, tzinfo=UTC)
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e1"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="scheduled_cancel",
            trial_end=now + timedelta(days=3),
        ))
        db_session.session.commit()

        start = now + timedelta(days=3)
        assert store.trials_ending_between(start, start + timedelta(days=1)) == []


def test_a_trial_whose_tile_was_MISSED_is_still_warned(app, db_session, monkeypatch):
    """A day the job does not run must not cost a customer their only actionable notice.

    The window used to be the single calendar day exactly ``days_before`` out. Run daily
    those tile perfectly — but there is no watermark and no backlog, so a day the job is
    down is a hole nothing ever revisits, and the trials whose tile fell in it are never
    warned at all. Their first news is the module going dark.

    Here the job misses 17 Aug and runs on the 18th. Under the old window the 18th looks
    for trials ending 21 Aug and never sees this one; under the current window it catches
    it with two days' notice instead of three.
    """
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription

    with app.app_context():
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e_missed"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="trial",
            trial_end=datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        ))
        db_session.session.commit()

        # 17 Aug never ran. This is the 18th.
        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 18, 8, 10, tzinfo=UTC)
        )
        result = checkout.notify_trials_ending(days_before=3)

        assert [w["entity_id"] for w in result["warned"]] == [_company(db_session, "e_missed")]


def test_a_trial_ending_TODAY_is_left_to_the_trial_end_job(app, db_session, monkeypatch):
    """The window starts tomorrow.

    ``notify-trial-ending`` runs before ``close-trials`` on the same schedule, so warning
    about a trial ending today would mail "your trial ends soon" minutes before "your
    trial has ended" — two contradictory notices about one trial on one day.
    """
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription

    with app.app_context():
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()),
            entity_id=_company(db_session, "e_today"),
            function_code="PAYMENT_REQUEST",
            payer_user_id=payer,
            phase="trial",
            trial_end=datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        ))
        db_session.session.commit()

        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 20, 1, 0, tzinfo=UTC)
        )
        result = checkout.notify_trials_ending(days_before=3)

        assert result["warned"] == []


def test_a_trial_warning_reaches_a_payer_the_entity_was_handed_to(
    app, db_session, mail, monkeypatch
):
    """The whole reason "change subscriber" used to refuse an entity on trial.

    The uniqueness constraint is (event, dedupe_key) with ``user_id`` deliberately outside
    it, so the KEY is the only thing that can tell two recipients apart. A handover changes
    neither the entity, nor the codes, nor ``trial_end`` — so a key built from those three
    regenerates identically, ``_claim`` finds the row already sent to the outgoing payer,
    and the person who is actually about to be charged is told nothing.

    That is not a missed reminder. This email branches on ``needs_card`` into "action
    needed" versus "nothing you need to do", so silence is indistinguishable from
    reassurance right up until the money leaves.
    """
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription, SubscriptionEmailLog

    with app.app_context():
        outgoing = _make_payer(db_session, email="outgoing@test.com")
        incoming = _make_payer(db_session, email="incoming@test.com")

        trial_end = datetime(2026, 8, 20, 5, 0, tzinfo=UTC)
        row = EntityModuleSubscription(
            id=str(uuid.uuid4()), entity_id=_company(db_session, "e1"), function_code="PAYMENT_REQUEST",
            payer_user_id=outgoing, phase="trial", trial_end=trial_end,
        )
        db_session.session.add(row)
        db_session.session.commit()

        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 17, 8, 10, tzinfo=UTC)
        )

        # Warned once, to the payer at the time.
        assert [w["entity_id"] for w in
                checkout.notify_trials_ending(days_before=3)["warned"]] == [_company(db_session, "e1")]

        # The handover: only the payer moves. Entity, codes and trial_end are untouched,
        # which is exactly why an entity-scoped key would swallow the second warning.
        row.payer_user_id = incoming
        db_session.session.commit()

        assert [w["entity_id"] for w in
                checkout.notify_trials_ending(days_before=3)["warned"]] == [_company(db_session, "e1")]

        sent = SubscriptionEmailLog.query.filter_by(event="trial_ending").all()
        assert len(sent) == 2, "each payer gets their own warning"
        assert {log.user_id for log in sent} == {outgoing, incoming}
        assert len({log.dedupe_key for log in sent}) == 2, "the keys must differ"


def test_the_same_payer_is_still_only_warned_once(app, db_session, mail, monkeypatch):
    """Payer-scoping the key must not become a licence to re-send. The warning window
    re-matches the same trial on every day it spans, and the log is the only thing
    keeping that quiet."""
    from blueprints.subscription.services import checkout
    from models.db import EntityModuleSubscription, SubscriptionEmailLog

    with app.app_context():
        payer = _make_payer(db_session)
        db_session.session.add(EntityModuleSubscription(
            id=str(uuid.uuid4()), entity_id=_company(db_session, "e1"), function_code="PAYMENT_REQUEST",
            payer_user_id=payer, phase="trial",
            trial_end=datetime(2026, 8, 20, 5, 0, tzinfo=UTC),
        ))
        db_session.session.commit()

        monkeypatch.setattr(
            checkout.clock, "now", lambda: datetime(2026, 8, 17, 8, 10, tzinfo=UTC)
        )
        checkout.notify_trials_ending(days_before=3)
        checkout.notify_trials_ending(days_before=3)

        assert SubscriptionEmailLog.query.filter_by(event="trial_ending").count() == 1
