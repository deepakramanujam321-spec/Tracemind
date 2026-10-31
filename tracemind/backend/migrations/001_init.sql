-- TraceMind schema (db: tracemind). Orchestrator-owned; add new numbered files for changes.
CREATE TABLE IF NOT EXISTS spans (
  trace_id        TEXT NOT NULL,
  span_id         TEXT NOT NULL,
  parent_span_id  TEXT,
  name            TEXT NOT NULL,
  kind            TEXT,
  service_name    TEXT NOT NULL,
  service_version TEXT,
  environment     TEXT,
  start_time      TIMESTAMPTZ NOT NULL,
  end_time        TIMESTAMPTZ NOT NULL,
  duration_ms     DOUBLE PRECISION GENERATED ALWAYS AS (EXTRACT(EPOCH FROM (end_time - start_time)) * 1000) STORED,
  status_code     TEXT,            -- UNSET | OK | ERROR
  status_message  TEXT,
  attributes      JSONB NOT NULL DEFAULT '{}',
  resource        JSONB NOT NULL DEFAULT '{}',
  scope_name      TEXT,
  ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (trace_id, span_id)
);
CREATE INDEX IF NOT EXISTS spans_start_idx   ON spans (start_time DESC);
CREATE INDEX IF NOT EXISTS spans_service_idx ON spans (service_name, start_time DESC);
CREATE INDEX IF NOT EXISTS spans_error_idx   ON spans (status_code) WHERE status_code = 'ERROR';
CREATE INDEX IF NOT EXISTS spans_attr_gin    ON spans USING GIN (attributes jsonb_path_ops);

CREATE TABLE IF NOT EXISTS span_events (
  trace_id TEXT NOT NULL, span_id TEXT NOT NULL, idx INT NOT NULL,
  name TEXT NOT NULL, time TIMESTAMPTZ NOT NULL, attributes JSONB NOT NULL DEFAULT '{}',
  PRIMARY KEY (trace_id, span_id, idx),
  FOREIGN KEY (trace_id, span_id) REFERENCES spans (trace_id, span_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logs (
  id BIGSERIAL PRIMARY KEY,
  time TIMESTAMPTZ NOT NULL,
  trace_id TEXT, span_id TEXT,
  service_name TEXT NOT NULL,
  severity TEXT, severity_number INT,
  body TEXT,
  attributes JSONB NOT NULL DEFAULT '{}',
  resource JSONB NOT NULL DEFAULT '{}',
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS logs_trace_idx ON logs (trace_id, span_id);
CREATE INDEX IF NOT EXISTS logs_time_idx  ON logs (time DESC);

CREATE TABLE IF NOT EXISTS services (
  name TEXT PRIMARY KEY, version TEXT, environment TEXT,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(), last_seen TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS repositories (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, commit_sha TEXT NOT NULL,
  graph_status TEXT NOT NULL DEFAULT 'none',   -- none | graphify | fallback
  registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS incidents (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',          -- open | investigating | root_cause_found | inconclusive | remediated
  severity TEXT NOT NULL DEFAULT 'medium',
  primary_trace_id TEXT,
  trace_ids TEXT[] NOT NULL DEFAULT '{}',
  services TEXT[] NOT NULL DEFAULT '{}',
  context JSONB NOT NULL DEFAULT '{}',          -- deterministic IncidentContext (topology, timeline, signals, limitations)
  detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investigations (
  id TEXT PRIMARY KEY,
  incident_id TEXT NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
  repository_id TEXT REFERENCES repositories(id),
  status TEXT NOT NULL DEFAULT 'running',       -- running | completed | failed
  outcome TEXT,                                 -- supported | rejected | inconclusive
  adjudication JSONB,
  error TEXT,
  model_provider TEXT, model_name TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_steps (
  id BIGSERIAL PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  agent TEXT NOT NULL,                          -- trace_investigator | code_analyst | skeptic | adjudicator | remediation_engineer
  status TEXT NOT NULL, summary TEXT, output JSONB,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS hypotheses (
  id TEXT PRIMARY KEY,                          -- e.g. H-<investigation>-<n>
  investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  author_agent TEXT NOT NULL,
  description TEXT NOT NULL,
  confidence REAL,                              -- model-estimated, NOT a probability
  supporting_refs TEXT[] NOT NULL DEFAULT '{}',
  contradicting_refs TEXT[] NOT NULL DEFAULT '{}',
  alternatives TEXT[] NOT NULL DEFAULT '{}',
  missing_evidence TEXT[] NOT NULL DEFAULT '{}',
  challenges JSONB NOT NULL DEFAULT '[]',       -- skeptic output
  validation_status TEXT NOT NULL DEFAULT 'inconclusive'  -- supported | rejected | inconclusive
);

CREATE TABLE IF NOT EXISTS remediations (
  id TEXT PRIMARY KEY,
  investigation_id TEXT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
  repository_id TEXT NOT NULL REFERENCES repositories(id),
  base_sha TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',       -- pending | patch_generated | tested | verified | failed
  diff TEXT, files_changed TEXT[] NOT NULL DEFAULT '{}',
  test_summary JSONB,                           -- {passed, failed, scenario_regression_passed}
  approved_at TIMESTAMPTZ, error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS command_runs (
  id BIGSERIAL PRIMARY KEY,
  remediation_id TEXT NOT NULL REFERENCES remediations(id) ON DELETE CASCADE,
  command TEXT NOT NULL, exit_code INT, stdout TEXT, stderr TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(), duration_ms INT
);
