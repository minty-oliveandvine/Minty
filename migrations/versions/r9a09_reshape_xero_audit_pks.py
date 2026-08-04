"""STEP 4d — reshape the Xero audit-trail PKs so a report delete does not erase them

Revision ID: r9a09_reshape_xero_pks
Revises: r8a08_repoint_rcc_fk
Create Date: 2026-08-03

=============================================================================
WHAT THIS IS

`xero_report_sync` and `xero_bank_transfer` are the audit trail of what was
pushed to Xero — the record that detects a double-publish. Publishing stores no
Xero object IDs, so a second publish re-POSTs everything and duplicates it in
the customer's ledger. These two tables are how that is caught.

Today, deleting a local report erases that record.

Both tables carry their report FK **inside a composite primary key**:

    xero_report_sync   PRIMARY KEY (id, report_id)
    xero_bank_transfer PRIMARY KEY (id, sync_report_id)

r4a04 gave those FKs `ON DELETE CASCADE` **only because** a PK column cannot be
`SET NULL` — the cascade was forced by the key shape, not chosen for its
behaviour. This revision changes the shape so the intended behaviour is
available:

    * drop the composite PK, leaving `id` as the sole primary key
    * make the FK column nullable
    * re-point the FK to ON DELETE SET NULL

Deleting a report then leaves its Xero audit rows in place with a NULL report
reference, rather than deleting them.

-----------------------------------------------------------------------------
NO DATA MOVEMENT

`id` already exists on both tables as `String(36)` with a `uuid4` default and
is already part of the PK, so it is populated and unique. The pre-flight below
proves uniqueness and non-NULLness before touching anything, and aborts rather
than dropping a key it cannot re-add.

-----------------------------------------------------------------------------
THE CODE HALF OF THIS CHANGE ALREADY SHIPPED

`report_detail.py::_delete_report_children` used to explicitly delete rows from
both tables. Those two lines were removed in Step 4a-2.

That removal is a **no-op until this revision runs** — the FKs still CASCADE,
so the rows go either way. It is only once this migration flips them to
SET NULL that the trail actually survives. Conversely, running this migration
while those deletes were still in the code would have achieved nothing: the
application would have erased the trail before the FK ever mattered.

Both halves are required. Neither is harmful alone.

-----------------------------------------------------------------------------
INDEPENDENT of the r10a10 drops. Ship before or after; do NOT bundle into
r10a10 — an irreversible drop and a reversible constraint change do not belong
in one transaction.

REVERSIBLE. downgrade() restores the composite PKs and the CASCADE. It fails if
any row has a NULL FK by then (i.e. a report was deleted while this was
applied) — correct, because such a row is exactly what the old shape could not
represent. Delete those orphans first if you genuinely need to go back.
=============================================================================
"""
import sqlalchemy as sa
from alembic import op

revision = "r9a09_reshape_xero_pks"
down_revision = "r8a08_repoint_rcc_fk"
branch_labels = None
depends_on = None

SCHEMA = "pettycashv2"

# (table, fk_column, parent_table)
AUDIT_TABLES = [
    ("xero_report_sync", "report_id", "report"),
    ("xero_bank_transfer", "sync_report_id", "report"),
]


def _has_table(bind, table):
    return sa.inspect(bind).has_table(table, schema=SCHEMA)


def _pk_name(bind, table):
    return bind.execute(
        sa.text(
            """
            SELECT con.conname FROM pg_constraint con
              JOIN pg_class cl ON cl.oid = con.conrelid
              JOIN pg_namespace ns ON ns.oid = cl.relnamespace
             WHERE con.contype='p' AND ns.nspname=:s AND cl.relname=:t
            """
        ),
        {"s": SCHEMA, "t": table},
    ).scalar()


def _fk_names(bind, table, column):
    return [
        r[0]
        for r in bind.execute(
            sa.text(
                """
                SELECT con.conname
                  FROM pg_constraint con
                  JOIN pg_class cl ON cl.oid = con.conrelid
                  JOIN pg_namespace ns ON ns.oid = cl.relnamespace
                  JOIN unnest(con.conkey) k ON true
                  JOIN pg_attribute a ON a.attrelid = cl.oid AND a.attnum = k
                 WHERE con.contype='f' AND ns.nspname=:s
                   AND cl.relname=:t AND a.attname=:c
                """
            ),
            {"s": SCHEMA, "t": table, "c": column},
        )
    ]


def upgrade():
    bind = op.get_bind()
    for table, fk_col, parent in AUDIT_TABLES:
        if not _has_table(bind, table):
            print(f"r9a09: {table} missing; skipping")
            continue

        # Pre-flight: `id` must be able to stand alone as the PK.
        bad = bind.execute(
            sa.text(
                f"""
                SELECT count(*) FROM (
                    SELECT id FROM {SCHEMA}.{table}
                     WHERE id IS NULL
                     UNION ALL
                    SELECT id FROM {SCHEMA}.{table}
                     GROUP BY id HAVING count(*) > 1
                ) x
                """
            )
        ).scalar()
        if bad:
            raise RuntimeError(
                f"r9a09: {table}.id is not unique/non-null ({bad} offending "
                "rows). It cannot become the sole primary key. Investigate — "
                "do NOT force past this."
            )

        for name in _fk_names(bind, table, fk_col):
            op.drop_constraint(name, table, schema=SCHEMA, type_="foreignkey")
            print(f"r9a09: dropped FK {name}")

        pk = _pk_name(bind, table)
        if pk:
            op.drop_constraint(pk, table, schema=SCHEMA, type_="primary")
            print(f"r9a09: dropped composite PK {pk}")

        op.create_primary_key(f"{table}_pkey", table, ["id"], schema=SCHEMA)
        op.alter_column(table, fk_col, nullable=True, schema=SCHEMA)
        op.create_foreign_key(
            f"{table}_{fk_col}_fkey",
            table,
            parent,
            [fk_col],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="SET NULL",
        )
        print(
            f"r9a09: {table} -> PK(id), {fk_col} nullable, "
            f"FK ON DELETE SET NULL. Audit trail now survives report deletion."
        )


def downgrade():
    bind = op.get_bind()
    for table, fk_col, parent in AUDIT_TABLES:
        if not _has_table(bind, table):
            continue

        orphans = bind.execute(
            sa.text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE {fk_col} IS NULL")
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"r9a09 downgrade: {table} has {orphans} rows with a NULL "
                f"{fk_col} — audit rows whose report was deleted while this "
                "revision was applied. The old composite PK cannot represent "
                "them. Delete or re-key them first if you really want to "
                "revert (that DESTROYS Xero publish history)."
            )

        for name in _fk_names(bind, table, fk_col):
            op.drop_constraint(name, table, schema=SCHEMA, type_="foreignkey")
        pk = _pk_name(bind, table)
        if pk:
            op.drop_constraint(pk, table, schema=SCHEMA, type_="primary")

        op.alter_column(table, fk_col, nullable=False, schema=SCHEMA)
        op.create_primary_key(f"{table}_pkey", table, ["id", fk_col], schema=SCHEMA)
        op.create_foreign_key(
            f"{table}_{fk_col}_fkey",
            table,
            parent,
            [fk_col],
            ["id"],
            source_schema=SCHEMA,
            referent_schema=SCHEMA,
            ondelete="CASCADE",
        )
        print(f"r9a09 downgrade: {table} restored to composite PK + CASCADE")
