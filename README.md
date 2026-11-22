<p align="center"><img src="docs/logo.svg" alt="GTD suite: Todo, Notes, Projects, Sites and Common Brain" width="480"></p>

# GTD suite

Five apps in one service, with one account and one agent link that AI tools read and write
through. The backend uses FastAPI and SQLite; the frontend uses React. You can use the apps
in a browser and connect your own AI tools. The server runs no AI itself.

- **Todo GTD:** inbox, next actions, projects, areas and weekly reviews.
- **Notes GTD:** Markdown notes with tags, colours and pins.
- **Projects GTD:** project boards, tasks, messages, files and schedules.
- **Simple Sites:** publish pages, file sites and short links.
- **Common Brain:** shared memories, pages and files with history and access rules.

Would rather not host it? The same code runs at https://todogtd.com.

## Run it yourself

### Any Docker host

1. Clone this repository and open its directory. Install Docker with Compose.
2. In `docker-compose.yml`, set `PUBLIC_BASE_URL` to the address you will open.
   The default, `http://localhost:8000`, works on this machine. For remote access, use your
   server's address; use an HTTPS reverse proxy for a public deployment.
3. Run `docker compose up --build -d`. The named volume keeps the database and backups
   at `/data`. Check `curl http://localhost:8000/healthz`.
4. Open the address and press **Start**. It is yours: one account, all five apps at `/`,
   `/notes`, `/projects`, `/sites` and `/brain`. The first visitor claims the account.
   Use Settings (the ⚙) to sign in on another device.

Keep one worker and one replica. Do not remove the data volume when upgrading:
`docker compose up --build -d` rebuilds and starts the new version with the existing data.

### Railway

1. **New project → Deploy from GitHub repo** and pick your fork. Railway finds the
   `Dockerfile` by itself; no start command is needed.
2. **Add a volume** to the service with mount path **`/data`**. Without it the database is on the container's own disk and every deploy wipes it.
3. **Variables**: `TRUST_PROXY=1`. Set `PUBLIC_BASE_URL` only if you attach your own domain.
4. **Settings → Networking → Generate domain** (or add your own).
5. **Settings → Deploy → Healthcheck path**: `/healthz`.
6. Open the address and press **Start**. This browser is now signed in to it; use
   Settings → **Sign in on another device** for your phone. All five apps are available at
   `/`, `/notes`, `/projects`, `/sites` and `/brain`. From then on the home page shows
   "This list is set up" to everyone else.

Keep the service at **one replica**. The app is a single process by design (see
`backend/db.py`), and Railway does not allow replicas with a volume anyway. A deploy restarts
the service, so expect a few seconds of downtime.

**Locked out?** Set `RESET_CODE` to a long random string in the service's variables, let it
redeploy, open the home page, choose **Reset access** and type the code. Every browser is
signed out, unused sign-in links stop working, program keys are revoked, the list's email is
removed, the agent and capture links are replaced — and the browser you typed the code in is signed in, with the new
links under Your AI and Settings. Then remove the variable. The same steps recover a deployment that a
stranger claimed before you did. Or, from the service's shell, `python -m scripts.admin
signin-link 1` prints a one-hour sign-in link and changes nothing else.

Railway's own HTTP log (the service's "HTTP Logs" tab) records full request paths, which
include the agent, capture and sign-in tokens (the app's own pages and API carry none). The
app's log does not: it prints `***` in their place.

## Settings

Persisting `DATA_DIR` is required to keep your data. Set `PUBLIC_BASE_URL` to your public
address (Railway can supply it). Everything else is optional. `OPEN_SIGNUP` enables
multi-account hosting; Stripe settings only apply with open signup. Mail and file storage
work in either mode.

| Variable | Default | What it does |
|---|---|---|
| `DATA_DIR` | `data` (`/data` in the image) | Where `todo.db` and `backups/` live. Must be a persistent, writable directory; the app refuses to start if it cannot write there. |
| `PUBLIC_BASE_URL` | Railway's public domain if there is one, else the request's own address | The address every generated link starts with (agent, capture, sign-in), e.g. `https://todogtd.com`. Set it whenever you use your own domain. When it starts with `https://` the session cookie is `Secure`. |
| `OPEN_SIGNUP` | `false` | `true` lets anyone create a list. Leave unset to run one list. |
| `SIGNUP_CLOSED` | `false` | With `OPEN_SIGNUP` on, `true` stops new accounts: every front page offers sign-in only and creating one is refused (403). Existing accounts, sign-in, agent and capture links keep working. No effect on a one-list server. |
| `FREE_MAX` | `true` | The suite is free: with `OPEN_SIGNUP` on, an account with a confirmed email gets Max, and nothing is sold (no plan card, prices, billing routes, or the policy pages' paid parts; no Refunds page). `false` brings Pro back as it was, with the Stripe settings below. |
| `RESET_CODE` | unset | One-list servers only. While set, the home page offers "Reset access" to whoever types this code. Remove it afterwards. |
| `TRUST_PROXY` | `false` | `1` when the app is behind a proxy that sets the client-address header itself (Railway does; for Cloudflare see `TRUSTED_IP_HEADER`). Rate limits then key on the address in `TRUSTED_IP_HEADER` instead of the proxy's own. Never set it on a server reached directly: clients could then pick their own address. |
| `TRUSTED_IP_HEADER` | `X-Real-IP` | The header the proxy puts the client address in. Railway sets `X-Real-IP` itself and ignores what the client sent. Behind Cloudflare set `CF-Connecting-IP`, and only if the server cannot be reached except through Cloudflare (otherwise clients send that header themselves). With Cloudflare in front of Railway the default `X-Real-IP` is Cloudflare's address, shared by many visitors. For a list-valued header such as `X-Forwarded-For` the first entry is used. |
| `PROJECTS_BASE_URL` | unset | Projects GTD's own address, e.g. `https://projectsgtd.com`: a request on that host gets the Projects app (project boards) on the same account, and its links start with it. Unset, Projects is served at `/projects` on the main address. With `OPEN_SIGNUP` on, Projects lives at `/projects` either way and this host is its old address: agent links and signed-in browsers there keep working, and a signed-out visitor is sent to `/projects`. |
| `SITES_BASE_URL` | unset | Simple Sites' own address, e.g. `https://simplesites.app`: a request on that host gets the Sites app, and its pages and short links are served there (`/<code>` or `/<name>-<code>`). Unset, Sites is served at `/sites`; visitor pages and links remain at the main address's top level. |
| `SITES_SHORT_URL` | unset | A shorter address Simple Sites hands its pages and links out at, e.g. `https://ss.page`. Its host serves those addresses, password forms and visitor data endpoints: any other GET goes to the same path on `SITES_BASE_URL`, anything else is a 404. `SITES_BASE_URL` keeps serving every address, so links handed out before stay good. Needs `SITES_BASE_URL`. |
| `SITES_CONTENT_DOMAIN` | unset | Isolated page domain, e.g. `simplesites.page` (lowercase, no scheme or port). Needs `SITES_BASE_URL`. Pages get `https://<name>-<code12>.<domain>/`; their old addresses redirect. Existing data pages keep their sandboxed path until their content is replaced. Unset, pages keep serving at their path addresses. A missing page and the domain's own front page tell visitors to report abuse to `abuse@<domain>` (the standard role address), so make that mailbox exist. |
| `SITES_CONTENT_LISTS` | unset | Staged activation: comma-separated account list ids, e.g. `4`. While set, only those accounts use content-host addresses and redirects. Unset allows all accounts; an empty value allows none. Needs `SITES_CONTENT_DOMAIN`. |
| `NOTES_BASE_URL` | unset | Notes GTD's own address, e.g. `https://notesgtd.com`: the Notes app (markdown notes, like Google Keep) on the same account, or `/notes` on the main address when unset. With `OPEN_SIGNUP` on, it is an old address, as for `PROJECTS_BASE_URL`. |
| `BRAIN_BASE_URL` | unset | Common Brain's own address, e.g. `https://commonbrain.ai`: the shared second brain every connected AI reads and writes (memories and pages, with full history), on the same account. Its front page is the suite's way in: an account started there begins with every app on. Unset, Brain is served at `/brain` on the main address. |
| `RESEND_API_KEY` | unset | A [Resend](https://resend.com) API key. With `MAIL_FROM`, turns on confirming a list's email and signing in by email; without both, the email parts of the app are hidden (and a hosted list cannot leave the smaller limits, and is never put away). It also needs `PUBLIC_BASE_URL` (or Railway's domain): a mailed link is never built from a request's Host header. |
| `MAIL_FROM` | unset | The sender, on a domain verified with Resend, e.g. `Todo GTD <you@example.com>`. |
| `SNAPSHOT_INTERVAL_SECONDS` | `3600` | How often a snapshot is taken. |
| `STRIPE_SECRET_KEY` | unset | Hosted servers only: with `STRIPE_WEBHOOK_SECRET`, Pro (the paid plan) syncs from Stripe and Manage billing works. See [Billing](#billing-hosted). |
| `STRIPE_WEBHOOK_SECRET` | unset | The signing secret of the Stripe webhook endpoint. |
| `STRIPE_PRICE_MONTH`, `STRIPE_PRICE_YEAR` | unset | The two Pro prices. Setting both opens sales (the Upgrade buttons); removing one stops new sales and nothing else. |
| `FILES_S3_ENDPOINT`, `FILES_S3_BUCKET`, `FILES_S3_KEY_ID`, `FILES_S3_SECRET` | unset | Common Brain's files: any S3-compatible store (Cloudflare R2, MinIO, S3, B2), addressed path-style, e.g. `https://<account>.r2.cloudflarestorage.com` and a bucket with a read-and-write key. Unset, Files is off. See [Files](#files-common-brain). |
| `FILES_S3_REGION` | `auto` | The region requests are signed for: `auto` is R2's; MinIO and S3 name a real one (`us-east-1`). |
| `SITES_FILES_PREFIX` | `sites` | The bucket prefix this deployment keeps Simple Sites' files under. **Each deployment sharing a bucket needs its own** (e.g. `sites-dev` for a local server): a daily pass deletes any object under this prefix that the deployment's database has no record of. |
| `RAILWAY_PUBLIC_DOMAIN` | unset | Supplied by Railway; used as the HTTPS main address when `PUBLIC_BASE_URL` is unset. |
| `PORT` | `8000` | The port the container listens on (Railway sets it). |

Confirmation and sign-in mail is plain text, so there is nothing for click tracking to
rewrite. Keep open and click tracking **off** on the Resend domain (the default); with it on,
those links would pass through a third party.

## Connecting an AI tool

Open **Your AI** in Todo GTD, Notes GTD or Projects GTD (**Connect** in Simple Sites and
Common Brain) and copy the agent link. Give it to an AI tool that can fetch URLs, or use it
as the server address in an MCP client. The link contains a secret: anyone who has it can
use the account's enabled apps. The page has setup steps for each AI tool, can replace the
link, and says which tools have connected and the day each last called. The write-only
capture link, under Settings, is separate and can add todos without reading them.

The same link speaks **Agent Commands** for HTTP clients and scripts. A plain GET returns
the guide. Reads such as `?cmd=LIST` use GET; writes such as `?cmd=ADD` use POST.
See [the Agent Commands specification](docs/agent-commands.md). Common Brain's tools use
MCP or the REST API below. No agent tool deletes content.

### How access works

- Browsers sign in with a cookie, not a secret URL. Use Settings → **Sign in on another
  device** for a one-hour, single-use link or QR code. A confirmed email also allows sign-in
  by email when mail is configured. Changing the email cancels links sent to the old address.
- Browser writes require the same origin. Every `/api/app` call except `GET /session` must
  carry the session's list id in `X-List`; a mismatch returns 409 and reloads the app.
- Agent and capture links are independent of browser sessions. Unknown or replaced path
  tokens return 404, never a sign-in challenge. Only wrong links are throttled by address;
  valid links are still served. Accounts also have write and call budgets.
- Program keys and named staff links are hashed and shown once. Keys travel only as Bearer
  headers; staff links travel only in paths. Their grants control which brains they reach.
- One account has one main agent link. **Apps** under Settings controls its available tools.
  New self-hosted accounts start with all five apps on. On an open-signup server, starting
  in Todo, Notes or Projects enables those three, starting in Sites enables Sites, and
  starting in Brain enables all five; signing in on an app's address enables that app.
- A sync tool calls `todo_changes` (or `CHANGES`) with its last counter and saves the next
  counter. `todo_changes_count` (`CHANGES_COUNT`) checks cheaply whether anything changed.
  Each tool keeps its own counter.
- On open-signup servers with mail, unconfirmed accounts become archived after 60 idle
  days and removed after 180. Agent or capture use restores an archived account; a removed
  account needs email confirmation in the browser. Confirmed accounts and self-hosted
  accounts are never put away. Never-used hosted accounts are deleted after 30 days.
- Hosted unconfirmed Sites pages expire after 7 days and are deleted 30 days later unless
  the email is confirmed. Agents can unpublish; the person can delete in the browser.

### Several brains in one account

Each Common Brain account starts with one unnamed brain. Brains have a name and folder,
a description, rules, and an AI access setting: write, read only, or write only into
`inbox/` (no memory writes). The owner sets these; the main agent link may name an unsettled
brain once through `brain_setup`, after a naming interview with the person.

Every main agent link, staff link and program key carries an ordered set of brains. A
single-brain credential keeps ordinary paths such as `people/maya`. With several brains,
paths begin with the brain's folder, such as `work/people/maya` or `personal/daily/today`.
`brain_page_list` at the root lists those folders; search spans only the carried brains.
Path-less tools accept `brain="work"`; without it, the first brain receives the call.
Archiving a brain removes it from active grants. An empty grant never falls back to a
personal brain: Brain-only credentials are refused, while multi-app credentials keep
working for their other apps.

Named staff links use the same hashed credential records as keys, default to read access,
are shown once, and work only in `/link/<token>` (also the older MCP path shapes). They
reach Brain tools only, and their name labels writes. Give staff a link carrying only their
work brain. Folder restrictions are available on keys carrying exactly one brain.

Free accounts have 1 active brain and 3 live staff links; Pro has 10 and 100. Max and
self-hosting show Unlimited (ceilings of 100 brains and 1,000 links). Keys keep their
separate limit of 20. Existing brains and credentials keep working after a plan lapses.

The signed-in browser API exposes `GET/POST /api/app/brains`, `PUT /api/app/brains/{id}`,
`POST /api/app/brains/{id}/archive` and `/restore`, `PUT /api/app/link-brains` with
`{"brains": [id, ...]}`, and `POST /api/app/brain/move` with `kind`, `id`, `to_brain`, optional
`path` and `expected_version`. `/api/app/keys` accepts `brains` and `kind` (`key` or `link`);
`/api/app/session` includes brain identities and caps. These routes use the browser session,
`X-List` and same-origin checks.

The operator can fold a whole Brain-only account into another:
`python -m scripts.admin merge-brain FROM TO --name Personal --folder personal`.
It prints counts, credential scopes and name clashes; add `--yes` to apply. The source
must have exactly one brain, no other apps' content, and only Brain-scoped credentials
carrying exactly that brain. The transaction copies policy, moves content, history, files
and keys, renames clashing keys, and disables the source. Existing key values keep working.

### REST API

A program (a script, a server, a nightly job) reaches an account with a **program key**
instead of the agent link. Make one under Connect → **For programs** in Common Brain: give it
a name, what it reaches (Common Brain only, or every app on the account), its access (read
only, or read and write) and, for a Brain key, optionally the folders it may write in. The key
(`cb_…`) is shown once and stored only as a hash; the list shows each key's last use, and
revoking one stops it at once. An account holds up to 20 live keys. Keys also carry an ordered
`brains` grant; a folder-limited key must carry exactly one brain.

The key goes only in a header, `Authorization: Bearer cb_…`, never in an address.
Replace `https://brain.example` below with your Brain app's address, including `/brain`
when using one address for the suite:

```sh
# Who this key is, and every tool it may call, each with its JSON Schema
curl -H "Authorization: Bearer $KEY" https://brain.example/api/v1

# Call a tool: a JSON object of its arguments in, its result out
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d '{"query": "invoice OR bill"}' https://brain.example/api/v1/tools/brain_search
```

The file, import and export routes take `?brain=<folder>`, defaulting to the key's first
active brain, for example `/api/v1/export?brain=work` or
`/api/v1/files?brain=work&path=raw/scan.pdf`. The named brain must be carried by the key.
Tool calls use the same `brain` arguments and blended path prefixes as MCP.

`POST /api/v1/tools/{name}` runs the agent link's own tool by name, so REST and MCP never
differ. Answers:

| Status | When |
|---|---|
| 200 | the tool's result |
| 400 `{error}` | a missing or wrong argument, or the tool refused (not found, a stale version, a cap) |
| 403 `{error}` | no key, an unknown or revoked key, or a tool this key may not call |
| 404 `{error}` | no tool by that name |
| 413 `{error}` | a body over 4 MB |
| 429 `{error}` | too many wrong keys from one address (wait ten minutes), or over the account's 600 calls a minute, shared with the agent link |

No answer carries `WWW-Authenticate`. The same key also works on `/mcp` as the bearer, for an
MCP client; in any path it is just an unknown link (404).

Files have routes of their own, since their bytes go straight to the file store (see
[Files](#files-common-brain)):

```sh
# 1. Reserve: one {path, size, sha256, content_type}, or {"files": [up to 100]}
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
     -d "{\"path\": \"raw/2026/scan.pdf\", \"size\": $(stat -c%s scan.pdf), \
          \"sha256\": \"$(sha256sum scan.pdf | cut -d' ' -f1)\", \"content_type\": \"application/pdf\"}" \
     https://brain.example/api/v1/files
# 2. PUT the bytes to files[0].upload.url with files[0].upload.headers, within 15 minutes
curl -X PUT -H "x-amz-checksum-sha256: $CHECKSUM" --data-binary @scan.pdf "$UPLOAD_URL"
# 3. Finish it (a retry is fine), then download: a 302 to a 5-minute link
curl -X POST -H "Authorization: Bearer $KEY" https://brain.example/api/v1/files/$ID/done
curl -L -H "Authorization: Bearer $KEY" "https://brain.example/api/v1/files?path=raw/2026/scan.pdf"
```

The store refuses bytes of another length or checksum than the ones reserved. A path keeps its
case and characters (no `..`, `\` or control characters). An AI lists files with
`brain_page_list` and gets a 10-minute link with `brain_file_link`.

- A **read** key sees and calls only the read-only tools.
- A **Brain only** key sees only the `brain_` tools.
- What a key writes in Common Brain is labelled with the key's name. The name is only a label:
  "you" is refused, and no key can change a locked memory.
- A **folder-limited** key writes pages only inside its folders, reads and writes only the
  files inside them (a file's path must start with the folder exactly), and gets a narrow
  surface: `brain_start`, `brain_search`, `brain_page_list`, `brain_page_get`,
  `brain_page_write`, `brain_page_append`, `brain_page_edit` and `brain_file_link`. It never sees a page whose frontmatter says
  `confidential: true`: such a page is left out of every list and search, and reading or writing
  it is "not found". Memories, history, restore, changes and the curator are refused to it.

### Import Markdown

In Common Brain's **Connect**, choose **Import Markdown**, select a zip and preview it,
then Import. Markdown and HTML become pages; root `MEMORY.md` or `memories.md` bullets
become memories. A Locked heading or 🔒 locks a memory only in the browser import.
Bullets over 500 characters become lines on `inbox/long-memories` (or a file if that
generated page is oversized). Frontmatter `archived: true` imports a page archived. Pages
above 200,000 characters become files at their original paths; other attachments (including `.txt`) are files too.
Files are skipped if this server has Files off. Secrets in pages and memories are blanked;
the report lists the paths and counts, never the secret values.

Programs can send the raw zip to `POST /api/v1/import?dry_run=1&label=my-import` with a
write key that has no folder limit. Send `dry_run=0` to import. Set `X-Import-Name` to the
zip's basename (default `import.zip`, URL-encode non-ASCII names), keeping it the same on
subsequent runs:

```sh
curl -X POST -H "Authorization: Bearer $KEY" -H 'Content-Type: application/zip' \
     -H 'X-Import-Name: notes.zip' --data-binary @notes.zip \
     'https://brain.example/api/v1/import?dry_run=1&label=notes'
```

Re-running skips unchanged bodies and attachment hashes, without new versions. The report
says how many entries were processed and whether the run completed; a cap or write failure
stops it, retaining completed entries so another run resumes. All page and memory changes
carry the pass label in Changes. REST imports cannot lock, unlock or archive locked memories.

Optional `archive_missing=1` archives active pages and memories absent from the zip, plus
missing active files made by imports with the same `X-Import-Name`. Separately uploaded files
are untouched. This happens only after a complete run. **Pause all other writers during
cutover**, especially when archiving missing items.

Limits: 200 MB uploaded, 50,000 zip entries, 1 GB of actual uncompressed bytes, 100 MB per
attachment. Absolute paths, traversal, symlinks and names that collide after normalising
are refused before any write. Invalid UTF-8 is replaced and reported. No dependency or
server-side AI is involved.

### Export and curation

`GET /api/v1/export?since=2026-10-01` downloads changes after a UTC date or ISO time;
omit `since` for a full snapshot. It needs a read-capable Brain key without folder limits.
The signed-in app offers the same date option under Export; `brain_export_link` opens it
without granting access. Each zip is one consistent database snapshot, marked
`common-brain-export: 1` in `EXPORT`, with root-level `memories.json`, `pages.json`,
`files.json`, human-readable `memories.md` and `history.json`. Page bodies are
`pages/<path>.md|.html` or `_archived/pages/<path>.md|.html`. Files are listed with their
id, path, size, sha256, type and status; their bytes are not zipped. Fetch an exact file
version with `GET /api/v1/files/{id}` (a download redirect); a forgotten file returns 404.
Full exports let mirrors reconcile moves, archives and Forgets. A since-export is for
reviewing changes, not backing up. The Markdown importer refuses exports: restoring
from an export isn't supported yet.

Curators use `brain_curate(misses_since, unattended, folder)` and `brain_eval(folder)`;
the default working folder is `curator`, while rules always live at `curator/rules`.
Save the opaque `misses_until` cursor for the next run. When `misses_more` is true,
continue with that cursor after handling the returned misses. An ISO date/time can
also be used for `misses_since` on the first run.
`brain_search(probe=true)` creates no misses. Eval reads `- id: query => expected; expected`
lines from `<folder>/golden`, checks top-10 paths and titles, and appends the score to
`<folder>/scorecard`. It writes, so a read-only key cannot run it. Neither eval nor the
export link is available to folder-limited keys. The remember, memory_update, page_write,
page_append, page_edit and restore tools accept `pass_label` and `reason` for history.
Page writes warn if a removed contact exists on no other active page outside inbox,
archive and curator segments.

## Files (Common Brain)

Common Brain keeps files (PDFs, images, recordings: anything that is not a page) in an
S3-compatible store, never on the volume. Normal uploads go straight between the browser
(or program) and the store. Zip imports spool temporarily on the server and upload attachments
through the same reserve/PUT/done flow. Before turning it on:

1. Make a bucket and a key with read and write on it, and set the `FILES_S3_*` variables.
2. Give the bucket a CORS rule allowing `PUT` and `GET` from the app's addresses (Common Brain's
   and the anchor's), with the headers `content-type` and `x-amz-checksum-sha256`.
3. Give it a lifecycle rule deleting objects under `staging/` after a day: the backstop for
   uploads nobody finished (the app also sweeps them every hour).
4. Run the provider test against it, from a checkout with the same variables set:
   `uv run pytest -m objectstore`. It uploads, copies, downloads and deletes under `staging/` and
   `pytest/` and `sites/pytest/`, and checks that the store refuses an upload of the wrong length or checksum. Keep
   Files off on a store that fails it: the quota relies on that refusal.

Storage caps: self-hosted accounts have 100 GB. Hosted accounts need a confirmed email
for Brain files, then have 500 MB on Free, 10 GB on Pro or 100 GB on Max. Every version,
unfinished upload and not-yet-deleted forgotten file counts. A file is at most 5 GB (one upload), and 500 MB from the browser. Archive keeps a file; Forget (in the
app only) deletes every version at its path for good.

Simple Sites file sites use the same bucket under `sites/`, and share this storage pool with
Brain files (25 MB for unconfirmed Sites accounts). Add `GET` from
`https://*.<content domain>` to the R2 CORS rule, for example `https://*.simplesites.page`.
Keep the `staging/` lifecycle rule restricted to that prefix: Sites uploads go directly to
checksum-bound final keys. Hourly GC keeps unreferenced files for 30 days; daily reconciliation
removes old keys absent from the database, including uploads that completed after deletion.
Database snapshots do not contain these bytes.

With a content domain and file store configured, `SITE_SYNC` / `site_sync` accepts a manifest
of `{path, size, sha256}` (including `index.html`) and returns PUT URLs only for missing hashes.
Reuse a stable `client_ref` on creation; PUT with the returned headers and call again until
published. The complete manifest switches at commit; reload after updates. File-site limits:
25 MB Free/unconfirmed, 250 MB Pro, 1 GB Max/self-hosted, at most 1,000 files.
Text stays same-origin; media uses 12-hour inline signed URLs. Such URLs already issued can
remain usable after unpublish, takedown or password changes until they expire.
The Sites app offers Download zip, including for a single-body page. Slides and local media
can open offline; `fetch('live.json')` cannot work from `file://`.

Operator check (stdlib only, source folder unchanged):
`python scripts/sites_sync_check.py --link-file /path/to/agent-link /path/to/deck`.
It times initial publishing, unchanged and 20 changed updates, an abandoned/retried update,
concurrent commits and unpublish/republish. Check slides, playback/seek during updates and
an offline zip by eye. The link can instead come from `SITES_AGENT_LINK`; it is never printed.

## Backups and restore

Every hour the app writes a consistent copy of the database to `DATA_DIR/backups/`
(`todo-YYYYMMDDTHHMMSSZ.db`). It keeps every snapshot from the last 6 hours and the newest
of each day for 7 days: each one is a whole copy of the database, so keep longer history off
the volume (below). A snapshot that fails is logged and skipped. Snapshots pause, with a
warning in the log, while the volume has less free space than the database's size plus 100 MB.
After each run the app asks the kernel to drop the snapshots from its file cache, because
Railway counts cached files as the service's memory.

The snapshots are on the same volume as the database: they protect against mistakes, not
against losing the volume. Copy them elsewhere if the list matters.

### Copies off the volume

On Railway, two things cover losing the volume, and neither needs a change to the app:

- **Pull the snapshots to another machine on a schedule.** Make a project token (project
  **Settings → Tokens**, environment `production`) and run this hourly from cron on a machine
  you control, with the [Railway CLI](https://docs.railway.com/guides/cli) installed:

  ```bash
  export RAILWAY_TOKEN=<project token> V=<volume name>
  cd <the folder you keep>
  railway volume files --volume "$V" list /backups --json </dev/null | jq -r '.files[].name' |
    grep -E '^todo-[0-9TZ]+\.db$' | while read -r name; do
      [ -e "$name" ] || { railway volume files --volume "$V" download "/backups/$name" "$name.part" \
        --overwrite </dev/null && mv "$name.part" "$name"; }
    done
  ```

  It downloads only the snapshots you do not have yet, each under a temporary name until it
  finishes, so a download cut short is fetched again next run. The `</dev/null`s matter: the CLI
  reads standard input, and would otherwise list nothing or swallow the list of names.
  Downloading the whole folder every hour moves every kept copy each time, and Railway
  meters that as the service's outbound traffic. Copy only
  `backups/`, never `todo.db` itself: a snapshot is a finished file, the live database may be
  mid-write. Have the job warn you when no new file has arrived for a few hours; a backup that
  stopped quietly is the usual way this fails.
- **Turn on Railway's volume backups** (the service's **Backups** tab: daily, weekly, monthly).
  They are a second way back, not an off-site copy: wiping the volume deletes them, and they
  restore only into the same project and environment.

On Railway, run the commands below in the service's shell (`railway ssh`), in `/app`.

### Disaster restore (the whole database)

Replaces everything, links and sign-ins included, with the snapshot's state. Run this in
the service's own shell (`docker compose exec suite sh`, or `railway ssh`):

```bash
cd /data
cp backups/todo-20261004T120000Z.db todo.db.restore
mv todo.db.restore todo.db && rm -f todo.db-wal todo.db-shm
```

Then restart the service straight away (`docker compose restart`; Railway: **Deployments →
Restart**). The running process still holds the old file; anything it writes between the `mv`
and the restart is discarded. Locally, stop the app first, run the same commands, start it again.

### One-list repair

Puts ONE list's todos, projects and areas back the way a snapshot has them. The list's
current links, signed-in browsers, email and time zone are kept, and every other list is
untouched. It is safe while the app is running. Common Brain's files stay as they are now:
their bytes are in the file store, which a snapshot does not hold.

```bash
python -m scripts.restore_list /data/backups/todo-20261004T120000Z.db --list-id 7
```

`python -m scripts.admin find --link=<the list's agent link>` gives the id. Anything added to
that list after the snapshot is gone afterwards, so the script first takes a fresh snapshot of
the live database and prints its name.

## Administration

There is no admin web page, on purpose: a secret that could see every list would be the most
valuable thing on the server to steal. The operator runs a command-line tool inside the
container instead. It works on the live database while the app is running, and what it
changes takes effect at once, with no restart.

On Railway, open a shell in the service and run a command (the shell starts in `/app`):

```bash
railway ssh --service <your service>
python -m scripts.admin stats
```

or run one command without staying in the shell:

```bash
railway ssh --service <your service> "python -m scripts.admin stats"
```

Anywhere else, run it from the app directory with the same `DATA_DIR` as the app.

| Command | What it does | Example |
|---|---|---|
| `stats` | Totals: lists, todos by status, projects, areas, lists created per day (14 days), lists with an email and with a confirmed one, database and snapshot sizes | `python -m scripts.admin stats` |
| `lists` | One row per list, newest first: id, account number, name, created, last used, open/total todos, projects, has-email, confirmed, state (`active`, `archived`, `removed` or `disabled`). Filters: `--email`, `--name`, `--created-after`, `--created-before`, `--unused`, `--limit` (default 100). `--show-email` prints the addresses | `python -m scripts.admin lists --created-after 2026-10-01 --unused` |
| `find` | Which list an agent or capture link (or bare token) belongs to, and which kind it is. A sign-in link cannot be identified | `python -m scripts.admin find --link=https://todogtd.com/link/AbC…` |
| `show` | One list's details: the `lists` row plus time zone, review date and per-status counts | `python -m scripts.admin show 7` |
| `signin-link` | Prints a one-hour, single-use sign-in link for the list. Nothing else changes. The way back in for someone with no email and no signed-in device | `python -m scripts.admin signin-link 7` |
| `sign-out-all` | Signs every browser out of the list and cancels its unused sign-in links. The agent and capture links are untouched | `python -m scripts.admin sign-out-all 7` |
| `set-email` | Sets the list's email, unconfirmed (it gets no sign-in mail until someone signed in to the list confirms it); cancels sign-in links already mailed | `python -m scripts.admin set-email 7 me@example.com` |
| `clear-email` | Removes the list's email; cancels sign-in links already mailed | `python -m scripts.admin clear-email 7` |
| `disable` | The list's capture and agent links answer as unknown links (404) and its browsers as signed out. Deletes nothing | `python -m scripts.admin disable 7` |
| `enable` | Undoes `disable` | `python -m scripts.admin enable 7` |
| `delete` | Permanently removes the list and everything in it. Prints what will go, needs the confirmation flag typed in full, and takes a snapshot first unless `--no-snapshot` | `python -m scripts.admin delete 7 --yes-delete-list-7` |
| `snapshots` | The snapshot files, with time and size | `python -m scripts.admin snapshots` |
| `restore` | One-list repair from a snapshot (the same as `scripts.restore_list`, below) | `python -m scripts.admin restore 7 --from todo-20261004T120000Z.db` |

`stats`, `lists`, `find`, `show` and `snapshots` take `--json`. Write `--link=<token>` (with
the `=`) when passing a bare token, since a token may start with `-`. Wherever a command takes
a list id, the account number the person sees under Settings works too, with or without its dash.

**Privacy.** The tool never prints an agent or capture link, and the only link it prints is
the one-hour sign-in link from `signin-link`. By default it shows only metadata: counts, dates, the
list's name. `show <id> --content` additionally prints the list's todo and project titles.
That is reading someone's private list, so it is an explicit flag, it says so when used, and
it is recorded. Email addresses are hidden unless `--show-email` is given.

Every change (and every `--content` read) adds a line to the `admin_log` table: time,
command and list id, never a link, an address or content. Read it with
`sqlite3 /data/todo.db "SELECT * FROM admin_log"` if the image has `sqlite3`, or
`python -c "import sqlite3; print(*sqlite3.connect('/data/todo.db').execute('SELECT * FROM admin_log'), sep='\n')"`.

Most app content is archived. Browser-only Sites deletion and Brain Forget also remove
content permanently; the operator's `delete` removes a whole account.

## Local development

Needs [uv](https://docs.astral.sh/uv/) and Node 22 (20.19 or newer also works).

```bash
uv sync
cd frontend && npm ci && cd ..

# Backend on :8000, with open signup so you can make as many lists as you like
OPEN_SIGNUP=true uv run uvicorn backend.main:app --workers 1 --reload

# Frontend dev server (proxies /api to :8000)
cd frontend && npm run dev
```

To run it the way the container does, build the frontend into `backend/static` and serve
everything from the backend:

```bash
cd frontend && npm run build && cd ..
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Or with Docker:

```bash
docker build -t todo-gtd .
docker run -p 8000:8000 -v todo-gtd-data:/data todo-gtd
```

Tests:

```bash
uv run pytest backend/tests
cd frontend && npm test
```

Run `scripts/check.sh` before opening a pull request. It runs lint, formatting, type checks,
both test suites and the frontend build.

## The paid folder

`backend/paid/` and `frontend/src/paid/` hold the plans and billing sold by the hosted
service. They are MIT like the rest of the repository. Billing stays off unless a server
sets open signup and its own Stripe keys. A self-hosted server has no plans and no limits
beyond the built-in safety caps. Open signup also supports operator-granted plans without
Stripe.

### Billing (hosted)

Pro is the paid plan: $5 a month or $36 a year, one plan for the whole account. It is sold
through Simple Sites and lifts every app's limits (Sites: 2,500 pages and 2,500 short links), and
shows how many times each page was opened and each short link followed, and lets a page ask
visitors for a password (set in the Sites app; a visitor types it once per device for 30 days,
and changing it asks everyone again).
Stripe takes the payments as merchant of record (Managed Payments), so it handles sales tax,
VAT, receipts, refunds and disputes. Pro needs a confirmed email. A self-hosted server has no
billing and already has the big limits.

Setting it up, in the Stripe account the suite bills from:

1. Settings → Managed Payments: activate it and accept its terms (Stripe reviews eligibility).
2. Create the product "Simple Sites Pro" with a tax code labeled "Eligible for Managed
   Payments" (software as a service), and two prices: $5/month and $36/year.
3. Turn on the Customer Portal: cancel, and switch between the two prices, with cancellations
   taking effect at the end of the billing period.
4. Add a webhook endpoint `https://<your-sites-host>/api/stripe/webhook` on API version
   `2026-04-22.dahlia`, for `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid` and
   `invoice.payment_failed`.
5. With `OPEN_SIGNUP=true` and `FREE_MAX=false`, set `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` (this turns on
   syncing), then `STRIPE_PRICE_MONTH` and `STRIPE_PRICE_YEAR` (this opens sales).

How it stays right: Pro is never set by one event. Every webhook makes the app re-read the
account's subscriptions from Stripe (`billing.sync`), so the order events arrive in does not
matter. Coming back from Checkout re-reads it at once; an hourly catch-up re-reads any
account whose paid period has passed, and a daily one every Stripe customer (a purchase whose
webhooks all failed). Pro lapses three days after the last period the app knows about. A
subscription that can still be paid (unpaid, incomplete) blocks a second purchase and points to
Manage billing, so nobody is charged twice. `python -m scripts.admin billing-sync
<list_id>` re-reads one account by hand, and `admin stats` counts Pro accounts.

Free Pro, for yourself, testers or friends: `python -m scripts.admin comp <email, list id or
account number>` grants it for good, `--plan max` grants Max instead, `--until YYYY-MM-DD` for
a while, and `--off` takes it back. It needs no Stripe and leaves any paid subscription alone
(Max outranks one); `admin stats` counts these as free. Max is not sold yet.
On Railway: `railway ssh --service <your service> -- python -m scripts.admin comp you@example.com`.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for local setup and pull requests.
Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

## License and names

The code is licensed under [MIT](LICENSE).
The names Todo GTD, Notes GTD, Projects GTD, Simple Sites and Common Brain are Will Wilson's
and are not licensed with the code, so a public fork should pick its own names.
