-- Help-desk database schema (SQLite). Safe to run many times.
CREATE TABLE IF NOT EXISTS tickets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL CHECK (length(trim(customer_name)) BETWEEN 2 AND 60),
    issue         TEXT NOT NULL CHECK (length(trim(issue)) BETWEEN 5 AND 500),
    priority      TEXT NOT NULL DEFAULT 'Medium'
                  CHECK (priority IN ('Low', 'Medium', 'High', 'Critical')),
    status        TEXT NOT NULL DEFAULT 'Open'
                  CHECK (status IN ('Open', 'In Progress', 'Closed')),
    created_at    TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS'
    updated_at    TEXT NOT NULL,
    closed_at     TEXT,                       -- only filled when status = 'Closed'
    resolution    TEXT,
    CHECK ((status = 'Closed' AND closed_at IS NOT NULL)
        OR (status <> 'Closed' AND closed_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_tickets_status_priority ON tickets (status, priority);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at      ON tickets (created_at);
