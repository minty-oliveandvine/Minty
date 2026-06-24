"""add user.xero_email + backfill legacy Xero rows + dedupe split persons

Adds a dedicated ``xero_email`` identity column so the email-OTP and Xero login
flows can be unified: a person whose personal ``email`` equals their Xero
``xero_email`` is one user (one row); different addresses stay two users.

Data steps:
  1. add ``xero_email`` (nullable).
  2. backfill: legacy Xero rows stored the Xero email in ``username`` while
     ``email`` stayed NULL — copy ``lower(username)`` into ``xero_email``.
  3. dedupe: where a personal/OTP row and a legacy Xero row share the same
     address, repoint all child FKs onto the personal row, delete the Xero row,
     then copy its Xero-side fields onto the survivor.
  4. add the UNIQUE constraint (after dedupe, so it can't fail).

Revision ID: add_user_xero_email
Revises: dc9b0d357bcc
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa
from loguru import logger

# revision identifiers, used by Alembic.
revision = "add_user_xero_email"
# Chains after the lock-dates/email-otp merge head so there's a single head.
# (Originally branched off "add_email_otp", which created a second head once
# the merge revision dc9b0d357bcc also took add_email_otp as a parent.)
down_revision = "dc9b0d357bcc"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. add the column (nullable for now)
    op.add_column(
        "user",
        sa.Column("xero_email", sa.String(length=100), nullable=True),
        schema="pettycashv2",
    )

    # 2. backfill: legacy Xero rows kept the Xero email in `username`, email NULL
    conn.execute(
        sa.text(
            """
            UPDATE pettycashv2."user"
            SET xero_email = lower(username)
            WHERE xero_email IS NULL
              AND email IS NULL
              AND username LIKE '%@%'
            """
        )
    )

    # 2b. Xero-created users defaulted to approved=False (the Xero login flow
    #     ignores `approved`). The unified resolver now lets them log in via OTP,
    #     which DOES enforce `approved`, so bring Xero-origin rows in line with
    #     every other signup path (which set approved=True).
    conn.execute(
        sa.text(
            """
            UPDATE pettycashv2."user"
            SET approved = true
            WHERE approved = false
              AND email IS NULL
              AND username LIKE '%@%'
            """
        )
    )

    # 3. dedupe split persons: a personal/OTP row (email set) and a legacy Xero
    #    row (xero_email set) that share the same address.
    pairs = conn.execute(
        sa.text(
            """
            SELECT c.id AS canonical_id, d.id AS dup_id
            FROM pettycashv2."user" c
            JOIN pettycashv2."user" d
              ON d.id <> c.id
             AND lower(d.xero_email) = lower(c.email)
            WHERE c.email IS NOT NULL
              AND d.xero_email IS NOT NULL
            """
        )
    ).fetchall()

    if pairs:
        logger.info(
            "xero_email dedupe: merging {} duplicate user row(s): {}",
            len(pairs),
            [f"{r.dup_id} -> {r.canonical_id}" for r in pairs],
        )

        # Carry the dup's Xero-side fields so we can graft them onto the
        # canonical row AFTER the dup is deleted (avoids the xero_email UNIQUE
        # clash that an in-place copy would hit).
        conn.execute(
            sa.text(
                """
                CREATE TEMP TABLE _dup_merge ON COMMIT DROP AS
                SELECT c.id AS canonical_id, d.id AS dup_id,
                       d.xero_email, d.xero_user_id, d.xero_entity_id,
                       d.access_token, d.refresh_token, d.id_token,
                       d.expires_in, d.token_created_at, d.xero_token,
                       c.xero_user_id   AS c_xero_user_id,
                       c.xero_entity_id AS c_xero_entity_id
                FROM pettycashv2."user" c
                JOIN pettycashv2."user" d
                  ON d.id <> c.id
                 AND lower(d.xero_email) = lower(c.email)
                WHERE c.email IS NOT NULL
                  AND d.xero_email IS NOT NULL
                """
            )
        )

        # entities.connected_by_user_id (ON DELETE RESTRICT — must repoint first)
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.entities e
                SET connected_by_user_id = m.canonical_id
                FROM _dup_merge m
                WHERE e.connected_by_user_id = m.dup_id
                """
            )
        )
        # invitations.invited_by
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.invitations i
                SET invited_by = m.canonical_id
                FROM _dup_merge m
                WHERE i.invited_by = m.dup_id
                """
            )
        )
        # report_history.user_id / report_history_draft.user_id
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.report_history rh
                SET user_id = m.canonical_id
                FROM _dup_merge m
                WHERE rh.user_id = m.dup_id
                """
            )
        )
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.report_history_draft rhd
                SET user_id = m.canonical_id
                FROM _dup_merge m
                WHERE rhd.user_id = m.dup_id
                """
            )
        )
        # user_entity (composite PK user_id+entity_id): drop dup memberships the
        # canonical already holds, then repoint the rest.
        conn.execute(
            sa.text(
                """
                DELETE FROM pettycashv2.user_entity ue
                USING _dup_merge m
                WHERE ue.user_id = m.dup_id
                  AND EXISTS (
                      SELECT 1 FROM pettycashv2.user_entity c
                      WHERE c.user_id = m.canonical_id
                        AND c.entity_id = ue.entity_id
                  )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.user_entity ue
                SET user_id = m.canonical_id
                FROM _dup_merge m
                WHERE ue.user_id = m.dup_id
                """
            )
        )
        # user_token (UNIQUE user_id): drop dup token if canonical already has
        # one, then repoint the rest.
        conn.execute(
            sa.text(
                """
                DELETE FROM pettycashv2.user_token ut
                USING _dup_merge m
                WHERE ut.user_id = m.dup_id
                  AND EXISTS (
                      SELECT 1 FROM pettycashv2.user_token c
                      WHERE c.user_id = m.canonical_id
                  )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2.user_token ut
                SET user_id = m.canonical_id
                FROM _dup_merge m
                WHERE ut.user_id = m.dup_id
                """
            )
        )

        # delete the duplicate rows (all child FKs now repointed)
        conn.execute(
            sa.text(
                """
                DELETE FROM pettycashv2."user" u
                USING _dup_merge m
                WHERE u.id = m.dup_id
                """
            )
        )

        # graft the dup's Xero-side identity onto the survivor
        conn.execute(
            sa.text(
                """
                UPDATE pettycashv2."user" c
                SET xero_email       = m.xero_email,
                    xero_user_id     = COALESCE(m.c_xero_user_id, m.xero_user_id),
                    xero_entity_id   = COALESCE(m.c_xero_entity_id, m.xero_entity_id),
                    access_token     = m.access_token,
                    refresh_token    = m.refresh_token,
                    id_token         = m.id_token,
                    expires_in       = m.expires_in,
                    token_created_at = m.token_created_at,
                    xero_token       = m.xero_token
                FROM _dup_merge m
                WHERE c.id = m.canonical_id
                """
            )
        )
    else:
        logger.info("xero_email dedupe: no duplicate user rows found")

    # 4. enforce one user per Xero email (multiple NULLs are allowed in Postgres)
    op.create_unique_constraint(
        "uq_user_xero_email", "user", ["xero_email"], schema="pettycashv2"
    )


def downgrade():
    # Note: merged duplicate rows cannot be reconstructed by a downgrade.
    op.drop_constraint(
        "uq_user_xero_email", "user", schema="pettycashv2", type_="unique"
    )
    op.drop_column("user", "xero_email", schema="pettycashv2")
