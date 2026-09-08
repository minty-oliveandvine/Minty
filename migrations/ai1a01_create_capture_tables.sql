-- =============================================================================
-- CAPTURE 1 - create the three AI Capture Hub tables (Stage 2)
--
-- Hand-runnable twin of migrations/versions/ai1a01_create_capture_tables.py.
-- Use this on an environment alembic does not stamp. It is idempotent: every
-- statement uses IF NOT EXISTS, so running it twice is harmless, and running
-- the alembic revision afterwards is harmless too (it checks for the table
-- first and returns).
--
-- Purely additive. Nothing existing is touched. Safe to run on live at any
-- time, and safe to run BEFORE the application code ships - the feature stays
-- dark until CAPTURE_AI_ENABLED is turned on.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- capture_upload - one row per file a user dropped on the bubble
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.capture_upload (
    id                      VARCHAR(36)  PRIMARY KEY,
    entity_id               VARCHAR(36)  NOT NULL,
    uploaded_by             VARCHAR(36)  NOT NULL,
    original_filename       VARCHAR(255),
    -- The SNIFFED type, from the file's magic bytes. The declared extension is
    -- not evidence and is never stored here.
    mime_type               VARCHAR(64)  NOT NULL,
    byte_size               INTEGER      NOT NULL,
    -- 1 for images; the real page count for PDFs.
    page_count              INTEGER,
    -- Duplicate detection: a double-click or a re-upload must not create a
    -- second set of drafts, and must not cost a second set of model calls.
    content_sha256          VARCHAR(64)  NOT NULL,
    s3_key                  VARCHAR(512) NOT NULL,
    status                  VARCHAR(32)  NOT NULL DEFAULT 'queued',
    reject_reason           VARCHAR(64),
    document_count          INTEGER,
    -- Set by the "This IS a receipt - process it anyway" override.
    bypass_classification   BOOLEAN      NOT NULL DEFAULT false,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    -- Stamped when the worker picks the row up, so the stuck-job sweeper can
    -- recover a thread that died with the process.
    processing_started_at   TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,
    CONSTRAINT fk_capture_upload_entity
        FOREIGN KEY (entity_id) REFERENCES pettycashv2.entities (id),
    CONSTRAINT fk_capture_upload_user
        FOREIGN KEY (uploaded_by) REFERENCES pettycashv2."user" (id)
);

-- The bubble polls GET /capture/status every two seconds for every user with
-- it open. That query is (entity_id, status) and must not be a seq scan.
CREATE INDEX IF NOT EXISTS ix_capture_upload_entity_status
    ON pettycashv2.capture_upload (entity_id, status);

-- The duplicate check runs on EVERY upload, before the file is stored and
-- before any model call.
CREATE INDEX IF NOT EXISTS ix_capture_upload_dedupe
    ON pettycashv2.capture_upload (entity_id, content_sha256);

-- The retention sweeper's only filter.
CREATE INDEX IF NOT EXISTS ix_capture_upload_created
    ON pettycashv2.capture_upload (created_at);


-- ---------------------------------------------------------------------------
-- capture_draft - one row per document found inside an upload
--
-- Five receipts in one PDF are FIVE rows here and ONE row above.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.capture_draft (
    id                      VARCHAR(36)  PRIMARY KEY,
    upload_id               VARCHAR(36)  NOT NULL,
    -- Denormalised from the upload ON PURPOSE: every authorisation check reads
    -- it, and going through capture_upload would put a join on the hot path of
    -- every request to avoid storing 36 bytes.
    entity_id               VARCHAR(36)  NOT NULL,
    -- 1, 2, 3 ... within the upload. Drives "Document 2 of 5".
    sequence                INTEGER      NOT NULL,
    -- 1-based, inclusive. A two-page invoice is ONE row with start 1, end 2.
    page_start              INTEGER      NOT NULL,
    page_end                INTEGER      NOT NULL,
    -- Pass 1's short description, e.g. "top-left receipt, Starbucks HK$48".
    -- Only meaningful when several documents share one page. Untrusted text
    -- off a photograph - render with textContent, never innerHTML.
    locator                 VARCHAR(200),
    doc_type                VARCHAR(32)  NOT NULL,
    doc_type_confidence     NUMERIC(4,3),
    destination             VARCHAR(32)  NOT NULL,
    status                  VARCHAR(32)  NOT NULL DEFAULT 'ready',
    -- Pass 2's validated output, in the {value, confidence, band, applied}
    -- shape Stage 1 uses, so the queue page can reuse expense_ai.js's marking.
    suggested               JSONB,
    -- What the user actually saved. The pair (suggested, confirmed) is the
    -- only signal worth feeding back into the prompt later.
    confirmed               JSONB,
    -- Lifted out of suggested so the queue can sort and filter without
    -- unpacking JSON on every row.
    document_date           DATE,
    amount                  NUMERIC(14,2),
    currency                VARCHAR(3),
    supplier_name           VARCHAR(150),
    -- The single-document file cut out of the original. NULL when the upload
    -- held one document - then the parent's s3_key is the file.
    page_s3_key             VARCHAR(512),
    -- What it became: a shop_expense.id, or Module 2's PaymentRequest id.
    target_ref              VARCHAR(128),
    send_attempts           INTEGER      NOT NULL DEFAULT 0,
    -- Never contains file contents.
    last_error              VARCHAR(500),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    confirmed_at            TIMESTAMPTZ,
    confirmed_by            VARCHAR(36),
    CONSTRAINT fk_capture_draft_upload
        FOREIGN KEY (upload_id) REFERENCES pettycashv2.capture_upload (id)
        ON DELETE CASCADE,
    CONSTRAINT fk_capture_draft_entity
        FOREIGN KEY (entity_id) REFERENCES pettycashv2.entities (id),
    -- A retried or double-fired worker would otherwise insert "document 2"
    -- twice, and the user would see the same receipt in the queue two times
    -- with no way to tell which one is real.
    CONSTRAINT uq_capture_draft_upload_sequence UNIQUE (upload_id, sequence)
);

CREATE INDEX IF NOT EXISTS ix_capture_draft_entity_status
    ON pettycashv2.capture_draft (entity_id, status);

CREATE INDEX IF NOT EXISTS ix_capture_draft_upload
    ON pettycashv2.capture_draft (upload_id);


-- ---------------------------------------------------------------------------
-- capture_ai_audit - one row per AI call. NUMBERS ONLY.
--
-- No amounts, no supplier names, no descriptions, no file bytes. Those are a
-- client's financial details and a metrics table is the wrong place for them.
-- This table answers "is the feature worth what it costs", and that question
-- does not need a single receipt total.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pettycashv2.capture_ai_audit (
    id                      VARCHAR(36)  PRIMARY KEY,
    upload_id               VARCHAR(36)  NOT NULL,
    -- NULL for Pass 1: the split call belongs to the upload, because it is the
    -- call that decides how many drafts there will be. Deliberately not a
    -- foreign key - a nullable FK that is null half the time buys nothing the
    -- CASCADE on upload_id does not already give us.
    draft_id                VARCHAR(36),
    entity_id               VARCHAR(36)  NOT NULL,
    pass_number             SMALLINT     NOT NULL,
    model_id                VARCHAR(64),
    -- A compliance field, not a performance knob. On the direct Gemini API
    -- there is no region to pin, and that absence is the fact worth recording.
    location                VARCHAR(64),
    latency_ms              INTEGER,
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    -- Billed at the OUTPUT rate and invisible in the reply. Leaving thinking
    -- out of the cost sum understated a measured Stage 1 call by ~60%.
    thought_tokens          INTEGER,
    -- Zero across repeated calls for one entity means the cacheable prefix is
    -- under Gemini's minimum or is not byte-stable. Worth an alert.
    cached_tokens           INTEGER,
    -- An indication for the dashboard, not an invoice.
    estimated_cost          NUMERIC(12,6),
    status                  VARCHAR(32)  NOT NULL,
    reason                  VARCHAR(64),
    -- Field name -> confidence number. NO VALUES.
    confidence_by_field     JSONB,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT fk_capture_audit_upload
        FOREIGN KEY (upload_id) REFERENCES pettycashv2.capture_upload (id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_capture_ai_audit_entity_created
    ON pettycashv2.capture_ai_audit (entity_id, created_at);

COMMIT;

-- =============================================================================
-- TO REVERSE (destroys any unconfirmed drafts - take a backup first):
--
--   BEGIN;
--   DROP TABLE IF EXISTS pettycashv2.capture_ai_audit;
--   DROP TABLE IF EXISTS pettycashv2.capture_draft;
--   DROP TABLE IF EXISTS pettycashv2.capture_upload;
--   COMMIT;
--
-- Drafts already posted are unaffected: those became shop_expense rows or
-- Module 2 PaymentRequests and do not live here.
-- =============================================================================
