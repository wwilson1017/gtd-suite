# Connecting AI tools and programs

- [The agent link](#the-agent-link) · [Access](#access) · [Several brains](#several-brains)
- [REST API](#rest-api) · [Files](#files) · [Import Markdown](#import-markdown) · [Export and curation](#export-and-curation) · [Site sync](#site-sync)

## The agent link

Copy it from **Settings → Connect your AI**. Use it as the server address in an MCP
client, or give it to any AI that can fetch URLs. Anyone holding it can use the account's
apps, so treat it like a password. Settings can replace it, and shows which AI tools have
connected and when.

The same link answers plain HTTP too ([Agent Commands](agent-commands.md)): a GET returns the
guide, reads like `?cmd=LIST` are GETs, writes like `?cmd=ADD` are POSTs. Common Brain's
tools are MCP and REST only. No agent tool deletes anything.

The **capture link** (under Settings) is separate and write-only: it adds todos and can't read them.

**Apps** in Settings decides which apps' tools the link offers. A self-hosted account starts
with all five. On a hosted server, starting in Todo, Notes or Projects turns on those three,
Sites turns on Sites, and Brain turns on everything.

**Syncing:** call `todo_changes` (or `CHANGES`) with your last counter and keep the next one.
`todo_changes_count` checks cheaply whether anything changed. Each tool keeps its own counter.

## Access

- Browsers sign in with a cookie, never a secret URL. **Settings → Sign in on another
  device** gives a one-hour link or QR code; a confirmed email can sign in by email.
- Agent and capture links don't depend on browser sessions. A wrong or replaced link is a
  404, never a sign-in prompt. Only wrong links are rate-limited.
- Program keys and staff links are stored hashed and shown once. Keys go only in a Bearer
  header; staff links only in a path.
- On a hosted server with mail, an unconfirmed account is archived after 60 idle days and
  removed after 180. Using its agent or capture link brings an archived one back. Confirmed
  and self-hosted accounts are never put away. Unconfirmed Sites pages expire after 7 days.

## Several brains

An account can hold several brains, each with a name, folder, description, rules and AI
access (write, read only, or write only into `inbox/`). Only the owner changes these, except
that the main agent link may name a new brain once, through `brain_setup`.

Every agent link, staff link and key carries an ordered list of brains. With one brain,
paths look like `people/maya`. With several, they start with the folder: `work/people/maya`.
Path-less tools take `brain="work"`, or use the first brain. Archiving a brain removes it
from every grant, and an empty grant never falls back to another brain.

**Staff links** reach Brain tools only, default to read, and label what they write with
their name. Give staff a link carrying only the work brain.

Limits: free accounts have 1 brain and 3 staff links, Pro 10 and 100, Max and self-hosted
100 and 1,000. Keys are capped at 20 separately.

## REST API

For a script, server or nightly job, make a **program key** in Common Brain under
**Settings → Keys & access**. Choose what it reaches (Brain only, or every app), read or
read-write, which brains, and optionally the folders it may write in. The key (`cb_…`) is
shown once.

Send it only as a header. Replace `https://brain.example` with your Brain address (add
`/brain` if the suite shares one address):

```sh
# Who this key is, and every tool it may call, with JSON Schemas
curl -H "Authorization: Bearer $KEY" https://brain.example/api/v1

# Call a tool: its arguments in, its result out
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"query": "invoice OR bill"}' https://brain.example/api/v1/tools/brain_search
```

REST calls the same tools as MCP, so they never differ.

| Status | When |
|---|---|
| 200 | The tool's result |
| 400 | A bad argument, or the tool refused (not found, stale version, a limit) |
| 403 | No key, an unknown or revoked key, or a tool this key may not call |
| 404 | No such tool |
| 413 | Body over 4 MB |
| 429 | Too many wrong keys from one address (wait ten minutes), or over 600 calls a minute |

Errors are `{error}` JSON. The key also works as the bearer on `/mcp`.

What a key can do:

- A **read** key sees only read-only tools. A **Brain only** key sees only `brain_` tools.
- Writes are labelled with the key's name. The name grants nothing, "you" is refused, and
  no key can change a locked memory.
- A **folder-limited** key (one brain only) writes pages and files only in its folders and
  gets just `brain_start`, `brain_search`, `brain_page_list`, `brain_page_get`,
  `brain_page_write`, `brain_page_append`, `brain_page_edit` and `brain_file_link`. It
  never sees a page with `confidential: true` in its frontmatter.

File, import and export routes take `?brain=<folder>`, defaulting to the key's first brain.

## Files

Bytes go straight to the file store:

```sh
# 1. Reserve: one {path, size, sha256, content_type}, or {"files": [up to 100]}
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d "{\"path\": \"raw/2026/scan.pdf\", \"size\": $(stat -c%s scan.pdf), \
          \"sha256\": \"$(sha256sum scan.pdf | cut -d' ' -f1)\", \"content_type\": \"application/pdf\"}" \
     https://brain.example/api/v1/files
# 2. PUT the bytes to files[0].upload.url with its headers, within 15 minutes
curl -X PUT -H "x-amz-checksum-sha256: $CHECKSUM" --data-binary @scan.pdf "$UPLOAD_URL"
# 3. Finish (safe to retry), then download: a 302 to a 5-minute link
curl -X POST -H "Authorization: Bearer $KEY" https://brain.example/api/v1/files/$ID/done
curl -L -H "Authorization: Bearer $KEY" "https://brain.example/api/v1/files?path=raw/2026/scan.pdf"
```

The store refuses bytes that don't match the reserved size and checksum. An AI lists files
with `brain_page_list` and gets a 10-minute link with `brain_file_link`. The server needs
a file store; see [self-hosting](self-hosting.md#files).

## Import Markdown

In Common Brain, **Settings → Import & export → Import Markdown**: pick a zip, preview, import.

- Markdown and HTML become pages. Bullets in a root `MEMORY.md` or `memories.md` become memories.
- A "Locked" heading or 🔒 locks a memory (browser import only).
- Frontmatter `archived: true` imports a page archived.
- Bullets over 500 characters go to `inbox/long-memories`. Pages over 200,000 characters,
  and every other attachment, become files.
- Secrets are blanked; the report lists where, never the values.

Programs send the zip to `POST /api/v1/import` with a write key without folder limits:

```sh
curl -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/zip' \
     -H 'X-Import-Name: notes.zip' --data-binary @notes.zip \
     'https://brain.example/api/v1/import?dry_run=1&label=notes'
```

Use `dry_run=0` to import. Keep `X-Import-Name` the same between runs: a re-run skips what's
unchanged and resumes where a failed run stopped. `archive_missing=1` archives what's no
longer in the zip, after a complete run; **pause other writers** when you use it.

Limits: 200 MB upload, 50,000 entries, 1 GB uncompressed, 100 MB per attachment.

## Export and curation

`GET /api/v1/export` downloads a full snapshot zip; `?since=2026-10-01` gives only the
changes after a date. It needs a read key without folder limits. The app has the same
under Export, and `brain_export_link` hands the person a link to it.

The zip holds `memories.json`, `pages.json`, `files.json`, `history.json`, a readable
`memories.md`, and page bodies under `pages/` (archived ones under `_archived/pages/`).
File bytes aren't included; fetch one with `GET /api/v1/files/{id}`. Exports can't be
imported back yet.

Curators run `brain_curate(misses_since, unattended, folder)` and `brain_eval(folder)`. The
working folder defaults to `curator`; rules live at `curator/rules`. Save `misses_until`
for the next run, and keep going while `misses_more` is true. `brain_search(probe=true)`
logs no misses. Eval reads `- id: query => expected; expected` lines from `<folder>/golden`
and appends the score to `<folder>/scorecard`. Write tools take `pass_label` and `reason`
for the history.

Some days `brain_start` returns a `tickle`: one question the brain can't answer, for the AI
to ask the person. It is the first line of `curator/golden` whose probe fails, else a search
missed twice or more in 30 days. After asking (and saving the answer on a page its `expects`
strings name, or with `brain_remember`), call `brain_tickle_record(question)`: the question rests five
days and no other is offered that day. The set-up (`brain_onboard`) asks for the person's
top questions and writes `curator/golden`.

## Site sync

With a file store and a content domain, and "Own address for each page" on in Sites
Settings, `SITE_SYNC` / `site_sync` publishes a folder: send a manifest of
`{path, size, sha256}` (including `index.html`), PUT the files it asks for, and call again
until it's published. Reuse a stable `client_ref` when creating. The whole site switches
at once; reload after an update. The Sites app can download any site as a zip.
