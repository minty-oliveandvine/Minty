# `docs/schema` — the redesigned database and how production gets into it

| File | Role |
|---|---|
| `01_schema_rebased.sql` | **The target.** 59 tables + 2 views, 21 enums, uuid keys, numeric money, timestamptz. Its header is the decision register (three eras, 19 items); read that before anything else. Builds clean from empty: `psql "$URL" -v ON_ERROR_STOP=1 -f docs/schema/01_schema_rebased.sql`. |
| `generators/gen.py` | **The only place the transformation is written.** Reads both catalogues from `information_schema` and emits the three files below. Dictionaries, not statements: `TABLE_SRC`, `OVERRIDE`, `EXPR`, `ENUM_MAP`, `USER_REFS`, `DISTINCT_ON`, `PRE`, `EXPECT_SKIP`. Regenerate after any change to `01`: `python docs/schema/generators/gen.py` (`GEN_DB` names a database holding both schemas; `GEN_PLAN=1` prints the per-column plan and writes nothing). |
| `00_enum_coverage_check.sql` | Generated. Every distinct source value, through its mapping, against the enum that receives it. All OK or it exits non-zero. |
| `02_data_foundation_rebased.sql` | Generated. 25 foundation tables, `pettycashv2` at alembic head → `pettycash_test`, in one database. Checks B1–B6. Ends in `ROLLBACK`. |
| `03_data_reports_rebased.sql` | Generated. 33 report / xero / billing / subscription tables, then the expense receipts: `shop_expense.files` → `attachment` + `report_expense_attachment`, split on the app's own key boundary (`receipt_keys._KEY_BOUNDARY`, read by `gen.py`). Checks R1–R9. Ends in `ROLLBACK`. |
| `../../scripts/schema_migration/rehearse.py` | **Runs the whole thing** and is the only supported way to: restore → snapshot → alembic upgrade → upgrade check (U1/U2) → build → 00 → 02 → 03 → manifest, timed, non-zero on the first check that is not green. |
| `generators/audit_models.py`, `mkdoc.py` | Diff every model in the three repos against the built schema; `APPLICATION_CHANGES.md` is its output. **0 findings since 2026-09-17** (phase C closed; it was 287) — `tests/test_zz_schema_audit.py` runs it against the harness build on every test run, and `mkdoc.py` now renders the close-out record. |
| `pettycashv2_schema.sql` | DDL snapshot of the **current** production schema (see below). |
| `supabase/` | Comment-free copies from `generators/strip_comments.py`: `pettycashv3.sql` (= `01` with the schema named `pettycashv3`), `00`, `02`, `03`. Its README says which may be pasted into a SQL editor (`pettycashv3.sql` and `00`) and why `02`/`03` are psql-only. |
| `archive/` | The schema-2 era. Record only. |

## One hop

```
old production (pettycashv2 @ f3a1c2b4d6e8)
   │  pg_dump -Fc -n pettycashv2
   ▼
scratch database ── flask db upgrade ──▶ pettycashv2 @ alembic head (~20 s)
   │                                        the app's own report/sales/cash redesign
   │  U1/U2 against a snapshot taken before it: no posted report's total needs an
   │  expense row the upgrade dropped, and no stored total moved
   ▼
01_schema_rebased.sql ──▶ pettycash_test, same database
   │  00 → 02 → 03   (03 ends with the expense receipts)
   ▼
checks: parity with expected skips · enum mapping counts · key survival · money sums to the cent
        · sales breakdown · cash-count view · restored references · <db>_not_carried.md
```

The alembic chain does the hard part — `report`/`report_draft`/`report_v2` share one
id by design (r1a01), the wide cash counts become rows (c2a02), sales become
`report_sale_detail` + a catalogue (s1a01–s5a05). The loaders then do the rebase:
types, the enum vocabulary (01 header item 18), nine renames, the token split, and the
handful of things item 19 lists. One run on the production dataset:

```
SUBSCRIPTION_ENABLED=0 PYTHONUTF8=1 python scripts/schema_migration/rehearse.py --from-db production-backup --db pcreh_github7d_upcheck
    restore 4.6s · snapshot 0.1s · upgrade 20.4s · upgrade-check 0.6s · build 0.5s · 00 0.1s · 02 1.6s · 03 218.4s · manifest 0.9s
    total 247s  → maintenance window 8 min          ALL GREEN   (2026-09-28, the 09-25 data: 5,078 of 5,176 reports,
                                                    13,866 receipt links, 485 expense rows dropped by the upgrade and
                                                    none of them in a posted total; the August dump: 159s)
```

`rehearse.py` drops `--db` before restoring into it, so give each run a name no other
session is using - on 2026-09-28 a second session picked the same `pcreh_<date>` name
and dropped the first one's database between its load and its checks. `backups/<db>_rehearsal.log` has every check line;
`backups/<db>_not_carried.md` lists every source row that has no target row, by reason, with ids.

## The applications run on it

Part 1 phase C of `../modernisation/modernisation_plan.md` (C1–C10, 2026-09-16/17) moved
Minty, billing-backend and onboarding-backend onto this schema with the schema as the
authority: every model follows `01`, the enum vocabulary lives in one module per repo
(`blueprints/shared/enums.py`, the two `shared_models/enums.py`, checked against `01` by
`tests/test_enums_match_schema.py`), Alembic is frozen and `billing-backend/bills/migrations/`
is gone. The apps run against the local `postgres` database (schema `pettycashv3`, built from `01`
plus the catalogue rows; `minty_cleanse`, the phase C copy of production data, was dropped on
2026-09-21); Minty's tests build their own database from `01` per run (`tests/pg_harness.py`,
Postgres only, one database per xdist worker) — 1677 tests, ~2 min on all cores.

## Changing the schema

**Ask first** — the schema is the contract all three applications now follow. Then edit
`01_schema_rebased.sql` (and its decision register), rebuild it into the scratch
database, run `gen.py`, run `rehearse.py --skip-restore --db <same db>`, rebuild the local
`postgres` database from it, and let `tests/test_zz_schema_audit.py` name every model that has to follow. The header's
WHAT WAS ADDED counts are re-measured with the query under HOW TO BUILD IT, never
adjusted by hand.

## `pettycashv2_schema.sql` — the current production shape

A **DDL-only snapshot** of `pettycashv2` as it stands on Supabase (PostgreSQL 17.6),
captured 2026-09-02 at `s5a05_drop_legacy_sales`; 67 tables, 1 view (`tracker`). Not a
migration: never run it against an existing database or add it to the alembic chain.
Regenerate with

```bash
pg_dump "$RDS_DATABASE_URI" --schema-only --schema=pettycashv2 --no-owner --no-acl \
  --no-publications --no-subscriptions -f docs/schema/pettycashv2_schema.sql
```

`--no-owner --no-acl` strips the Supabase role grants, which do not exist on a plain
Postgres. Two cosmetic localhost/Supabase differences are known: `sale_info.sale_id`'s
not-null constraint is named on one side and anonymous on the other, and three
columns (`cancel_reason`, `payment_method`, `hosted_invoice_url`) sit at different
ordinal positions.
