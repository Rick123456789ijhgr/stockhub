-- migrate:up

CREATE TABLE raw_objects (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider   text NOT NULL,
  dataset    text NOT NULL,
  params     jsonb NOT NULL DEFAULT '{}'::jsonb,
  uri        text NOT NULL,
  sha256     char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  bytes      bigint NOT NULL CHECK (bytes >= 0),
  fetched_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT raw_objects_sha256_key UNIQUE (sha256)
);
COMMENT ON TABLE raw_objects IS 'Registry of raw provider responses kept in RawStore, deduplicated by content hash.';
COMMENT ON COLUMN raw_objects.uri IS 'RawStore location: raw/{provider}/{dataset}/{yyyy}/{mm}/{dd}/{sha256}.json.gz under a file:// or gs:// root.';
COMMENT ON COLUMN raw_objects.sha256 IS 'Hex SHA-256 of the uncompressed payload.';
COMMENT ON COLUMN raw_objects.bytes IS 'Size of the uncompressed payload in bytes.';
COMMENT ON COLUMN raw_objects.params IS 'Request parameters of the first fetch that produced this payload.';
CREATE INDEX raw_objects_provider_dataset_idx ON raw_objects (provider, dataset, fetched_at DESC);

CREATE TABLE job_runs (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  job_name     text NOT NULL,
  params       jsonb NOT NULL DEFAULT '{}'::jsonb,
  status       text NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  rows_written integer NOT NULL DEFAULT 0 CHECK (rows_written >= 0),
  error        text,
  checkpoint   jsonb,
  "trigger"    text NOT NULL CHECK ("trigger" IN ('schedule', 'manual')),
  CONSTRAINT job_runs_finished_check CHECK ((status = 'running') = (finished_at IS NULL))
);
COMMENT ON TABLE job_runs IS 'One row per scheduled or manual job execution; drives /status and freshness alerts.';
COMMENT ON COLUMN job_runs.checkpoint IS 'Resume state saved during the run; a rerun with the same params resumes from the latest failed run.';
COMMENT ON COLUMN job_runs.rows_written IS 'Rows inserted or updated in target tables.';
CREATE INDEX job_runs_name_started_idx ON job_runs (job_name, started_at DESC);
CREATE INDEX job_runs_started_idx ON job_runs (started_at DESC);
-- At most one in-flight run per job + params.
CREATE UNIQUE INDEX job_runs_one_running_idx ON job_runs (job_name, params) WHERE status = 'running';

CREATE TABLE settings (
  key        text PRIMARY KEY,
  value      jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE settings IS 'Personal key/value settings, e.g. brokerage fee discount.';
CREATE TRIGGER settings_updated_at BEFORE UPDATE ON settings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE audit_log (
  id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  at     timestamptz NOT NULL DEFAULT now(),
  actor  text NOT NULL,
  action text NOT NULL,
  target text,
  detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
COMMENT ON TABLE audit_log IS 'Append-only log of manual admin actions.';
COMMENT ON COLUMN audit_log.actor IS 'Signed-in email, or job:<name> for automated actions.';
CREATE INDEX audit_log_at_idx ON audit_log (at DESC);

-- migrate:down
DROP TABLE audit_log;
DROP TABLE settings;
DROP TABLE job_runs;
DROP TABLE raw_objects;
