# Archive — the schema-2 era

Kept as the record of how the redesign was arrived at. Nothing here is on any
path any more; `01_schema_rebased.sql` and the generated loaders beside it are
the only files that run.

| File | What it was |
|---|---|
| `01_schema 2.sql` | The original redesign (2026-09-04), written against alembic `e5b7d9f1a3c6`. `01_schema_rebased.sql` was rebased from it onto head and its enum vocabulary was readopted in item 18. |
| `02_data_foundation 1.sql`, `03_data_reports 1.sql` | The first loaders, `pettycashv2 -> pettycash_test`, which performed the report/draft/v2 merge by `(entity, transaction_date)` with a priority - the "3,764 shared ids" that turned out to be one identity by design (r1a01). Superseded by the one-hop pipeline, in which the alembic chain does that merge. |
| `pettycash_test_schema.sql`, `pettycash_test_v2_schema.sql` | Dumps of the two earlier builds (the uuid7 branch, ERA 1, and the first rebase). |

The two-hop pipeline (`pettycashv2 -> pettycash_s2 -> pettycash_test`) and the
D1-D5 decisions it produced are described in the 01 header, ERA 3 item 18.
