-- Demo app schema (database "app").
-- BASELINE: intentionally NO UNIQUE constraint on notification_id (see docs/ARCHITECTURE.md section 3).
CREATE TABLE IF NOT EXISTS notifications (
    id              BIGSERIAL PRIMARY KEY,
    notification_id UUID        NOT NULL,
    user_id         TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    body            TEXT        NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'delivered',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id);
