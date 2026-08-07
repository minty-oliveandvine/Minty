"""Phase 2 of the Terms of Use work: the consent record and its service.

The tests that matter most here are the transaction ones. A consent row that
commits separately from the `User` row it belongs to, or one that takes the
sign-up down when someone double-clicks, is a bug you only find in production
on a busy day.
"""

from __future__ import annotations

import uuid

import pytest

from legal import registry

_schema_attached = False


@pytest.fixture
def db_session(app, tmp_path_factory):
    """SQLite stand-in for the `pettycashv2` schema.

    The house pattern elsewhere attaches ``':memory:'`` on a single borrowed
    connection. That is unreliable here: an in-memory attachment belongs to the
    connection that made it, so a second connection from the pool sees a
    *different*, empty `pettycashv2` — and whether a test passes then depends on
    which connection the pool happens to hand out.

    Two changes make it deterministic: attach a real file (so every connection
    sees the same tables), and do it from a ``connect`` event (so every
    connection the pool opens from now on gets it).
    """
    global _schema_attached
    from sqlalchemy import event

    from models.db import db

    with app.app_context():
        engine = db.engine
        if not _schema_attached:
            schema_path = str(
                tmp_path_factory.mktemp("schema") / "pettycashv2.sqlite"
            ).replace("\\", "/")

            @event.listens_for(engine, "connect")
            def _attach_schema(dbapi_connection, _record):  # noqa: ANN001
                try:
                    dbapi_connection.execute(
                        f"ATTACH DATABASE '{schema_path}' AS pettycashv2"
                    )
                except Exception:
                    # Already attached on this connection — harmless.
                    pass

            # Drop connections opened before the listener existed, so nothing
            # in the pool is missing the schema.
            engine.dispose()
            _schema_attached = True

        db.session.expire_on_commit = False
        db.create_all()
        yield db
        db.session.rollback()
        for table in reversed(db.metadata.sorted_tables):
            try:
                db.session.execute(table.delete())
            except Exception:
                pass
        db.session.commit()


@pytest.fixture
def user(db_session):
    from models.db import User

    row = User(
        id=str(uuid.uuid4()),
        username=f"consent-{uuid.uuid4().hex[:8]}@test.com",
        email=f"consent-{uuid.uuid4().hex[:8]}@test.com",
        first_name="Con",
        last_name="Sent",
        password="x",
        approved=True,
    )
    db_session.session.add(row)
    db_session.session.commit()
    return row


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------

def test_record_consent_writes_the_server_side_hash(app, db_session, user):
    """The fingerprint comes from the registry, never from a caller.

    A client that could supply the hash could choose what it claims to have
    agreed to, which would make the record worthless in the one situation it
    exists for.
    """
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        consent = record_consent(user.id, source="gate")
        db_session.session.commit()

        document = registry.get_current(registry.TERMS)
        assert consent.document_hash == document.sha256
        assert consent.terms_version == document.version
        assert consent.source == "gate"


def test_record_consent_is_idempotent(app, db_session, user):
    """Two tabs, a double-click, or a retried request give ONE row."""
    from blueprints.legal.models.terms_consent import TermsConsent
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        first = record_consent(user.id, source="gate")
        second = record_consent(user.id, source="gate")
        db_session.session.commit()

        assert first.id == second.id
        assert TermsConsent.query.filter_by(user_id=user.id).count() == 1


def test_record_consent_does_not_commit(app, db_session, user):
    """The caller owns the transaction.

    At sign-up the User row and the consent row must land together, so this
    function must never commit on its own. If it did, a later failure in the
    sign-up would leave a consent record for an account that was never created.

    Asserted with a spy on Session.commit rather than by rolling back and
    looking for the row — see the xfail below for why the rollback form cannot
    be trusted on SQLite. The `after_commit` *event* is no good here either: it
    also fires when a SAVEPOINT is released, so it cannot tell a real commit
    from `begin_nested()` exiting.
    """
    from blueprints.legal.services.consent import record_consent

    commits = []

    with app.app_context():
        session = db_session.session()  # the real Session behind the proxy
        real_commit = session.commit

        def _spy():
            commits.append(1)
            return real_commit()

        session.commit = _spy
        try:
            record_consent(user.id, source="signup_otp")
            assert commits == [], "record_consent committed; the caller must"
        finally:
            session.commit = real_commit
            session.rollback()


@pytest.mark.xfail(
    reason=(
        "pysqlite does not honour SAVEPOINT rollback: a row written inside "
        "begin_nested() survives session.rollback(). Reproducible with bare "
        "SQLAlchemy and no application code, and documented by SQLAlchemy as a "
        "pysqlite driver limitation. PostgreSQL — what production runs — "
        "behaves correctly, so this test passes there and is kept to prove it."
    ),
    strict=False,
)
def test_rolling_back_the_caller_transaction_discards_the_consent(
    app, db_session, user
):
    """The guarantee itself: no consent row without the transaction that owns it."""
    from blueprints.legal.models.terms_consent import TermsConsent
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        record_consent(user.id, source="signup_otp")
        db_session.session.rollback()

        assert TermsConsent.query.filter_by(user_id=user.id).first() is None


def test_record_consent_rejects_an_unknown_source(app, db_session, user):
    """A typo'd source would silently poison the audit trail."""
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        with pytest.raises(ValueError):
            record_consent(user.id, source="signup_token")


def test_record_consent_refuses_a_version_with_no_document(app, db_session, user):
    """A row naming a version we cannot produce is unverifiable."""
    from blueprints.legal.models.terms_consent import TermsConsent
    from blueprints.legal.services.consent import record_consent

    with app.app_context():
        assert record_consent(user.id, source="gate", version="beta-99") is None
        assert TermsConsent.query.filter_by(user_id=user.id).first() is None


def test_a_duplicate_insert_does_not_poison_the_caller_transaction(
    app, db_session, user, monkeypatch
):
    """The savepoint is the point of this test.

    Two tabs can both pass the "already recorded?" check and race to insert.
    In PostgreSQL the loser's IntegrityError aborts the ENTIRE transaction — at
    sign-up that would take the User row with it, turning a double-click into a
    failed registration. `begin_nested()` confines the rollback to the insert.

    The race is simulated by blinding the existence check, which is exactly
    what a concurrent transaction does.
    """
    from blueprints.legal.models.terms_consent import TermsConsent
    from blueprints.legal.services import consent as consent_module
    from models.db import User

    with app.app_context():
        consent_module.record_consent(user.id, source="gate")
        db_session.session.commit()

        class _Blind:
            """Query stand-in that never finds the existing row."""

            def filter_by(self, **_kwargs):
                return self

            def first(self):
                return None

        monkeypatch.setattr(TermsConsent, "query", _Blind())

        # Must not raise, and must not abort the surrounding transaction.
        consent_module.record_consent(user.id, source="gate")

        monkeypatch.undo()

        # The caller's transaction is still usable — this is what the savepoint
        # buys, and what a bare add() would have destroyed.
        survivor = User(
            id=str(uuid.uuid4()),
            username=f"after-{uuid.uuid4().hex[:8]}@test.com",
            email=f"after-{uuid.uuid4().hex[:8]}@test.com",
            first_name="Still",
            last_name="Works",
            password="x",
            approved=True,
        )
        db_session.session.add(survivor)
        db_session.session.commit()

        assert User.query.filter_by(id=survivor.id).first() is not None
        assert TermsConsent.query.filter_by(user_id=user.id).count() == 1


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------

def test_has_consent_is_false_before_and_true_after(app, db_session, user):
    from blueprints.legal.services.consent import has_consent, record_consent

    with app.app_context():
        assert has_consent(user.id) is False
        record_consent(user.id, source="gate")
        db_session.session.commit()
        assert has_consent(user.id) is True


def test_agreeing_to_one_version_does_not_satisfy_another(app, db_session, user):
    """This is the entire revamp mechanism.

    Moving CURRENT_TERMS_VERSION must move everyone back to "not agreed" — if
    a record for beta-1 satisfied beta-2, rewriting the Terms would ask nobody.
    """
    from blueprints.legal.services.consent import has_consent, record_consent

    with app.app_context():
        record_consent(user.id, source="gate")
        db_session.session.commit()

        assert has_consent(user.id, version=registry.CURRENT_TERMS_VERSION) is True
        assert has_consent(user.id, version="beta-2") is False


def test_has_consent_handles_no_user(app, db_session):
    from blueprints.legal.services.consent import has_consent

    with app.app_context():
        assert has_consent(None) is False
        assert has_consent("") is False


def test_consents_for_user_returns_newest_first(app, db_session, user):
    from blueprints.legal.services.consent import consents_for_user, record_consent

    with app.app_context():
        record_consent(user.id, source="signup_otp")
        db_session.session.commit()

        rows = consents_for_user(user.id)
        assert len(rows) == 1
        assert rows[0].source == "signup_otp"


# --------------------------------------------------------------------------
# The table itself
# --------------------------------------------------------------------------

def test_unique_constraint_is_enforced_by_the_database(app, db_session, user):
    """The service treats a violation as success, so the constraint must
    actually exist — otherwise duplicates accumulate silently."""
    from sqlalchemy.exc import IntegrityError

    from blueprints.legal.models.terms_consent import TermsConsent

    with app.app_context():
        version = registry.CURRENT_TERMS_VERSION
        for _ in range(2):
            db_session.session.add(
                TermsConsent(
                    id=str(uuid.uuid4()),
                    user_id=user.id,
                    terms_version=version,
                    document_hash="a" * 64,
                    source="gate",
                )
            )
        with pytest.raises(IntegrityError):
            db_session.session.commit()
        db_session.session.rollback()


def test_document_hash_is_required(app, db_session, user):
    """A consent row that does not pin the wording is unverifiable."""
    from sqlalchemy.exc import IntegrityError

    from blueprints.legal.models.terms_consent import TermsConsent

    with app.app_context():
        db_session.session.add(
            TermsConsent(
                id=str(uuid.uuid4()),
                user_id=user.id,
                terms_version="beta-1",
                document_hash=None,
                source="gate",
            )
        )
        with pytest.raises(IntegrityError):
            db_session.session.commit()
        db_session.session.rollback()
