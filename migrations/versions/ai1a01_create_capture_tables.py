"""CAPTURE 1 — create the three AI Capture Hub tables (Stage 2)

Revision ID: ai1a01_capture_tables
Revises: z1a01_drop_payer_cycle
Create Date: 2026-09-07

=============================================================================
WHAT THIS IS

Three new tables. Nothing existing is touched — no column added to an existing
table, no constraint changed, no data moved, no row rewritten.

    pettycashv2.capture_upload      one row per file a user dropped
    pettycashv2.capture_draft       one row per document found inside a file
    pettycashv2.capture_ai_audit    one row per AI call, numbers only

The shape mirrors how the feature actually works: a user uploads ONE file, the
model finds N documents inside it, and each of those becomes a draft the user
reviews on its own. Five receipts in one PDF are five capture_draft rows and
one capture_upload row.

-----------------------------------------------------------------------------
SAFE TO RUN ON LIVE AT ANY TIME

This is purely additive, so the deploy-order rules that govern the report
consolidation do NOT apply:

  * Old code ignores tables it has never heard of. Running this ahead of the
    application code is harmless.
  * Nothing reads these tables until the capture blueprint ships, and even then
    nothing runs until CAPTURE_AI_ENABLED is turned on. The feature ships dark.
  * CREATE TABLE takes no lock on anything that already exists, so no live
    traffic is blocked and no large table is rewritten.

Schema first, code after — the ordinary direction for an addition.

-----------------------------------------------------------------------------
NOTE ON down_revision

Chains onto ``z1a01_drop_payer_cycle``, which is what the database is stamped
at and what ``flask db heads`` reported as the single head before this
revision existed. After this one, ``ai1a01_capture_tables`` is the only head.

Several files in versions/ name a ``down_revision`` that looks like it starts a
branch, but alembic resolves them into one line — do not "fix" that on the
strength of reading the files. Ask alembic: ``flask db heads``.

-----------------------------------------------------------------------------
WHY THE FOREIGN KEYS ARE SHAPED THIS WAY

capture_draft.upload_id CASCADEs. A draft has no meaning without the file it
came from — you cannot review a document you can no longer look at — so when
the retention sweeper removes an upload, its drafts go with it.

capture_ai_audit.upload_id CASCADEs for the same reason. The cost numbers for a
file we no longer hold are not worth keeping a dangling row for. If we later
want long-lived cost history, that is an aggregate table, not this one.

capture_ai_audit.draft_id is deliberately NOT a foreign key. Pass 1 rows have no
draft (the split call belongs to the upload, because it is the call that decides
how many drafts there will be), and a nullable FK that is null half the time
buys nothing that the CASCADE on upload_id does not already give us.

capture_draft.entity_id is denormalised from the upload, and that is on purpose.
Every authorisation check in the feature reads it. Resolving it through
capture_upload would put a join on the hot path of every single request, to
avoid storing 36 bytes.

-----------------------------------------------------------------------------
WHY THE INDEXES

  ix_capture_upload_entity_status   the bubble polls GET /capture/status every
                                    two seconds for every user with it open.
                                    That query is (entity_id, status) and it
                                    must not be a sequential scan.
  ix_capture_upload_dedupe          (entity_id, content_sha256). The duplicate
                                    check runs on EVERY upload, before the file
                                    is stored and before any model call.
  ix_capture_upload_created         the retention sweeper's only filter.
  ix_capture_draft_entity_status    the queue page and the badge count.
  ix_capture_draft_upload           "show me the 5 drafts from this PDF", and
                                    the CASCADE delete.
  ix_capture_ai_audit_entity_created  the cost dashboard: spend per entity over
                                    a date range.

-----------------------------------------------------------------------------
NO BACKFILL

Nothing existed before this feature, so there is nothing to backfill and no
later migration should invent any. The tables start empty and stay empty until
someone turns CAPTURE_AI_ENABLED on.

-----------------------------------------------------------------------------
FULLY REVERSIBLE

downgrade() drops all three tables. While the feature is dark that destroys
nothing. Once real drafts exist it destroys work users have done but not yet
confirmed — take a backup first at that point. Drafts that were already posted
are safe either way: those became shop_expense rows or Module 2 PaymentRequests
and do not live here.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai1a01_capture_tables"
down_revision = "z1a01_drop_payer_cycle"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

UPLOAD = "capture_upload"
DRAFT = "capture_draft"
AUDIT = "capture_ai_audit"


def _has_table(bind, name: str) -> bool:
    """Whether the table already exists.

    In OFFLINE mode (``flask db upgrade --sql``, the dry run you should do
    before touching a live database) there is no connection to inspect and
    ``sa.inspect`` raises. Nothing can exist to collide with in a SQL script, so
    answer "not present" and let the CREATE statements be emitted — which is
    exactly what a dry run is for.
    """
    if op.get_context().as_sql:
        return False
    return sa.inspect(bind).has_table(name, schema=SCHEMA)


def upgrade():
    bind = op.get_bind()

    # Idempotent. The .sql twin gets run by hand on environments alembic does
    # not stamp, and this revision must not then fail on them.
    if _has_table(bind, UPLOAD):
        print(f"{SCHEMA}.{UPLOAD} already exists — nothing to do.")
        return

    op.create_table(
        UPLOAD,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("uploaded_by", sa.String(36), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=True),
        # The SNIFFED type, from magic bytes. The declared extension is not
        # evidence and is never stored.
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column(
            "status", sa.String(32), nullable=False, server_default="queued"
        ),
        sa.Column("reject_reason", sa.String(64), nullable=True),
        sa.Column("document_count", sa.Integer, nullable=True),
        sa.Column(
            "bypass_classification",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processing_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            [f"{SCHEMA}.entities.id"],
            name="fk_capture_upload_entity",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            [f"{SCHEMA}.user.id"],
            name="fk_capture_upload_user",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_upload_entity_status",
        UPLOAD,
        ["entity_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_upload_dedupe",
        UPLOAD,
        ["entity_id", "content_sha256"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_upload_created", UPLOAD, ["created_at"], schema=SCHEMA
    )

    op.create_table(
        DRAFT,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("page_start", sa.Integer, nullable=False),
        sa.Column("page_end", sa.Integer, nullable=False),
        sa.Column("locator", sa.String(200), nullable=True),
        sa.Column("doc_type", sa.String(32), nullable=False),
        sa.Column("doc_type_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("destination", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ready"),
        sa.Column("suggested", postgresql.JSONB, nullable=True),
        sa.Column("confirmed", postgresql.JSONB, nullable=True),
        sa.Column("document_date", sa.Date, nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("supplier_name", sa.String(150), nullable=True),
        sa.Column("page_s3_key", sa.String(512), nullable=True),
        sa.Column("target_ref", sa.String(128), nullable=True),
        sa.Column(
            "send_attempts", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("confirmed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            [f"{SCHEMA}.{UPLOAD}.id"],
            name="fk_capture_draft_upload",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            [f"{SCHEMA}.entities.id"],
            name="fk_capture_draft_entity",
        ),
        # One sequence number per upload. A retried or double-fired worker
        # would otherwise be able to insert "document 2" twice, and the user
        # would see the same receipt in the queue two times with no way to tell
        # which one is real.
        sa.UniqueConstraint(
            "upload_id", "sequence", name="uq_capture_draft_upload_sequence"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_draft_entity_status",
        DRAFT,
        ["entity_id", "status"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_draft_upload", DRAFT, ["upload_id"], schema=SCHEMA
    )

    op.create_table(
        AUDIT,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), nullable=False),
        # Not a foreign key, deliberately — see the note in the docstring.
        sa.Column("draft_id", sa.String(36), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column("pass_number", sa.SmallInteger, nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("location", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("thought_tokens", sa.Integer, nullable=True),
        sa.Column("cached_tokens", sa.Integer, nullable=True),
        sa.Column("estimated_cost", sa.Numeric(12, 6), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        # Field name -> confidence number. NO VALUES, ever.
        sa.Column("confidence_by_field", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["upload_id"],
            [f"{SCHEMA}.{UPLOAD}.id"],
            name="fk_capture_audit_upload",
            ondelete="CASCADE",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_capture_ai_audit_entity_created",
        AUDIT,
        ["entity_id", "created_at"],
        schema=SCHEMA,
    )

    print(
        f"Created {SCHEMA}.{UPLOAD}, {SCHEMA}.{DRAFT}, {SCHEMA}.{AUDIT} "
        "(empty — no backfill, by design)."
    )


def downgrade():
    bind = op.get_bind()
    if not _has_table(bind, UPLOAD):
        return

    # Loud, because by the time anyone runs this in anger the tables may hold
    # drafts a user has reviewed but not yet confirmed. Those cannot be
    # recreated — the model would have to read every receipt again.
    #
    # Skipped offline for the same reason as _has_table: there is nothing to
    # count against in a generated script.
    drafts = 0
    if not op.get_context().as_sql:
        drafts = bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.{DRAFT}")
        ).scalar()
    if drafts:
        print(
            f"WARNING: dropping these tables DESTROYS {drafts} capture "
            "draft(s), including any a user has edited but not confirmed. "
            "Restore from backup if this was not intended. Drafts already "
            "posted are unaffected — those are shop_expense rows."
        )

    op.drop_index("ix_capture_ai_audit_entity_created", table_name=AUDIT, schema=SCHEMA)
    op.drop_table(AUDIT, schema=SCHEMA)

    op.drop_index("ix_capture_draft_upload", table_name=DRAFT, schema=SCHEMA)
    op.drop_index("ix_capture_draft_entity_status", table_name=DRAFT, schema=SCHEMA)
    op.drop_table(DRAFT, schema=SCHEMA)

    op.drop_index("ix_capture_upload_created", table_name=UPLOAD, schema=SCHEMA)
    op.drop_index("ix_capture_upload_dedupe", table_name=UPLOAD, schema=SCHEMA)
    op.drop_index("ix_capture_upload_entity_status", table_name=UPLOAD, schema=SCHEMA)
    op.drop_table(UPLOAD, schema=SCHEMA)
