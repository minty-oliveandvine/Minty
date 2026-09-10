"""One row per agreement to a version of the Terms.

APPEND-ONLY. Rows are inserted and then never updated or deleted by the
application. That is what makes the table evidence: a record that can be
changed after the fact proves nothing about what happened at the time.

WHY NOT A COLUMN ON `user`
--------------------------
A `terms_version` column on `user` would work until the first rewrite, then
throw the history away — you would know only the latest answer, never the
trail. Speed is not a reason to prefer it either: the check result is cached in
the login session, so this table is read about once per login.

WHAT PROVES WHAT
----------------
`terms_version` names the document. `document_hash` pins its exact wording (see
legal/registry.py). Together with `accepted_at` and `user_id` they answer "who
agreed to precisely what, and when" — which is the whole question. `source`,
`ip_address` and `user_agent` are supporting detail, not the proof.
"""

import uuid

from sqlalchemy.dialects.postgresql import UUID

from models.db import db

# How the agreement was given. Kept as a plain string column rather than a DB
# enum so adding a future sign-up route is a code change, not a migration.
SOURCE_SIGNUP_OTP = "signup_otp"      # self-serve sign-up, tick box
SOURCE_SIGNUP_INVITE = "signup_invite"  # invited user, tick box
SOURCE_GATE = "gate"                   # the post-login blocking screen

# NOTE: an earlier draft of the design listed a fourth source, `signup_token`,
# for the "choose a username" flow behind POST /auth/email/complete. That route
# has no client and is unreachable — `email_verify_code` never returns the
# `choose_username` result to the browser, so no signup_token is ever minted for
# a real user. It is deliberately absent here; adding a constant for a path that
# cannot run would invite someone to wire consent capture into dead code.
CONSENT_SOURCES = (SOURCE_SIGNUP_OTP, SOURCE_SIGNUP_INVITE, SOURCE_GATE)


class TermsConsent(db.Model):
    __tablename__ = "terms_consent"
    __table_args__ = (
        # One record per person per version. This is what makes recording a
        # consent idempotent: a double-click, two open tabs, or a retried
        # request all collapse to the same single row instead of littering the
        # evidence trail with duplicates.
        db.UniqueConstraint(
            "user_id", "terms_version", name="uq_terms_consent_user_version"
        ),
        db.Index("ix_terms_consent_user", "user_id"),
        {"schema": "pettycashv2"},
    )

    id = db.Column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(
        db.String(36),
        # Section 13 of the Terms allows permanent deletion of a user. Keeping
        # consent records about a deleted person is data we would have no
        # reason to hold, so they go with them.
        db.ForeignKey("pettycashv2.user.id", ondelete="CASCADE"),
        nullable=False,
    )
    terms_version = db.Column(db.String(32), nullable=False)
    # SHA-256 of the exact wording shown, as computed by legal.registry.
    # Always resolved server-side — a hash supplied by a client would let the
    # client choose what it claims to have agreed to.
    document_hash = db.Column(db.String(64), nullable=False)
    # Timezone-aware on purpose. A naive timestamp is ambiguous the moment
    # anyone asks "when, exactly?" — which is the only question this column
    # exists to answer.
    accepted_at = db.Column(
        db.TIMESTAMP(timezone=True), nullable=False, server_default=db.func.now()
    )
    source = db.Column(db.String(32), nullable=False)
    # 45 chars fits an IPv6 address in its longest textual form.
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)

    user = db.relationship("User", backref="terms_consents", lazy=True)

    def __repr__(self):
        return (
            f"<TermsConsent {self.user_id} {self.terms_version} "
            f"{self.source} {self.accepted_at}>"
        )
