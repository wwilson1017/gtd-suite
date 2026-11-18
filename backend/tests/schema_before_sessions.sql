-- The schema of the link-based release (origin/master @ 4c9d21e, backend/db.py _SCHEMA),
-- pinned so test_lists.py can check that startup migrates a database made by it.

CREATE TABLE IF NOT EXISTS lists (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    web_token_hash    TEXT NOT NULL UNIQUE,   -- SHA-256; the token is shown once
    agent_token_hash  TEXT NOT NULL UNIQUE,   -- SHA-256 of agent_token; what a lookup matches
    -- Plain, so the web app can always show the agent link (like capture_token).
    -- Not a downgrade: the web link already reads and changes everything, and
    -- only the web link can fetch this. Nullable only because _migrate adds it
    -- to databases made before it existed; every row has one after startup.
    agent_token       TEXT,
    capture_token     TEXT NOT NULL UNIQUE,   -- plain, so the web app can display it
    tz                TEXT NOT NULL DEFAULT 'UTC',
    email             TEXT,
    created_at        TEXT NOT NULL,
    last_used_at      TEXT,
    review_started_at TEXT,
    name              TEXT NOT NULL DEFAULT '',  -- optional; common.validate_list_name
    -- Set by the operator (scripts/admin.py disable). While set, every link of
    -- the list answers as an unknown one (lists._resolve); nothing is deleted.
    disabled_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_lists_email ON lists(email) WHERE email IS NOT NULL;

-- Areas of focus: the standing parts of a life or job that projects and todos
-- hang off. Never deleted; archiving is status 'dropped'.
CREATE TABLE IF NOT EXISTS areas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    name        TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','dropped')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_areas_list_name ON areas(list_id, lower(name));

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    name        TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    purpose     TEXT NOT NULL DEFAULT '',   -- why it matters
    outcome     TEXT NOT NULL DEFAULT '',   -- what done looks like
    area_id     INTEGER REFERENCES areas(id),
    status      TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN ('active','someday','completed','dropped')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_list_name ON projects(list_id, lower(name));

CREATE TABLE IF NOT EXISTS todos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id          INTEGER NOT NULL REFERENCES lists(id),
    title            TEXT NOT NULL,
    notes            TEXT NOT NULL DEFAULT '',
    project_id       INTEGER REFERENCES projects(id),
    -- The todo's OWN area; NULL means "its project's area, if any" (service._SELECT_TODO).
    area_id          INTEGER REFERENCES areas(id),
    context          TEXT NOT NULL DEFAULT '',
    tags             TEXT NOT NULL DEFAULT '[]',     -- JSON array of strings
    people           TEXT NOT NULL DEFAULT '[]',     -- JSON array of strings
    status           TEXT NOT NULL DEFAULT 'inbox'
                     CHECK(status IN ('inbox','next_action','waiting_for','delegated',
                                      'someday_maybe','done','dropped')),
    star             INTEGER NOT NULL DEFAULT 0,
    due_date         TEXT,                           -- YYYY-MM-DD, date-only by design
    revisit_on       TEXT,                           -- YYYY-MM-DD: shown on Today from then on
    repeat           TEXT NOT NULL DEFAULT '',       -- validated by common.validate_repeat
    auto_star_on_due INTEGER NOT NULL DEFAULT 0,
    -- Who CREATED the row: set on insert, never changed by updates, copied to a
    -- repeat's next occurrence.
    source           TEXT NOT NULL DEFAULT 'agent'
                     CHECK(source IN ('ui','capture','agent')),
    source_client    TEXT,                           -- the AI tool's name when known
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    -- Brain tickle bookkeeping (service.record_tickle); never reset.
    last_tickled_at  TEXT,
    tickle_count     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_todos_list_status ON todos(list_id, status);
CREATE INDEX IF NOT EXISTS idx_todos_list_project ON todos(list_id, project_id);
CREATE INDEX IF NOT EXISTS idx_todos_list_due ON todos(list_id, due_date)
    WHERE completed_at IS NULL AND due_date IS NOT NULL;

CREATE TABLE IF NOT EXISTS recovery_tokens (
    token_hash  TEXT PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recovery_tokens_list ON recovery_tokens(list_id);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);

-- What the operator changed with scripts/admin.py. Never a token, an email
-- address or any list content. list_id is not a foreign key: the row outlives
-- a deleted list.
CREATE TABLE IF NOT EXISTS admin_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       TEXT NOT NULL,
    command  TEXT NOT NULL,
    list_id  INTEGER
);
