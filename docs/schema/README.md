# `pettycashv2` schema snapshot

`pettycashv2_schema.sql` is a **DDL-only snapshot** of the `pettycashv2` schema as it
actually stands in the database. It exists because the repo otherwise only describes
*changes* — the ~20 hand-written `.sql` files and 63 alembic revisions under
`migrations/` — with no single place to read the resulting shape.

| | |
|---|---|
| Source database | Supabase (`db.cedoiprsnbjufvvgaodx.supabase.co`), PostgreSQL 17.6 |
| Alembic revision | `s5a05_drop_legacy_sales` (the repo's single migration head) |
| Captured | 2026-09-02 |
| Contents | 67 tables, 1 view (`tracker`), 3 sequences, 73 indexes, 82 foreign keys. No rows. |

## This is not a migration

Do **not** run it against an existing database, and do **not** add it to the alembic
chain. Schema changes still go through hand-written migrations in `migrations/` —
`flask db migrate` autogenerate is unusable in this project because `env.py` does not
set `include_schemas`, so it proposes recreating every table.

The file is here to be read and diffed. Regenerating it after a migration and diffing
the result is a cheap way to see exactly what that migration did to the live schema.

## Regenerate

```bash
pg_dump "$RDS_DATABASE_URI" \
  --schema-only \
  --schema=pettycashv2 \
  --no-owner --no-acl \
  --no-publications --no-subscriptions \
  -f docs/schema/pettycashv2_schema.sql
```

Then re-add the header comment block at the top of the file.

`--no-owner --no-acl` strips `ALTER ... OWNER TO postgres` and the grants to Supabase's
`anon` / `authenticated` / `service_role` roles. Those roles do not exist on a plain
Postgres, and leaving them in makes every regeneration a noisy diff.

## Verified

- Restores clean into an empty database under `psql --set ON_ERROR_STOP=1`, producing
  all 67 tables. No dependency on extensions living outside the schema.
- Diffed against a dump of the local database at the same revision. The two are
  functionally identical; the only differences are noted below.

## Known Supabase / localhost divergences

Both databases are at `s5a05_drop_legacy_sales` with an identical set of 67 tables and
671 columns. Two cosmetic differences survive, neither of which changes behaviour:

1. **`sale_info.sale_id`** — localhost carries a *named* not-null constraint
   (`sale_info_sale_id_not_null`); Supabase's is anonymous. Same constraint, different
   catalogue entry.
2. **Column ordinal position** — `cancel_reason`, `payment_method` and
   `hosted_invoice_url` sit at different positions in their tables on the two
   databases, because the columns were added in a different order on each. Only
   matters to `SELECT *` and to `INSERT` without an explicit column list.
