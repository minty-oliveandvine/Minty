-- ============================================================================
-- Add invitations.first_name / last_name
--
-- The invitee's name is now captured at invite time and persisted, so the
-- pending-invite cards (onboarding Step 8 + Settings -> Users) keep the
-- name/email/role format when the invite is re-read from the DB on resume.
-- Previously the name lived only in the accept URL. Existing rows are left NULL.
--
-- Raw-SQL equivalent of alembic revision b1d3f5a7c9e2 (down_revision a9c1e3f5b7d2).
-- Running this script also advances pettycashv2.alembic_version so a later
-- `alembic upgrade head` does not try to re-apply the revision.
-- ============================================================================

BEGIN;

-- Guard: only apply on top of the expected alembic revision.
DO $$
DECLARE v text;
BEGIN
    SELECT version_num INTO v FROM pettycashv2.alembic_version;
    IF v IS DISTINCT FROM 'a9c1e3f5b7d2' THEN
        RAISE EXCEPTION
            'alembic_version is % — expected a9c1e3f5b7d2; run the missing migrations first (or this one is already applied)', v;
    END IF;
END $$;

ALTER TABLE pettycashv2.invitations
    ADD COLUMN first_name varchar(100),
    ADD COLUMN last_name  varchar(100);

UPDATE pettycashv2.alembic_version
    SET version_num = 'b1d3f5a7c9e2';

COMMIT;

-- ============================================================================
-- Rollback (equivalent of downgrade()):
--
-- BEGIN;
-- ALTER TABLE pettycashv2.invitations
--     DROP COLUMN last_name,
--     DROP COLUMN first_name;
-- UPDATE pettycashv2.alembic_version
--     SET version_num = 'a9c1e3f5b7d2';
-- COMMIT;
-- ============================================================================
