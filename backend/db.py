"""todo-gtd — SQLite database: connections, schema, write lock.

One database file holds every list. Each thread gets its own connection (WAL, so
readers never see a half-finished write), and every write path goes through
``transaction()``: the process-wide write lock plus ``BEGIN IMMEDIATE`` around the
whole read-check-write sequence, committed or rolled back as a unit.

# simplification: one process + global write lock; move to Postgres if one worker is not enough
# simplification: schema-at-startup plus the hand-written steps in _migrate; add a migration runner when those stop being a handful
"""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from backend.paid import caps


logger = logging.getLogger(__name__)

# The lists table's columns, shared by _SCHEMA and the rebuild in _migrate so the
# two cannot drift.
_LISTS_DDL = (
    """
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_token_hash  TEXT NOT NULL UNIQUE,   -- SHA-256 of agent_token; what a lookup matches
    -- Plain, so the web app can always show the agent link (like capture_token).
    -- Not a downgrade: a signed-in browser already reads and changes everything,
    -- and only a signed-in browser can fetch this. Nullable only because _migrate
    -- adds it to databases made before it existed; every row has one after startup.
    agent_token       TEXT,
    capture_token     TEXT NOT NULL UNIQUE,   -- plain, so the web app can display it
    tz                TEXT NOT NULL DEFAULT 'UTC',
    email             TEXT,
    -- When a link mailed to `email` was opened (signin.redeem); NULL = unconfirmed.
    -- Changing the email clears it (lists.set_email_in). Picks the caps (common.caps_for).
    email_verified_at TEXT,
    created_at        TEXT NOT NULL,
    last_used_at      TEXT,
    review_started_at TEXT,
    name              TEXT NOT NULL DEFAULT '',  -- optional; common.validate_list_name
    -- What a person says to name their account (lists.account_no_in): random, so it says
    -- nothing about how many accounts exist. _migrate adds the unique index, and fills it
    -- in on databases made before it existed: every row has one after startup.
    account_no        TEXT,
    -- Set by the operator (scripts/admin.py disable). While set, every link of
    -- the list answers as an unknown one (lists._resolve) and no browser is
    -- signed in to it (sessions.resolve); nothing is deleted.
    disabled_at       TEXT,
    -- The list's change counter (_REV_TRIGGERS): every insert or edit of one of its
    -- todos, projects or areas adds one and stamps the row. service.changes reads it.
    rev               INTEGER NOT NULL DEFAULT 0,
    -- When `rev` last moved (same triggers), as common.to_iso writes it; null until then.
    changed_at        TEXT,
    -- Raised past `rev` by scripts/restore_list.py, which removes rows: a tool that
    -- synced before that is told to start over (service.changes `reset`).
    sync_floor        INTEGER NOT NULL DEFAULT 0,
    -- The apps (apps.py keys) turned on for this account, as a JSON array: the
    -- agent link offers only these (lists.apps_on). Creating the list on the host of an
    -- app, or signing in there, turns that app on; Apps under Connect toggles them.
    apps              TEXT NOT NULL DEFAULT '["todo"]',
    -- Projects' sample projects (samples.py): NULL never made, 'on' shown, 'off' put away.
    projects_sample   TEXT,
"""
    + caps.LISTS_DDL
)
_LISTS_INDEX = "CREATE INDEX IF NOT EXISTS idx_lists_email ON lists(email) WHERE email IS NOT NULL"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS lists ({_LISTS_DDL});
{_LISTS_INDEX};

-- Areas of focus: the standing parts of a life or job that projects and todos
-- hang off. Never deleted; archiving is status 'dropped'.
CREATE TABLE IF NOT EXISTS areas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    name        TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','dropped')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    rev         INTEGER NOT NULL DEFAULT 0   -- lists.rev when this row last changed
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
    updated_at  TEXT NOT NULL,
    rev         INTEGER NOT NULL DEFAULT 0   -- lists.rev when this row last changed
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
    revisit_on       TEXT,                           -- YYYY-MM-DD: hidden from the lists until then
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
    tickle_count     INTEGER NOT NULL DEFAULT 0,
    rev              INTEGER NOT NULL DEFAULT 0      -- lists.rev when this row last changed
);
CREATE INDEX IF NOT EXISTS idx_todos_list_status ON todos(list_id, status);
CREATE INDEX IF NOT EXISTS idx_todos_list_project ON todos(list_id, project_id);
CREATE INDEX IF NOT EXISTS idx_todos_list_due ON todos(list_id, due_date)
    WHERE completed_at IS NULL AND due_date IS NOT NULL;

-- Projects GTD (boards.py): a project is a board of columns of cards. Apart from
-- the todo app's GTD `projects` above. Never deleted; archiving is status 'archived'.
-- Order is a plain integer `position`, renumbered inside the moving transaction.
-- Simple Sites (sites.py): a page (HTML or Markdown) or a short link, at
-- <SITES_BASE_URL>/<name->code. The one table the person can delete rows from.
-- simplification: bodies live here, so backup, restore, admin delete and cleanup
-- work unchanged; move them to content-addressed files on the volume once the
-- table passes ~500 MB.
CREATE TABLE IF NOT EXISTS sites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    kind          TEXT NOT NULL CHECK(kind IN ('page','link')),
    code          TEXT NOT NULL UNIQUE,      -- 10 letters and digits: the address
    name          TEXT NOT NULL DEFAULT '',  -- '' or up to 10 of a-z 0-9 -, fixed at creation
    title         TEXT NOT NULL DEFAULT '',
    format        TEXT NOT NULL DEFAULT '' CHECK(format IN ('','html','markdown')),
    body          TEXT NOT NULL DEFAULT '',  -- a page's content
    target        TEXT NOT NULL DEFAULT '',  -- a link's address
    bytes         INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL DEFAULT 'published' CHECK(status IN ('published','unpublished')),
    source        TEXT NOT NULL DEFAULT 'ui',
    source_client TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    views         INTEGER NOT NULL DEFAULT 0,  -- step 16: opens and follows (sites.count_view)
    password_hash TEXT NOT NULL DEFAULT '',    -- step 17: a locked page's (sites.lock); never served
    note          TEXT NOT NULL DEFAULT '',    -- step 18: the owner's private note (who it is for)
    folder        TEXT NOT NULL DEFAULT '',    -- step 18: the folder it is filed in, or none
    data          TEXT NOT NULL DEFAULT '',
    data_read_at  TEXT,
    data_bytes    INTEGER NOT NULL DEFAULT 0,
    data_records  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sites_list ON sites(list_id, kind);

CREATE TABLE IF NOT EXISTS site_blobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES lists(id),
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('pending','active','deleting')),
    put_until TEXT NOT NULL,
    unref_since TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_site_blobs_hash ON site_blobs(list_id, sha256)
    WHERE status IN ('pending','active');
CREATE INDEX IF NOT EXISTS idx_site_blobs_list ON site_blobs(list_id);
CREATE TABLE IF NOT EXISTS site_files (
    site_id INTEGER NOT NULL REFERENCES sites(id),
    list_id INTEGER NOT NULL REFERENCES lists(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    content_type TEXT NOT NULL,
    PRIMARY KEY(site_id, path)
);
CREATE INDEX IF NOT EXISTS idx_site_files_hash ON site_files(list_id, sha256);

CREATE TABLE IF NOT EXISTS site_data (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id    INTEGER NOT NULL REFERENCES sites(id),
    list_id    INTEGER NOT NULL REFERENCES lists(id),
    by         TEXT NOT NULL CHECK(by IN ('visitor','owner')),
    created_at TEXT NOT NULL,
    body       TEXT NOT NULL,
    bytes      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_site_data_site ON site_data(site_id, id);

CREATE TABLE IF NOT EXISTS site_data_fields (
    record_id INTEGER NOT NULL REFERENCES site_data(id),
    site_id   INTEGER NOT NULL,
    list_id   INTEGER NOT NULL REFERENCES lists(id),
    key       TEXT NOT NULL,
    value     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_site_data_fields ON site_data_fields(site_id, key, value, record_id);

CREATE TABLE IF NOT EXISTS boards (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    name        TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- _BOARD_COLUMNS (added to an older database by _migrate step 8):
    dock        TEXT,                        -- JSON: the project's tools; NULL = all, in order
    pinned      INTEGER NOT NULL DEFAULT 0,  -- shown first on Home
    starts_on   TEXT,                        -- YYYY-MM-DD: the project's dates, for the Lineup
    ends_on     TEXT,
    template    INTEGER NOT NULL DEFAULT 0,  -- a project template (step 11): new projects copy it
    folder      TEXT NOT NULL DEFAULT '',    -- step 13: the Home folder it sits in (Basecamp 5's), or none
    sample      INTEGER NOT NULL DEFAULT 0   -- step 14: one of the sample projects (samples.py)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_boards_list_name ON boards(list_id, lower(name));

CREATE TABLE IF NOT EXISTS board_columns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    board_id    INTEGER NOT NULL REFERENCES boards(id),
    name        TEXT NOT NULL,
    position    INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- _CARD_TABLE_COLUMNS["board_columns"] (added to an older database by step 9):
    kind        TEXT NOT NULL DEFAULT 'column',  -- triage, not_now, column or done (Basecamp's)
    color       TEXT NOT NULL DEFAULT '',
    has_on_hold INTEGER NOT NULL DEFAULT 0,      -- the column has an On Hold section
    card_limit  INTEGER,                         -- Trello's soft list limit: warns, never refuses
    description TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_board_columns_board ON board_columns(board_id, position);

CREATE TABLE IF NOT EXISTS cards (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id        INTEGER NOT NULL REFERENCES lists(id),
    board_id       INTEGER NOT NULL REFERENCES boards(id),
    column_id      INTEGER NOT NULL REFERENCES board_columns(id),
    title          TEXT NOT NULL,
    notes          TEXT NOT NULL DEFAULT '',
    due_date       TEXT,                           -- YYYY-MM-DD
    position       INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    source         TEXT NOT NULL DEFAULT 'agent' CHECK(source IN ('ui','agent')),
    source_client  TEXT,
    -- One more on every change to the card: an edit sent with an older version is
    -- refused (409), so a browser cannot overwrite what an agent just wrote.
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    -- _CARD_TABLE_COLUMNS["cards"] (added to an older database by step 9):
    assignee_ids   TEXT NOT NULL DEFAULT '[]',     -- JSON array of people ids
    label_ids      TEXT NOT NULL DEFAULT '[]',     -- JSON array of the project's label ids
    starts_on      TEXT,                           -- YYYY-MM-DD: with due_date, a range
    cover          TEXT NOT NULL DEFAULT '',       -- a colour across the card's top
    on_hold        INTEGER NOT NULL DEFAULT 0,     -- in its column's On Hold section
    completed_at   TEXT,                           -- set while the card is in Done
    -- step 11:
    repeat         TEXT,                           -- recordings.REPEATS: completing it adds the next
    template       INTEGER NOT NULL DEFAULT 0      -- a card template: new cards copy it
);
CREATE INDEX IF NOT EXISTS idx_cards_column ON cards(column_id, position);

-- A project's labels (Trello's), shared by its cards. Never deleted: archived.
CREATE TABLE IF NOT EXISTS labels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    board_id    INTEGER NOT NULL REFERENCES boards(id),
    name        TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_labels_board ON labels(board_id, position);
CREATE INDEX IF NOT EXISTS idx_cards_list ON cards(list_id, status);

-- Projects GTD's people (people.py): who wrote a thing and who it is for. One 'me'
-- per account, one 'ai' per AI tool that has written (named by its client), and
-- anyone the person adds by name ('person'; they do not sign in). Never deleted.
CREATE TABLE IF NOT EXISTS people (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    kind        TEXT NOT NULL CHECK(kind IN ('me','person','ai')),
    name        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',   -- what they do: "Designer", "Contractor"
    color       TEXT NOT NULL DEFAULT '',   -- the avatar's colour
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    -- New for you's line: what others did after this is unread ('me' only).
    read_at     TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- _PEOPLE_COLUMNS (added to an older database by step 10):
    up_next     TEXT NOT NULL DEFAULT '[]'   -- My Tasks' private Up Next: [["r"|"c", id], …]
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_people_list_name ON people(list_id, kind, lower(name));

-- Everything in a project but its card table (recordings.py), as Basecamp models
-- it: a message, a to-do list and its to-dos, a document, a comment, ... one row
-- each, with a `type`. A row sits under a project, and under its parent (a to-do
-- under its list) or a card (a card's comment or step). Never deleted: archived
-- and trashed are statuses, and both come back.
CREATE TABLE IF NOT EXISTS recordings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id        INTEGER NOT NULL REFERENCES lists(id),
    board_id       INTEGER NOT NULL REFERENCES boards(id),
    parent_id      INTEGER REFERENCES recordings(id),
    card_id        INTEGER REFERENCES cards(id),
    type           TEXT NOT NULL,
    title          TEXT NOT NULL DEFAULT '',
    body           TEXT NOT NULL DEFAULT '',          -- markdown
    status         TEXT NOT NULL DEFAULT 'active'
                   CHECK(status IN ('active','archived','trashed','drafted')),
    position       INTEGER NOT NULL DEFAULT 0,
    category       TEXT NOT NULL DEFAULT '',          -- a message's kind: "Announcement"
    color          TEXT NOT NULL DEFAULT '',
    starts_on      TEXT,                              -- YYYY-MM-DD
    due_on         TEXT,                              -- YYYY-MM-DD
    completed_at   TEXT,
    completer_id   INTEGER REFERENCES people(id),
    assignee_ids   TEXT NOT NULL DEFAULT '[]',        -- JSON array of people ids
    data           TEXT NOT NULL DEFAULT '{{}}',      -- the type's extras (JSON)
    creator_id     INTEGER REFERENCES people(id),
    source         TEXT NOT NULL DEFAULT 'ui' CHECK(source IN ('ui','agent')),
    source_client  TEXT,
    -- One more on every change; an edit naming an older one is refused (409).
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recordings_board ON recordings(board_id, type, status);
CREATE INDEX IF NOT EXISTS idx_recordings_parent ON recordings(parent_id, position);
CREATE INDEX IF NOT EXISTS idx_recordings_card ON recordings(card_id);
CREATE INDEX IF NOT EXISTS idx_recordings_list ON recordings(list_id, type, status);

-- Boosts: a few characters or an emoji on a recording or a card, Basecamp's
-- small reaction. Taking one back sets status 'removed'.
CREATE TABLE IF NOT EXISTS boosts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    recording_id  INTEGER REFERENCES recordings(id),
    card_id       INTEGER REFERENCES cards(id),
    content       TEXT NOT NULL,
    booster_id    INTEGER NOT NULL REFERENCES people(id),
    status        TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','removed')),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_boosts_recording ON boosts(recording_id);
CREATE INDEX IF NOT EXISTS idx_boosts_card ON boosts(card_id);

-- The activity trail: one row per thing someone did in a project, newest last.
-- Activity, Hey! and a project's latest activity read it. `detail` is a short
-- line ("moved it to Doing"), never a token, link or email address.
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    board_id      INTEGER NOT NULL REFERENCES boards(id),
    recording_id  INTEGER REFERENCES recordings(id),
    card_id       INTEGER REFERENCES cards(id),
    action        TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    creator_id    INTEGER REFERENCES people(id),
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_list ON events(list_id, id);
CREATE INDEX IF NOT EXISTS idx_events_board ON events(board_id, id);

-- New for you, per item ('me' only): read up to read_at, marked unread by hand,
-- or bubbled up to come back at bubble_up_at. An item is a recording, a card, or
-- a project (for what was done to the project itself).
CREATE TABLE IF NOT EXISTS readings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    board_id      INTEGER REFERENCES boards(id),
    recording_id  INTEGER REFERENCES recordings(id),
    card_id       INTEGER REFERENCES cards(id),
    read_at       TEXT,
    unread        INTEGER NOT NULL DEFAULT 0,
    bubble_up_at  TEXT,
    muted         INTEGER NOT NULL DEFAULT 0,  -- step 12: "Don't notify me" (an item, a card, a whole project)
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_readings_item
    ON readings(list_id, COALESCE(recording_id, 0), COALESCE(card_id, 0), COALESCE(board_id, 0));

-- Bookmarks: a recording, a card or a project kept under My Bookmarks.
CREATE TABLE IF NOT EXISTS bookmarks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    board_id      INTEGER REFERENCES boards(id),
    recording_id  INTEGER REFERENCES recordings(id),
    card_id       INTEGER REFERENCES cards(id),
    status        TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','removed')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_list ON bookmarks(list_id, status);

-- Card Table automation (automation.py), Trello's: a rule runs its actions on a card
-- when something happens to it; a card button on one card when pressed; a board
-- button on every card in its column. Archived, never deleted.
CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id      INTEGER NOT NULL REFERENCES lists(id),
    board_id     INTEGER NOT NULL REFERENCES boards(id),
    kind         TEXT NOT NULL CHECK(kind IN ('rule', 'card_button', 'board_button')),
    name         TEXT NOT NULL DEFAULT '',
    trigger      TEXT NOT NULL DEFAULT '{{}}', -- JSON: a rule's "when", a board button's column
    actions      TEXT NOT NULL DEFAULT '[]',   -- JSON: what it does, in order
    status       TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    position     INTEGER NOT NULL DEFAULT 0,
    runs         INTEGER NOT NULL DEFAULT 0,
    last_run_at  TEXT,
    last_error   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rules_board ON rules(board_id, status);
-- A due-date rule acts once per card per due date.
CREATE TABLE IF NOT EXISTS rule_fired (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    rule_id     INTEGER NOT NULL REFERENCES rules(id),
    card_id     INTEGER NOT NULL REFERENCES cards(id),
    key         TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_rule_fired ON rule_fired(rule_id, card_id, key);

-- Notes GTD (notes.py): Keep-style notes holding markdown. Never deleted; archiving
-- is status 'archived'. `tags` is derived from the body's #hashtags on every write.
CREATE TABLE IF NOT EXISTS notes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id        INTEGER NOT NULL REFERENCES lists(id),
    title          TEXT NOT NULL DEFAULT '',
    body           TEXT NOT NULL DEFAULT '',
    tags           TEXT NOT NULL DEFAULT '[]',          -- JSON array, from the body
    color          TEXT NOT NULL DEFAULT '',
    pinned         INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    source         TEXT NOT NULL DEFAULT 'ui' CHECK(source IN ('ui','agent')),
    source_client  TEXT,
    -- The AI tool behind the last write; NULL when it was made in the app.
    edited_by      TEXT,
    -- One more on every write: a save naming an older version is refused (409).
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_list ON notes(list_id, status, updated_at);

-- Common Brain (brain.py): one account's second brain, shared by every AI it connects.
-- Memories are short bullets every AI loads; pages are Markdown or HTML at a path
-- (people/maya, daily/2026-10-24). `created_by` / `updated_by` name the AI tool, or
-- 'you' for the person in the app. Every write also appends the item's whole new state
-- to brain_versions, the history, the what-changed feed and each AI's catch-up. The one
-- hard delete is the person's Forget (brain.forget), which removes an item with its history.
CREATE TABLE IF NOT EXISTS brains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES lists(id),
    name TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    rules TEXT NOT NULL DEFAULT '[]',
    ai_access TEXT NOT NULL DEFAULT 'write' CHECK(ai_access IN ('write','read','inbox')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    settled_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(list_id, folder)
);
CREATE TABLE IF NOT EXISTS brain_memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    text        TEXT NOT NULL,
    locked      INTEGER NOT NULL DEFAULT 0,     -- only the person changes a locked memory
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    version     INTEGER NOT NULL DEFAULT 1,
    created_by  TEXT NOT NULL,
    updated_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_memories_list ON brain_memories(list_id, status);
CREATE TABLE IF NOT EXISTS brain_pages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    path        TEXT NOT NULL,
    title       TEXT NOT NULL DEFAULT '',
    format      TEXT NOT NULL DEFAULT 'markdown' CHECK(format IN ('markdown','html')),
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    version     INTEGER NOT NULL DEFAULT 1,
    created_by  TEXT NOT NULL,
    updated_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    -- `confidential: true` in the body's frontmatter (brain._front), set on every write:
    -- a folder-limited program key never sees the page.
    confidential INTEGER NOT NULL DEFAULT 0,
    UNIQUE(brain_id, path)
);
CREATE TABLE IF NOT EXISTS brain_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    kind        TEXT NOT NULL CHECK(kind IN ('memory','page')),
    item_id     INTEGER NOT NULL,
    version     INTEGER NOT NULL,
    action      TEXT NOT NULL,                  -- added, edited, locked, archived, restored, …
    by          TEXT NOT NULL,
    at          TEXT NOT NULL,
    -- The item's whole state after the change: a memory's text, or a page's fields.
    text        TEXT NOT NULL DEFAULT '',
    path        TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    format      TEXT NOT NULL DEFAULT '',
    locked      INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'active',
    pass        TEXT NOT NULL DEFAULT '',
    reason      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_brain_versions_item ON brain_versions(list_id, kind, item_id, version);
CREATE INDEX IF NOT EXISTS idx_brain_versions_at ON brain_versions(list_id, at);
-- Each AI tool that has visited the brain: its catch-up starts at last_seen_at, and
-- onboarded_at says it has run the set-up once.
CREATE TABLE IF NOT EXISTS brain_ais (
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    name          TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    onboarded_at  TEXT,
    PRIMARY KEY (brain_id, name)
);
-- What an AI searched the brain for and did not find: the curator's demand signal.
CREATE TABLE IF NOT EXISTS brain_misses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    query       TEXT NOT NULL,
    by          TEXT NOT NULL,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_misses_list ON brain_misses(list_id, at);
-- Brain search's full-text index over pages and memories: _migrate step 22 (_BRAIN_FTS).

-- Common Brain's files (files.py), one row per version; the bytes are in the object store
-- (objectstore.py) at `object_key`, `<list_id>/<random>`, written once. An upload is staged at
-- `staging_key` while pending and finalizing. Many rows may share a path: the replaced and
-- archived versions, and pending replacements of the one active file. `abandoned` and
-- `forgotten` are tombstones: their bytes are still to delete, and then the row goes.
-- `sha256` (hex) is the content's identity, checked by the store at upload; `import_source`
-- names the import that made the file, NULL for an upload.
CREATE TABLE IF NOT EXISTS brain_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    brain_id    INTEGER NOT NULL REFERENCES brains(id),
    path          TEXT NOT NULL,
    object_key    TEXT NOT NULL UNIQUE,
    staging_key   TEXT,                 -- NULL once the sweeper has deleted it for good
    size          INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    import_source TEXT,
    status        TEXT NOT NULL CHECK(status IN ('pending','finalizing','active','archived',
                                                 'replaced','abandoned','forgotten')),
    created_by    TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_files_list ON brain_files(list_id, path);
CREATE INDEX IF NOT EXISTS idx_brain_files_status ON brain_files(status, updated_at);

-- Program keys (keys.py), stored only as SHA-256 hashes; `last4` is what the app shows.
-- `folders` is a JSON list. Revoking stamps revoked_at; the row stays.
CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id      INTEGER NOT NULL REFERENCES lists(id),
    name         TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    last4        TEXT NOT NULL,
    apps         TEXT NOT NULL CHECK(apps IN ('brain','all')),
    access       TEXT NOT NULL CHECK(access IN ('read','write')),
    folders      TEXT NOT NULL DEFAULT '[]',
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_keys_list ON api_keys(list_id);

-- One row per signed-in browser (sessions.py). The cookie holds the token; this
-- holds only its SHA-256 hash. At most sessions.MAX_PER_LIST rows per list.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash    TEXT PRIMARY KEY,
    list_id       INTEGER NOT NULL REFERENCES lists(id),
    created_at    TEXT NOT NULL,
    last_used_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_list ON sessions(list_id);

-- One-hour, single-use sign-in links (signin.py), stored only as SHA-256 hashes.
-- mailed_to is the address a mailed link went to; NULL for one shown in the app.
CREATE TABLE IF NOT EXISTS signin_tokens (
    token_hash  TEXT PRIMARY KEY,
    list_id     INTEGER NOT NULL REFERENCES lists(id),
    expires_at  TEXT NOT NULL,
    mailed_to   TEXT
);
CREATE INDEX IF NOT EXISTS idx_signin_tokens_list ON signin_tokens(list_id);

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
"""


# The database's own clock, in common.to_iso's format. A trigger cannot read
# common.utcnow, and a function registered on the app's connections would make
# every write from any other connection (the sqlite3 shell, a restore) fail.
NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


def _rev_triggers() -> list[str]:
    """The change counter, kept by the database so no write path can forget it:
    an insert or an update of a todo, project or area adds one to its list's
    `rev`, stamps the list's `changed_at`, and stamps the row with the new
    number. Created in _migrate, once the columns exist. The WHEN stops the
    stamp from counting as a change; a brain tickle (the only thing that moves
    tickle_count) is not an edit and is not counted either."""
    out = []
    for table in ("todos", "projects", "areas"):
        bump = (
            f"UPDATE lists SET rev = rev + 1, changed_at = {NOW_SQL} "
            f"WHERE id = NEW.list_id; "
            f"UPDATE {table} SET rev = (SELECT rev FROM lists WHERE id = NEW.list_id) "
            f"WHERE id = NEW.id;"
        )
        quiet = " AND NEW.tickle_count = OLD.tickle_count" if table == "todos" else ""
        out.append(f"CREATE TRIGGER IF NOT EXISTS {table}_rev_insert AFTER INSERT ON {table} BEGIN {bump} END")
        out.append(
            f"CREATE TRIGGER IF NOT EXISTS {table}_rev_update AFTER UPDATE ON {table} "
            f"WHEN NEW.rev = OLD.rev{quiet} BEGIN {bump} END"
        )
    return out


_path: Path | None = None
_generation = 0  # bumped by close_db so threads drop stale connections
_local = threading.local()
_connections: list[sqlite3.Connection] = []
_state_lock = threading.Lock()
_write_lock = threading.Lock()


def db_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "data")) / "todo.db"


def _connect() -> sqlite3.Connection:
    # isolation_level=None: no implicit transactions — transaction() issues BEGIN
    # IMMEDIATE itself, and a bare read sees only committed data.
    conn = sqlite3.connect(str(_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def init_db() -> None:
    """Open the database under DATA_DIR and create the schema if missing."""
    global _path
    close_db()
    path = db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        probe = path.parent / ".write-test"
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as e:
        # Refuse to start: a database that cannot be written (or that lands on a
        # container's throwaway disk) loses every list on the next deploy.
        raise RuntimeError(
            f"DATA_DIR ({path.parent.resolve()}) is not writable: {e}. "
            "Mount a persistent volume there, or point DATA_DIR at a writable directory."
        ) from None
    _path = path
    conn = _connect()
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.close()
    logger.info("Database initialized at %s", path)


def _migrate(conn: sqlite3.Connection) -> None:
    """Schema changes to a database made by an older version. Each step checks
    whether it is needed, so running it at every startup is safe.

    1. (the first change) `lists.agent_token`: the agent token used to be stored
       only as a hash and shown once. A list made before the column existed gets
       a FRESH agent token — its old one cannot be recovered from the hash, so
       the old agent link stops working and the web app shows the new one.
    2. `lists.name` (the optional list name) and `lists.disabled_at` (the
       operator's off switch): plain added columns, empty on every existing list.
    3. The web link is gone: browsers sign in with a session cookie. Drop
       `recovery_tokens` (one-hour tokens, nothing of value) and rebuild `lists`
       without `web_token_hash` (_rebuild_lists). Nobody is signed in afterwards;
       the self-hoster gets back in once with RESET_CODE or `admin.py signin-link`.
    4. `lists.email_verified_at`: a plain added column. Every existing email
       starts unconfirmed.
    5. `rev` on lists, todos, projects and areas, and the triggers that keep it
       (_rev_triggers). Every existing row gets its own number, so a first
       sync (since 0) pages through all of it.
    6. `lists.changed_at`: a plain added column, and the triggers made again so
       they stamp it. A list reads null until its next change.
    7. `lists.apps`: every existing account has todo on and nothing else (a new
       app is off until turned on), except Projects for an account that already
       has a board: its board tools reached every link before the switch existed.
    8. `boards` gains Basecamp's project fields (_BOARD_COLUMNS): plain added
       columns, empty on every existing board (a NULL dock means the card table alone).
    9. Card tables take Basecamp's shape (_card_table_kinds): columns and cards gain
       their added fields (_CARD_TABLE_COLUMNS), and each board made before then has
       its rightmost column become Done (its name kept, its cards completed) and gets
       an empty Triage and Not now. A board with a Done column is left alone.
    10. `people.up_next` (_PEOPLE_COLUMNS): a plain added column, an empty Up Next.
    11. `boards.template`, `cards.repeat` and `cards.template` (in _BOARD_COLUMNS and
        _CARD_TABLE_COLUMNS): plain added columns, off on every existing row.
    12. `readings.muted`: a plain added column, off on every existing row (nothing muted).
    13. `boards.folder` (in _BOARD_COLUMNS): a plain added column, empty on every existing
        board (no folder).
    14. `boards.sample` (in _BOARD_COLUMNS) and `lists.projects_sample`: plain added
        columns; no existing board is a sample and no existing account has had them.
    15. Paid fields on lists (paid.caps.COLUMNS): plain added columns; no
        existing account has a subscription.
    16. `sites.views`: a plain added column; every existing page and link starts at 0.
    17. `sites.password_hash`: a plain added column; no existing page is locked.
    18. `sites.note` and `sites.folder`, and the grant expiry (in paid.caps.COLUMNS):
        plain added columns; nothing has a note, a folder or a grant yet.
    19. `lists.account_no`: an added column, its unique index (here, not in _SCHEMA, which
        an older database meets without the column) and a random number for every list.
    20. The grant kind (in paid.caps.COLUMNS): a plain added column with the original default.
    21. `brain_pages.confidential`, backfilled from each page's frontmatter (brain.confidential);
        every write sets it from then on. (The program keys' `api_keys` is a new table.)
    22. Brain search's full-text index (_BRAIN_FTS): two external-content FTS5 tables over
        brain_pages and brain_memories, the triggers that keep them current, and one
        'rebuild' that indexes what is already there. Here, not in _SCHEMA, so the step
        knows when the index is new.
    23. Common Brain's files: `brain_files` is a new table (in _SCHEMA, with its partial
        unique index over the active rows); nothing here.
    24. `brain_versions.pass` and `reason`: plain added columns for grouped writes.
    25. Sites page data: mode, last owner fetch and usage counters; records and indexed
        fields are new tables in _SCHEMA.
    26. Brains under accounts: rebuild the six content tables with brain_id, preserving
        ids, sequences and FTS rowids; keep account indexes for caps and administration.
    27. Ordered brain grants on main links and keys, and named staff links (kind).
    28. Isolated Sites hosts, operator suspensions, expiry and legacy data paths.
    29. Sites file manifests and blob inventory (_SCHEMA), layout, size and client refs.
    30. Device connection codes and Sites short names with their lapse grace.
    """
    from backend import brain, lists, sites  # here, not at the top: lists imports this module

    # Off for the rebuild: with it on, DROP TABLE lists would first delete every
    # row that points at a list. It is a no-op inside a transaction, so it goes
    # before BEGIN, and back on after COMMIT or ROLLBACK.
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Read under the write lock: scripts/admin.py also runs this, in a second process.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(lists)")}
            if "agent_token" not in columns:
                conn.execute("ALTER TABLE lists ADD COLUMN agent_token TEXT")
            if "name" not in columns:
                conn.execute("ALTER TABLE lists ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            if "disabled_at" not in columns:
                conn.execute("ALTER TABLE lists ADD COLUMN disabled_at TEXT")
            if "email_verified_at" not in columns:
                conn.execute("ALTER TABLE lists ADD COLUMN email_verified_at TEXT")
            if "rev" not in columns:
                for table in ("lists", "areas", "projects", "todos"):
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN rev INTEGER NOT NULL DEFAULT 0")
                # Number what exists, each row its own rev (service.changes pages by it),
                # parents first so a first sync meets an area before its projects.
                last: dict[int, int] = {}
                for table in ("areas", "projects", "todos"):
                    for row in conn.execute(f"SELECT id, list_id FROM {table} ORDER BY id").fetchall():
                        last[row["list_id"]] = last.get(row["list_id"], 0) + 1
                        conn.execute(f"UPDATE {table} SET rev = ? WHERE id = ?", (last[row["list_id"]], row["id"]))
                conn.executemany(
                    "UPDATE lists SET rev = ? WHERE id = ?", [(rev, list_id) for list_id, rev in last.items()]
                )
            for row in conn.execute("SELECT id FROM lists WHERE agent_token IS NULL").fetchall():
                token = lists.mint_token()
                conn.execute(
                    "UPDATE lists SET agent_token = ?, agent_token_hash = ? WHERE id = ?",
                    (token, lists.hash_token(token), row["id"]),
                )
            conn.execute("DROP TABLE IF EXISTS recovery_tokens")
            if "web_token_hash" in columns:
                _rebuild_lists(conn)
            if "sync_floor" not in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}:
                conn.execute("ALTER TABLE lists ADD COLUMN sync_floor INTEGER NOT NULL DEFAULT 0")
            if "changed_at" not in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}:
                conn.execute("ALTER TABLE lists ADD COLUMN changed_at TEXT")
                # CREATE TRIGGER IF NOT EXISTS keeps an old trigger as it was.
                for table in ("todos", "projects", "areas"):
                    for event in ("insert", "update"):
                        conn.execute(f"DROP TRIGGER IF EXISTS {table}_rev_{event}")
            have = {r["name"] for r in conn.execute("PRAGMA table_info(boards)")}
            for name, ddl in _BOARD_COLUMNS.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE boards ADD COLUMN {name} {ddl}")
            _card_table_kinds(conn)
            have = {r["name"] for r in conn.execute("PRAGMA table_info(people)")}
            for name, ddl in _PEOPLE_COLUMNS.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE people ADD COLUMN {name} {ddl}")
            if "muted" not in {r["name"] for r in conn.execute("PRAGMA table_info(readings)")}:
                conn.execute("ALTER TABLE readings ADD COLUMN muted INTEGER NOT NULL DEFAULT 0")
            if "apps" not in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}:
                conn.execute("""ALTER TABLE lists ADD COLUMN apps TEXT NOT NULL DEFAULT '["todo"]'""")
                conn.execute(
                    """UPDATE lists SET apps = '["todo", "projects"]' """
                    "WHERE id IN (SELECT list_id FROM boards)"
                )
            if "projects_sample" not in {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}:
                conn.execute("ALTER TABLE lists ADD COLUMN projects_sample TEXT")
            have = {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}
            for name, ddl in caps.COLUMNS.items():
                if name not in have:
                    conn.execute(f"ALTER TABLE lists ADD COLUMN {name} {ddl}")
            if "account_no" not in have:
                conn.execute("ALTER TABLE lists ADD COLUMN account_no TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lists_account_no ON lists(account_no)")
            for row in conn.execute("SELECT id FROM lists WHERE account_no IS NULL").fetchall():
                conn.execute("UPDATE lists SET account_no = ? WHERE id = ?", (lists.account_no_in(conn), row["id"]))
            if "views" not in {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}:
                conn.execute("ALTER TABLE sites ADD COLUMN views INTEGER NOT NULL DEFAULT 0")
            if "password_hash" not in {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}:
                conn.execute("ALTER TABLE sites ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''")
            have = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
            for name in ("note", "folder"):
                if name not in have:
                    conn.execute(f"ALTER TABLE sites ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            if "confidential" not in {r["name"] for r in conn.execute("PRAGMA table_info(brain_pages)")}:
                conn.execute("ALTER TABLE brain_pages ADD COLUMN confidential INTEGER NOT NULL DEFAULT 0")
                conn.executemany(
                    "UPDATE brain_pages SET confidential = 1 WHERE id = ?",
                    [
                        (r["id"],)
                        for r in conn.execute("SELECT id, body FROM brain_pages").fetchall()
                        if brain.confidential(r["body"])
                    ],
                )
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'brain_pages_fts'").fetchone():
                for ddl in (*_BRAIN_FTS_TABLES, *_BRAIN_FTS_TRIGGERS):
                    conn.execute(ddl)
                for table in ("brain_pages_fts", "brain_memories_fts"):
                    conn.execute(f"INSERT INTO {table}({table}) VALUES ('rebuild')")
            have = {r["name"] for r in conn.execute("PRAGMA table_info(brain_versions)")}
            for name in ("pass", "reason"):
                if name not in have:
                    conn.execute(f"ALTER TABLE brain_versions ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            have = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
            for name, declaration in (
                ("data", "TEXT NOT NULL DEFAULT ''"),
                ("data_read_at", "TEXT"),
                ("data_bytes", "INTEGER NOT NULL DEFAULT 0"),
                ("data_records", "INTEGER NOT NULL DEFAULT 0"),
            ):
                if name not in have:
                    conn.execute(f"ALTER TABLE sites ADD COLUMN {name} {declaration}")
            _rebuild_brains(conn)
            # Step 27: backfill only when adding the column; an empty grant stays empty.
            for table, column in (("lists", "link_brains"), ("api_keys", "brains")):
                if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT '[]'")
                    owner = "id" if table == "lists" else "list_id"
                    conn.execute(
                        f"UPDATE {table} SET {column} = json_array((SELECT id FROM brains "
                        f"WHERE brains.list_id = {table}.{owner} ORDER BY id LIMIT 1))"
                    )
            if "kind" not in {r["name"] for r in conn.execute("PRAGMA table_info(api_keys)")}:
                conn.execute(
                    "ALTER TABLE api_keys ADD COLUMN kind TEXT NOT NULL DEFAULT 'key' CHECK(kind IN ('key','link'))"
                )
            # Step 28: keep legacy data URLs until the stored content is replaced.
            have = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
            for name, declaration in (
                ("host", "TEXT"),
                ("suspended_at", "TEXT"),
                ("expires_at", "TEXT"),
                ("legacy_path", "INTEGER DEFAULT 0"),
            ):
                if name not in have:
                    conn.execute(f"ALTER TABLE sites ADD COLUMN {name} {declaration}")
            if "legacy_path" not in have:
                conn.execute(f"UPDATE sites SET legacy_path = 1 WHERE {sites.LEGACY_PATH_SQL}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_host ON sites(host) WHERE host IS NOT NULL")
            for row in conn.execute("SELECT id, name FROM sites WHERE kind = 'page' AND host IS NULL").fetchall():
                while True:
                    try:
                        conn.execute(
                            "UPDATE sites SET host = ? WHERE id = ?", (sites._new_host(row["name"]), row["id"])
                        )
                        break
                    except sqlite3.IntegrityError as exc:
                        if "sites.host" not in str(exc):
                            raise
            # Step 29: body bytes are backfilled only on the first run.
            have = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
            for name, declaration in (
                ("layout", "TEXT NOT NULL DEFAULT 'body' CHECK(layout IN ('body','files'))"),
                ("size", "INTEGER NOT NULL DEFAULT 0"),
                ("client_ref", "TEXT"),
            ):
                if name not in have:
                    conn.execute(f"ALTER TABLE sites ADD COLUMN {name} {declaration}")
            # Every start, not only the first: the old revision may write bytes during a rollout.
            conn.execute("UPDATE sites SET size = bytes WHERE layout = 'body' AND size != bytes")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_client_ref "
                "ON sites(list_id, client_ref) WHERE client_ref IS NOT NULL"
            )
            # Step 30: existing sites retain their expiry and have no short name.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS connect_codes ("
                "device_hash TEXT PRIMARY KEY, user_code TEXT NOT NULL UNIQUE, "
                "list_id INTEGER REFERENCES lists(id), created_list_id INTEGER, approved_at TEXT, "
                "created_at TEXT NOT NULL, expires_at TEXT NOT NULL)"
            )
            have = {r["name"] for r in conn.execute("PRAGMA table_info(sites)")}
            for name in ("short_name", "short_grace_until"):
                if name not in have:
                    conn.execute(f"ALTER TABLE sites ADD COLUMN {name} TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_sites_short_name "
                "ON sites(short_name) WHERE short_name IS NOT NULL"
            )
            # After the rebuild: SQLite refuses to drop a table a trigger names.
            for trigger in _rev_triggers():
                conn.execute(trigger)
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _fts(table: str, cols: tuple[str, ...]) -> list[str]:
    """An external-content FTS5 index over `table` (rowid = its id), and the triggers
    that keep it current: SQLite's own recipe, so no write path can forget it. An
    update re-indexes only when an indexed column changes."""
    fts, names = f"{table}_fts", ", ".join(cols)
    new, old = ", ".join(f"new.{c}" for c in cols), ", ".join(f"old.{c}" for c in cols)
    delete = f"INSERT INTO {fts}({fts}, rowid, {names}) "
    return [
        f"CREATE VIRTUAL TABLE {fts} USING fts5({names}, content='{table}', content_rowid='id', "
        "tokenize='porter unicode61 remove_diacritics 2')",
        f"CREATE TRIGGER {fts}_insert AFTER INSERT ON {table} BEGIN "
        f"INSERT INTO {fts}(rowid, {names}) VALUES (new.id, {new}); END",
        f"CREATE TRIGGER {fts}_delete AFTER DELETE ON {table} BEGIN {delete}VALUES ('delete', old.id, {old}); END",
        f"CREATE TRIGGER {fts}_update AFTER UPDATE OF {names} ON {table} BEGIN "
        f"{delete}VALUES ('delete', old.id, {old}); "
        f"INSERT INTO {fts}(rowid, {names}) VALUES (new.id, {new}); END",
    ]


# Brain search's index (step 22; brain.search reads it).
_BRAIN_FTS_TABLES = [
    _fts(t, c)[0] for t, c in (("brain_pages", ("path", "title", "body")), ("brain_memories", ("text",)))
]
_BRAIN_FTS_TRIGGERS = [
    ddl
    for t, c in (("brain_pages", ("path", "title", "body")), ("brain_memories", ("text",)))
    for ddl in _fts(t, c)[1:]
]


def _rebuild_brains(conn: sqlite3.Connection) -> None:
    """Step 26, inside _migrate's transaction with foreign keys off. As in
    _rebuild_lists, copy before dropping and preserve AUTOINCREMENT high-water marks.
    FTS tables stay: content ids (and therefore their indexed rowids) never change.
    """
    conn.execute(
        "INSERT INTO brains (list_id, folder, created_at, updated_at) "
        "SELECT id, 'brain', created_at, created_at FROM lists "
        "WHERE NOT EXISTS (SELECT 1 FROM brains WHERE brains.list_id = lists.id)"
    )
    tables = ("brain_memories", "brain_pages", "brain_versions", "brain_ais", "brain_misses", "brain_files")
    rebuilt = []
    for table in tables:
        old = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
        if "brain_id" in old:
            continue
        rebuilt.append(table)
        row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
        high = row["seq"] if row else 0
        # The final table declaration is also what fresh databases use.
        ddl = _SCHEMA.split(f"CREATE TABLE IF NOT EXISTS {table} (", 1)[1].split(";", 1)[0]
        conn.execute(f"CREATE TABLE {table}_new (" + ddl)
        cols = ", ".join(old)
        selected = ", ".join(f"old.{c}" for c in old)
        conn.execute(
            f"INSERT INTO {table}_new ({cols}, brain_id) SELECT {selected}, "
            f"(SELECT id FROM brains WHERE list_id = old.list_id ORDER BY id LIMIT 1) FROM {table} old"
        )
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        if table != "brain_ais":
            top = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            conn.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))
            conn.execute("INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)", (table, max(high, top)))
    # Recreate account indexes lost in a rebuild, and add the brain gates separately:
    # _SCHEMA runs before migrations, when existing tables may still lack brain_id.
    for table, suffix, cols in (
        ("brain_memories", "list", "list_id, status"),
        ("brain_pages", "list", "list_id, status"),
        ("brain_versions", "item", "list_id, kind, item_id, version"),
        ("brain_versions", "at", "list_id, at"),
        ("brain_ais", "list", "list_id, name"),
        ("brain_misses", "list", "list_id, at"),
        ("brain_files", "list", "list_id, path"),
        ("brain_files", "account_status", "list_id, status"),
        ("brain_files", "status", "status, updated_at"),
    ):
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{suffix} ON {table}({cols})")
        if "list_id" in cols:
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_brain_{suffix} ON {table}({cols.replace('list_id', 'brain_id')})"
            )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_files_active ON brain_files(brain_id, path) WHERE status = 'active'"
    )
    for ddl in _BRAIN_FTS_TRIGGERS:
        conn.execute(ddl.replace("CREATE TRIGGER", "CREATE TRIGGER IF NOT EXISTS", 1))
    # Only the tables this run rebuilt: an unrelated bad row elsewhere must not stop startup.
    if any(conn.execute(f"PRAGMA foreign_key_check({t})").fetchall() for t in rebuilt):
        raise RuntimeError("Rebuilding brain tables left invalid foreign keys")


# The project fields Projects GTD added to `boards` after it shipped (step 8);
# _SCHEMA has them too, for a new database.
_BOARD_COLUMNS = {
    "dock": "TEXT",
    "pinned": "INTEGER NOT NULL DEFAULT 0",
    "starts_on": "TEXT",
    "ends_on": "TEXT",
    "template": "INTEGER NOT NULL DEFAULT 0",
    "folder": "TEXT NOT NULL DEFAULT ''",
    "sample": "INTEGER NOT NULL DEFAULT 0",
}


# The people fields added after people shipped (step 10); _SCHEMA has them too.
_PEOPLE_COLUMNS = {"up_next": "TEXT NOT NULL DEFAULT '[]'"}

# The fields card tables gained in Basecamp's shape (step 9); _SCHEMA has them too.
_CARD_TABLE_COLUMNS = {
    "board_columns": {
        "kind": "TEXT NOT NULL DEFAULT 'column'",
        "color": "TEXT NOT NULL DEFAULT ''",
        "has_on_hold": "INTEGER NOT NULL DEFAULT 0",
        "card_limit": "INTEGER",
        "description": "TEXT NOT NULL DEFAULT ''",
    },
    "cards": {
        "assignee_ids": "TEXT NOT NULL DEFAULT '[]'",
        "label_ids": "TEXT NOT NULL DEFAULT '[]'",
        "starts_on": "TEXT",
        "cover": "TEXT NOT NULL DEFAULT ''",
        "on_hold": "INTEGER NOT NULL DEFAULT 0",
        "completed_at": "TEXT",
        "repeat": "TEXT",
        "template": "INTEGER NOT NULL DEFAULT 0",
    },
}


def _card_table_kinds(conn: sqlite3.Connection) -> None:
    """Step 9, inside _migrate's transaction."""
    for table, columns in _CARD_TABLE_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
    boards = conn.execute(
        "SELECT b.id, b.list_id FROM boards b WHERE NOT EXISTS (SELECT 1 FROM board_columns c "
        "WHERE c.board_id = b.id AND c.kind = 'done')"
    ).fetchall()
    for board in boards:
        last = conn.execute(
            "SELECT id, updated_at FROM board_columns WHERE board_id = ? AND status = 'active' "
            "ORDER BY position DESC, id DESC LIMIT 1",
            (board["id"],),
        ).fetchone()
        if last is None:
            continue
        conn.execute("UPDATE board_columns SET kind = 'done' WHERE id = ?", (last["id"],))
        conn.execute(
            "UPDATE cards SET completed_at = updated_at WHERE column_id = ? AND completed_at IS NULL", (last["id"],)
        )
        now = conn.execute(f"SELECT {NOW_SQL}").fetchone()[0]
        conn.executemany(
            "INSERT INTO board_columns (list_id, board_id, name, position, kind, created_at, "
            "updated_at) VALUES (?, ?, ?, -1, ?, ?, ?)",
            [
                (board["list_id"], board["id"], name, kind, now, now)
                for name, kind in (("Triage", "triage"), ("Not now", "not_now"))
            ],
        )


def _rebuild_lists(conn: sqlite3.Connection) -> None:
    """SQLite's documented table rebuild, inside _migrate's transaction: it
    refuses DROP COLUMN on a UNIQUE column. Every row keeps its id, and the
    AUTOINCREMENT high-water mark survives, so the id of a deleted list is never
    handed out again (admin_log.list_id outlives its list)."""
    row = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'lists'").fetchone()
    high = row["seq"] if row else 0
    conn.execute(f"CREATE TABLE lists_new ({_LISTS_DDL})")
    old = {r["name"] for r in conn.execute("PRAGMA table_info(lists)")}
    shared = ", ".join(r["name"] for r in conn.execute("PRAGMA table_info(lists_new)") if r["name"] in old)
    conn.execute(f"INSERT INTO lists_new ({shared}) SELECT {shared} FROM lists")
    conn.execute("DROP TABLE lists")
    # Every table's REFERENCES lists(id) names the table, so it binds to this one.
    conn.execute("ALTER TABLE lists_new RENAME TO lists")
    top = conn.execute("SELECT MAX(id) FROM lists").fetchone()[0] or 0
    # sqlite_sequence.name is not unique, so INSERT OR REPLACE would add a second row.
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'lists'")
    conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('lists', ?)", (max(high, top),))
    conn.execute(_LISTS_INDEX)
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("Rebuilding the lists table left rows that point at no list")


def get_db() -> sqlite3.Connection:
    """This thread's connection."""
    if _path is None:
        raise RuntimeError("Database not initialized; call init_db() first")
    if getattr(_local, "generation", None) != _generation:
        conn = _connect()
        with _state_lock:
            _connections.append(conn)
        _local.conn, _local.generation = conn, _generation
    return _local.conn


def close_db() -> None:
    """Close every thread's connection (shutdown, tests, restore)."""
    global _path, _generation
    with _state_lock:
        for conn in _connections:
            conn.close()
        _connections.clear()
        _generation += 1
        _path = None


def write_lock() -> threading.Lock:
    return _write_lock


@contextmanager
def transaction(conn: sqlite3.Connection | None = None):
    """The one write path: write lock + BEGIN IMMEDIATE, commit or roll back as a unit.

    The write lock is per process. A second process on the same file (the
    operator's scripts/admin.py, scripts/restore_list.py) is serialized by
    SQLite itself: BEGIN IMMEDIATE takes the database's write lock and waits up
    to busy_timeout for the other writer to finish. An attached snapshot restore supplies
    its connection; ordinary callers use this thread's connection."""
    conn = conn if conn is not None else get_db()
    with _write_lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
