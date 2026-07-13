-- Add publishing_status to report_draft.
--
-- Reverting a submitted report to draft deletes its Report row, which is where
-- publishing_status lived. That column is the only signal that the report was
-- already pushed to Xero; re-publishing without it silently creates duplicate
-- transactions. Carrying it onto the draft lets it survive the revert and be
-- restored onto the Report when the draft is submitted again.

ALTER TABLE pettycashv2.report_draft
    ADD COLUMN IF NOT EXISTS publishing_status VARCHAR(20);
