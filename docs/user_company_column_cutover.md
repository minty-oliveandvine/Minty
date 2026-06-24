# User Company Column Cutover

`pettycashv2."user".company` is no longer part of the runtime contract. Entity access and defaults now come from `UserEntity` memberships and explicit `entity_id` request values.

## One-shot rollout

1. Back up the legacy values before running the Alembic upgrade:

```sql
CREATE TABLE pettycashv2.user_company_backup AS
SELECT
    id AS user_id,
    company,
    CURRENT_TIMESTAMP AS captured_at
FROM pettycashv2."user"
WHERE company IS NOT NULL;
```

2. Compare the backup count to the remaining populated rows:

```sql
SELECT COUNT(*) AS backed_up_rows
FROM pettycashv2.user_company_backup;

SELECT COUNT(*) AS legacy_company_rows
FROM pettycashv2."user"
WHERE company IS NOT NULL;
```

3. Run the Alembic upgrade for revision `1a4d6b2d4ef3`.

4. Verify the column is gone after deployment:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'pettycashv2'
  AND table_name = 'user'
  AND column_name = 'company';
```

That query must return zero rows.

## Rollback

- Roll back the app build before restoring the legacy column contract.
- Run the Alembic downgrade for revision `1a4d6b2d4ef3`.
- Restore data from the backup table if the downgraded build needs the old values:

```sql
UPDATE pettycashv2."user" AS u
SET company = b.company
FROM pettycashv2.user_company_backup AS b
WHERE b.user_id = u.id;
```
