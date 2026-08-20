-- Motion Artwork API — initial schema
-- Run against Postgres 14+. No ORM-specific extensions required.

CREATE TABLE orgs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    tier            TEXT NOT NULL DEFAULT 'standard',   -- standard | enterprise
    webhook_secret  TEXT NOT NULL,                       -- HMAC key for signing webhook payloads
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    key_hash        TEXT NOT NULL UNIQUE,   -- store only a hash (e.g. sha256) of the raw key, never the raw key
    label           TEXT,
    revoked_at      TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_api_keys_key_hash ON api_keys(key_hash) WHERE revoked_at IS NULL;

CREATE TABLE batches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    job_count       INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                  UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    batch_id                UUID REFERENCES batches(id) ON DELETE SET NULL,
    kind                    TEXT NOT NULL DEFAULT 'generate',  -- 'generate' | 'qc_only'
    release_id              TEXT,          -- pass-through from the distributor, not interpreted
    artist_id               TEXT,
    cover_art_url           TEXT,
    tier                    TEXT,          -- parametric | stylized | cinematic (null for qc_only)
    duration_seconds        NUMERIC,
    style_preset            TEXT,
    callback_url            TEXT,
    metadata                JSONB DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'queued',
        -- queued -> processing -> qc_review -> complete | rejected | failed
    price_usd               NUMERIC(6,2),
    square_asset_url        TEXT,
    vertical_asset_url      TEXT,
    error_message           TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at            TIMESTAMPTZ
);
CREATE INDEX idx_jobs_org_status ON jobs(org_id, status);
CREATE INDEX idx_jobs_batch ON jobs(batch_id);

CREATE TABLE qc_reports (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    passed          BOOLEAN NOT NULL,
    checks          JSONB NOT NULL,     -- full per-check breakdown, see qc_suite.run_qc_suite()
    apple_ready     BOOLEAN NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_qc_reports_job ON qc_reports(job_id);

CREATE TABLE webhook_deliveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url             TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',   -- pending | delivered | failed
    last_error      TEXT,
    next_attempt_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_webhook_deliveries_pending ON webhook_deliveries(status, next_attempt_at)
    WHERE status = 'pending';
