# todo-gtd

A no-login GTD todo list that AI tools read and write. Open source (MIT). Hosted at
todogtd.com with open signup; self-hosters run the same image with one list. See `README.md`
for settings, deploy, backups and restore.

## Layout

```
backend/
  main.py        app, lifespan (snapshot + cleanup loop), /healthz, router mounts; _AppPrefix
                 selects apps without configured addresses, and family apps on an old address,
                 on the main host only
  settings.py    shared environment variables; app_base_url (configured), app_url (reachable),
                 app_for (host or prefix), on_main_host, _origin (request origin for worker link builders);
                 old_url (a family app's own host on the hosted service), moved_to
  apps.py        the suite registry: each app's title, address variable and content tables; FAMILY
                 (Todo, Notes, Projects: together at the main address); off_message
  db.py          SQLite connections, schema, transaction() (write lock + BEGIN IMMEDIATE)
  common.py      constants, plan-aware caps_for (the per-list caps), validators, next_due,
                 the one clock (utcnow)
  models.py      Pydantic request models
  service.py     todo / project / area CRUD, recurrence spawn, caps (_check_cap), context rename
  boards.py      Projects GTD: boards (a "project" in its UI) and each one's Card Table: Basecamp's
                 fixed Triage / Not now / Done columns (`kind`) around ordered work columns (colour,
                 On Hold, soft card limit), cards with Trello's fields (assignees, labels, start/due,
                 cover; in Done = complete), labels; integer positions renumbered per move; a card
                 version refuses stale edits
  board_routes.py  the board API under /api/app (same owner, X-List and no-store rules)
  recordings.py  Projects GTD as Basecamp: everything in a project but its card table is a recording
                 (message, to-do list, group, to-do, subtask, comment, folder, document, link, event,
                 check-in question, answer) with comments, boosts, the activity trail (events),
                 bookmarks; the project's dock of tools and its page; a Docs & Files folder; the
                 Needle and Hill Charts (the person's to set, never an AI tool's); Spotlight; the archive;
                 copies, repeating to-dos, drafts that post themselves (publish_scheduled, each minute);
                 Chat (chat lines; one trail row per line on the project) and External links (doors)
                 @mentions (data_mentions, mentions_of) and Change dates (shift_dates on a list or group);
                 Card Table wormholes (type 'wormhole': another project's column, at most 4) and the
                 To-dos Markdown import (import_todos)
  schedules.py   the Calendar (events with their repeats, plus what is due), check-ins due and their
                 answers by day, the Lineup of projects with dates
  reports.py     the views across projects: Everything, Reports (overdue, upcoming, unassigned, added
                 and completed, someone's tasks, Mission Control, the Hilltop View) and search
  templates.py   project templates: a project marked as one is copied into a new project, dates moved
  samples.py     the sample projects a new account starts with (Home seeds them once on an empty
                 account), and turning them off (archived) and on; they don't count toward the cap
  automation.py  Card Table automation (Trello's): rules fired after card writes, card and board
                 buttons, due-date and scheduled rules (the minute loop: due_tick, scheduled_tick);
                 a rule's writes never fire another rule
  inbox.py       New for you (Basecamp 5's sidebar): unread per item worked out from the activity trail
                 against people.read_at and `readings`, mark read / unread / all, Bubble Up, due
                 reminders, "Don't notify me" (readings.muted: an item, a card or a whole project);
                 My Tasks' Up Next, My Drafts, My Boosts
  people.py      the account's people: me, each AI tool that has written (by client name), people
                 added by name; actor_in turns a write's source into its author
  project_routes.py  the Basecamp API under /api/app (home, people, projects, items, activity, …)
  projects_agent.py  Projects GTD's Basecamp tools on the agent link: project_open, item_*,
                 todo_complete, comment_add, activity_list; PROJECT … PEOPLE commands, its guide part
  sites.py       Simple Sites: pages (HTML/Markdown) and short links at <SITES_BASE_URL>/<name->code;
                 caps (site_caps_for), one update path, lookup and render for pages.py, view
                 counts (count_view in memory, flush_views each minute; shown with Pro only); page data
                 (visitor/owner records, indexed fields, quota counters, read cursors and browser Clear)
  sites_agent.py Simple Sites on the agent link: site_*/link_create tools, SITES … REPUBLISH and SITE_SYNC commands
  paid/billing.py Pro, the paid plan (sold through Sites, covers the account): Stripe Checkout
                 (Managed Payments), the Customer Portal, sync(), catch_up() and the hourly loop
  paid/caps.py   paid limits and plan column names/DDL; no app imports
  paid/plans.py  plan derivation, feature gates and plan wording
  paid/routes.py billing routes and the session plan block
  paid/settings.py payment service environment variables
  paid/admin.py  comp, billing-sync, billing checks and admin plan reports
  paid/smoke.sh  checks the hosted service's addresses after a deploy, without credentials
  site_host.py   isolated content hosts: body pages, file manifests, text cache, password passes and takedowns
  site_routes.py the Sites API under /api/app, with browser-only deletion of pages and their records
  notes.py       Notes GTD: notes (markdown body, #hashtag tags derived from it, colour, pin); a
                 version refuses a stale rewrite; edit (exact string once) and append need none
  note_routes.py the notes API under /api/app (same rules as board_routes.py)
  notes_agent.py Notes GTD on the agent link: note_ tools, the *_NOTE commands, its guide part
  brain.py       Common Brain: brains and their owner-set rules/AI policy; ordered grants, caps,
                 atomic cross-brain moves; memories (short facts every AI loads; the person locks them) and
                 pages (Markdown/HTML at a path); every write a version (history, restore, the
                 what-changed feed, each AI's catch-up); the AI cap and the email nudge; secrets
                 blanked; Forget; curator queues, probe evals, contact-drop warnings and snapshot exports.
                 Pass labels and reasons in history. No AI runs here, ever
  brain_import.py Markdown zip import: dry run, resumable chunks and passes, files, archive missing
  brain_routes.py the brain API under /api/app, with Forget (POST …/forget)
  brain_agent.py Common Brain on the agent link: brain_ tools (MCP only), and its paragraph of the
                 instructions, built from the carried brains (it leads, with labelled locked memories);
                 _scope is the grant, _split/_place map blended paths; one-time setup; curator
                 eval and signed-in export links, pass labels on writes
  lists.py       list rows, the account number, the agent and capture tokens, rotate, claim, reset,
                 email (+ confirmed stamp),
                 weekly-review stamp, the apps turned on (apps_on, served, set_app_in), the AI
                 tools that have called (seen_ai, ai_tools: the Your AI page's status)
  sessions.py    the session cookie: one hashed row per signed-in browser, ≤20 per list, revoke, expire
  keys.py        program keys (kind=key, cb_…, Bearer only) and staff links (kind=link, path only):
                 named, hashed, shown once, revoke; ordered brains, scope (brain | all), access
                 (read | write), single-brain key write folders; separate key and staff-link caps
  api_v1.py      the REST API for program keys: GET /api/v1, POST /api/v1/tools/{name} through
                 mcp.call_tool; _authorize, the one check for its own Brain routes
  lifecycle.py   the idle lifecycle of a hosted, unconfirmed list: enabled(), state() (active / archived
                 at 60 idle days / removed at 180), derived from the last use, never stored
  connect.py     device connection codes: hashed poll token, browser approval and one-use agent link delivery
  signin.py      sign-in links: one hour, single use, hashed; mailed (httpx to Resend) to confirm an email or
                 to a confirmed one, or shown as a QR; redeem (a mailed link confirms the address)
  router.py      /api: session_owner/active_owner (cookie, X-List, same-origin; A refuses a put-away list),
                 build_router on /api/app, links, account (email, sign-in link, apps on/off, restore,
                 sign out),
                 capture, create, sign in, reset
  mcp_server.py  the agent link: MCP tools over service.py and boards.py (board_/card_), each tagged
                 with its app and read-only flag; _AppsOn offers only the apps turned on, narrowed by a
                 program key (refusal); token resolution, the four addresses
  agent_cmd.py   Agent Commands on the agent link: the guide (HELP) and the ?cmd= commands, each app's
                 registered with register_app (todo's, and the boards': BOARDS, BOARD, CARD, CREATE_BOARD, *_CARD)
  pages.py       SPA shell, /app (signed in) or 303 /, manifests, /signin, retired /w, one-segment catch-all;
                 _site_host keeps visitor routes top-level on the Sites or fallback main host
  ratelimit.py   IPRateLimiter, client_ip(), the wrong-token guard
  files.py       Common Brain's files: reserve, done (claim, copy, commit), links, Forget, the sweeper
  storage.py     the shared account pool: Brain files and Sites blobs, reservations and tombstones included
  objectstore.py hand-signed SigV4 (no SDK) for the S3-compatible file store: presigned PUT/GET, HEAD, copy, DELETE, streamed GET and paged inventory
  backup.py      snapshots and pruning
  cleanup.py     deletes never-used lists (the only hard delete), with their sessions, sign-in links, keys
  logscrub.py    replaces token path segments with *** in every log record
  tests/         pytest, real temp SQLite file per test
scripts/sites_sync_check.py  stdlib large-deck sync check: agent link from a file or env, never printed
scripts/restore_list.py   one-list repair from a snapshot
scripts/admin.py          the operator's command line (stats, find, disable, delete, …); README "Administration"
frontend/        Vite + React 19 + Tailwind 4; builds into backend/static. One bundle; the
                 gtd-app meta (core/app.ts) makes /app the todo app, apps/projects-gtd or
                 apps/notes-gtd. Each app's colours: pages._shell stamps <html data-app>, and
                 index.css sets that app's brand-* and band-* tokens under [data-app="…"]
                 src/paid/ holds everything about paid plans (the plan card, prices, billing
                 calls, policy links); nothing outside it names a plan (paidBoundary.test.ts).
                 public/paid/ holds the policy pages, served at /terms.html … only with open signup
docs/agent-commands.md   the generic Agent Commands spec the guide links to
Dockerfile       frontend build, then Python 3.12 + uv, one uvicorn worker
```

The MCP server is FastMCP, stateless, JSON responses, one app behind four plain routes
(`/link/<token>`, the shape shown to users; `/mcp/<token>`, `/<token>/mcp`, `/mcp` with a
bearer header) that resolve the token into a
contextvar and forward with the path rewritten. Its lifespan is entered inside the app's.
Tools are hand-written, thin calls into `service.py`. The same routes also answer Agent
Commands (`agent_cmd.py`): any request with `?cmd=`, and a plain GET/HEAD whose `Accept`
lacks `text/event-stream`, which gets the guide. Both run after the token is resolved and
the call budget charged; every other request goes to FastMCP untouched.

## Rules that are easy to break

- **Brain content is scoped by `brain_id`.** An AI request's brains come only from
  `brain_agent._scope()`; account-level counts use `list_id`. Stored ordered grants are
  validated against the account, archived brains are dropped, and an empty grant never
  falls back to another brain. `_resolve` returns the grant from its worker thread;
  `_serve` and REST's `_as` set/reset `_brains`. Staff links resolve only from the path and
  keys only as Bearer. Every content mutation checks `brain._policy_in` inside its own
  transaction, including imports, moves, restores and an upload's final commit. Reading's
  bookkeeping is allowed on read-only brains. Only the owner changes policy and grants;
  the main link's one-time `brain_setup` is the sole AI exception.

- **Never answer 401 on a token route.** An unknown, rotated or wrong-kind token is a 404.
  AI clients treat a 401 as "start sign-in" and go looking for OAuth. Refusals are 403, 404,
  409 or 429, and no response carries `WWW-Authenticate`. Two exceptions: `/mcp` with a
  bearer header (no token in the path) answers 401 with a bare `WWW-Authenticate: Bearer`, and
  the browser-only `/api/app/*` answers 401 with no `WWW-Authenticate` when there is no live
  session (the app then goes to `/`). Every `/.well-known/...` path and `/register`,
  `/authorize`, `/token` stay 404. The REST API (`/api/v1`) refuses a missing, unknown or
  revoked program key with 403 `{error}`, never 401.
- **Every `/api/app` request but `GET /session` carries `X-List`** naming the list the session
  call returned; any other value is 409 `{list_changed}` and the app reloads. That is the only
  thing that stops a sign-in in one tab from writing into the list another tab shows. Every
  non-GET there, and create, redeem and reset, passes `router._same_origin` (403 otherwise).
  Raised refusals pass `headers=_NO_STORE`: an exception's response does not inherit headers.
- **A valid token is always served.** Only a MISS is charged to the per-address wrong-token
  bucket, and only misses get 429 when it is empty (`ratelimit.wrong_token_status`). Never
  check that bucket before resolving the token. Program keys follow the same rule.
- **Program keys travel only as `Authorization: Bearer`.** `mcp_server._resolve` resolves a
  `cb_` token only as the bearer; in a path it is an unknown token (404). A key's name labels
  its writes (`_client_name`) and never grants anything: a name that normalises to "you" is
  refused, and `brain_agent._by` keeps its guard. Every check of what a key may call is
  `mcp_server.refusal` (app and scope, read access, `FOLDER_KEY_TOOLS`), used by `_AppsOn` and
  by REST before the call. A folder-limited key passes `restricted` to every brain.py read and
  write it reaches, so a page with `confidential: true` in its frontmatter
  (`brain_pages.confidential`, set by `_save_page` on every write) is never shown to it; a new
  read or write of pages that such a key can reach must take `restricted` too. REST calls tools
  only through `mcp.call_tool` with the contextvars set and reset (`api_v1._as`), never a
  second copy of a tool.
- **No delete tool and no link tool in the MCP server, or in Agent Commands; `ARCHIVE` is
  status `dropped`.** Tools and commands never take a list id, `source` or `source_client`;
  the handler reads the list from the contextvar (commands: from the resolved token) and
  sets provenance itself. Every tool has a title and explicit hints. A command that writes
  is POST only, so a GET never changes anything.
- **One agent link, the apps turned on.** `lists.apps` (JSON) holds each account's apps;
  `lists.apps_on` keeps only those this server serves (all registered apps, on their own host
  or a main-host path). A new
  app's tools pass `_tool(app=...)`, its commands go through `agent_cmd.register_app`, and its
  paragraph of the instructions is `mcp_server.INSTRUCTIONS[key]`; nothing else checks the
  switch. An off app's tools are absent and refused (`_AppsOn`), and its commands answer 400
  with `apps.off_message`, never 404 or 401. Off never touches data or the browser API.
  Creating a list on an app's host or path, or redeeming a sign-in link there, turns that app on.
  New self-host accounts start with all five on; their agent link stays at the main address.
  A new hosted account made in a family app (`apps.FAMILY`) starts with those three, in Sites
  with Sites alone, in Brain with all five. An existing account's apps never change by themselves.
- **On the hosted service a family app's own host is an old address.** With open signup and a
  main address configured, Notes and Projects live at the main address's `/notes` and
  `/projects`: `settings.old_url` names their configured hosts, `app_url` names the paths, and
  every link built on the main host uses the paths. The old host keeps answering. `base_url`
  on it is still that host, so the agent links, capture links, guide and `_same_origin` check
  there are what they were, and a signed-in browser keeps working there (`/api/config` says
  `moved`, and the app bar offers the way over). Only a signed-out page request is sent on,
  with 303, never 301 or 308; token routes and `/signin/<t>` are never redirected. Without
  open signup nothing changes: a configured host stays that app's one address.
- **Exactly one worker.** `db.transaction()` is a process-wide lock plus `BEGIN IMMEDIATE`
  around each whole read-check-write sequence. A second worker or replica breaks the caps,
  the first-list claim, rotation and sign-in redemption. Every write goes through
  `db.transaction()`; a helper that must join a caller's transaction takes `conn` and ends in
  `_in` (`sessions.create_in`, `signin.issue_link_in`).
- **Nothing is deleted.** No DELETE routes, no delete functions in `service.py` or
  `lists.py`. Archiving is status `dropped`. `cleanup.py` is the one exception in the app
  and only touches lists with no content at all; `files.py`'s sweeper is the same kind: it
  deletes tombstones (`abandoned`, `forgotten`), rows that hold only the keys of bytes still
  to delete, after deleting those bytes. No store call runs inside `db.transaction()`. The operator's `scripts/admin.py delete`
  is the one hard delete of real content, behind a typed confirmation flag. Simple Sites is
  the one exception in the web app: `DELETE /api/app/sites/{id}` lets the
  person delete a page or link, because stored pages cost money.
  `DELETE /api/app/sites/{id}/data` also clears a page's records, for the person only.
  A site's zip downloads through a one-use, one-minute ticket from `POST /api/app/sites/{id}/zip-link`
  (`GET /api/zip/<ticket>`, in logscrub's token paths; a miss is a wrong link, never 401).
  Agents only unpublish pages and never delete records.
  Simple Sites also deletes a whole unconfirmed site after it has been expired for 30 days.
  The daily deletion rechecks expiry and the unconfirmed
  email inside the same transaction; blobs are left for GC.
  Common Brain's Forget is the other: `POST /api/app/brain/…/forget`
  removes a memory or page with its whole history, for the person in the browser only.
  An agent archives, or hands over `brain_forget_link`, a link to the app that grants nothing.
- **Pro is derived, never set.** `paid/plans.of` reads `lists.plan_status` + `plan_until`,
  which only `paid/billing.sync` writes, from Stripe's current subscriptions of the account's own
  customer. Never set Pro from a single webhook event (order and duplicates vary), never
  from metadata, and never by hand outside `scripts/admin.py billing-sync`. The one other
  way in is the operator's free grant, `lists.pro_comp_until` + `comp_plan`, set only by
  `paid/admin.py comp`. Max exists only as that grant (`paid/plans.of`), and
  outranks a subscription. Every SELECT that feeds `paid/plans.of` names
  `paid/caps.PLAN_COLUMNS`. Every cap function takes `plan`; a new cap check passes
  `paid/plans.of(row)` like the others.
  Stripe answers and webhook bodies carry the customer's email: never log them.
- **Simple Sites pages on the app and short hosts are always served sandboxed.**
  `pages._site` answers on those hosts, or at the main host's top level when Sites has no
  configured address; visitor pages, short names, data and unlock never answer under an app prefix,
  with `sites.SANDBOX` (CSP sandbox without `allow-same-origin`), so a page's script runs in a
  blank origin and cannot use the visitor's session. Never add `allow-same-origin`, and never
  serve unsandboxed content there, whatever the configuration. Only the isolated content
  host below is exempt. A miss there is a wrong link (`wrong_token_status`).
  A locked page (Pro, `sites.password_hash`) answers its form with 403 until the visitor's
  `sp_<code>` pass checks out (`sites.unlocked`: expiry + HMAC keyed by the hash); every
  try at `/<address>/unlock` is charged to `ratelimit.password_limiter` before any hashing,
  and the hash never appears in an answer (`_view` turns it into `locked`).
- **The isolated Sites content domain never reaches the app.** `site_host.SiteHost` is
  outside `_ShortHost` and answers every path and method under `SITES_CONTENT_DOMAIN`
  itself: no app, sessions or MCP. `SITES_CONTENT_LISTS`, while set, gates canonical
  host addresses, old-address redirects and host lookups. Legacy data pages retain their
  sandboxed path until content is replaced; switching data on or off never moves them.
  Host pages use `Origin-Agent-Cluster: ?1`, `nosniff`, `noindex, nofollow` and
  `Referrer-Policy: strict-origin-when-cross-origin` (needed by YouTube). No service workers:
  `Service-Worker: script` is 403. Passwords use only the `__Host-ss-pass` cookie (Secure,
  HttpOnly, Path=/, SameSite=Lax), checked before conditional responses; unlock posts are
  same-origin checked and use the existing password limiter and hashing slots.
  File manifests serve text, scripts, styles, SVG, wasm and fonts same-origin (a bounded
  hash cache up to 10 MB per file; bigger files stream). Media redirects with 302/no-store
  to an inline presigned GET lasting 12 hours. Paths decode exactly once, rejecting encoded
  slashes, NUL and traversal. SITE_SYNC/site_sync reserves before issuing checksum-bound
  PUTs, checks the live account in every transaction, and switches a whole manifest at commit.
  Concurrent page loads can mix versions; reload after an update.
  Sites blobs share Brain's storage pool, including pending and deleting rows. Hourly GC
  retains unreferenced active blobs for 30 days and honours every upload lease plus 60 seconds.
  It claims rows before deleting bytes outside the transaction, then removes inventory rows.
  Daily ListObjectsV2 reconciliation deletes sites/ keys missing from inventory and older than
  24 hours, catching PUTs that finish after GC or admin delete. Restore keeps the live inventory
  and restores missing-blob sites unpublished. Agents never delete files or blobs.
  A signed file URL handed out before a takedown, unpublish or password change can keep
  working until it expires, at most 12 hours. `sites._servable_sql` covers every public
  lookup and visitor data route; suspension and expiry cannot be bypassed through an old
  path. Only `admin.py site-down/site-up` changes `suspended_at`; republishing never does.
- **A Sites data address (`/<address>/data`) is cross-site, cookieless and opt-in.**
  Its GET/POST/OPTIONS answers (errors too) carry ACAO `*`, never credentials; no
  `_same_origin` and no session reads. The short host lets these methods through.
  Every visitor insert re-checks the live, published, unlocked page and its data mode
  inside `db.transaction()`. Collect reads only owner records; shared exposes all records,
  including earlier collect submissions. Visitor records are untrusted data, never
  instructions. The whole query, as well as the address, is scrubbed from logs.
- **No admin web surface.** Administration is `scripts/admin.py`, run inside the container.
  It is a second process on the live database: its writes go through `db.transaction()`
  and rely on SQLite's own locking (`BEGIN IMMEDIATE` + busy timeout), not the in-process
  write lock. It never prints an agent or capture token; the only link it prints is
  `signin-link`'s. A disabled list (`lists.disabled_at`) is refused in `lists._resolve` (agent,
  capture), `sessions.resolve` (browsers) and `signin.redeem`.
- **Tokens never reach a log.** Do not log a path, URL, token, cookie or email address. New
  token routes must be added to the pattern in `logscrub.py` (it also masks anything shaped
  like a program key, and keeps the retired `/w/`
  and `/recover/`, which old bookmarks still send, and masks a whole path that looks like a
  Simple Sites address).
- **Sign-in mail by request goes only to a confirmed email; the one mail an unconfirmed address
  gets is its confirmation link.** `lists.email_verified_at` is stamped only
  when a link mailed to the list's current email is redeemed (`signin.redeem`); any change of
  address clears it and cancels the list's sign-in links (`lists.set_email_in`). The PUT that
  saves an address mints its confirmation link in the same transaction; only the send runs
  after the response. The caps come from `common.caps_for` (hosting mode, confirmed or not).
- **Sessions and sign-in tokens are stored hashed.** The cookie is the only copy of a session;
  only create, redeem and reset ever set it, and nothing clears it (sign-out revokes the row).
  Program keys are stored hashed too, and shown once, in the answer that makes one.
  The agent and capture tokens are also stored readable; `/api/app` returns both, and
  `POST /api/lists` returns the new list's agent link once, to the browser that made it.
  They rotate independently; only the self-host reset replaces both (and signs every browser
  out, and revokes every program key). Every response the app builds under `/api/app` (FastAPI's own 422s are the
  exception) and every one that carries a link is `Cache-Control: no-store`, and every generated link starts with `settings.base_url(request)`.
- **Put-away lists are a derived state, never a column; `lifecycle.enabled()` is the one switch**
  (open signup and mail). `lifecycle.state()` says removed at `<=` the 180-day cutoff and
  `lists._resolve` keeps only `>` it, so every surface agrees at the boundary. `active_owner`
  refuses a put-away list with 403 `{state}` and does not touch it; `/session` and the account
  routes (`session_owner`) work in every state, because the put-away page needs them. Agent and
  capture calls on an archived list are served and touch it, which brings it back.
- **The change counter is the database's job.** Triggers (`db._rev_triggers`) add one to
  `lists.rev` and stamp the row's `rev` on every insert or update of a todo, project or area;
  `service.changes` (the `CHANGES` command, `todo_changes`) pages by it and relies on a rev
  belonging to one row. Never write `rev` from code, and never remember who has synced: each
  tool keeps its own number. The same triggers stamp `lists.changed_at` with the database's
  clock; `service.changes_count` (`CHANGES_COUNT`, `todo_changes_count`) reads the two.
- **Which AI tools have called, and when, is kept for the person's screen only.**
  `lists.seen_ai` writes `ai_tools` (a row per account and name, at most once an hour) after a
  call that succeeded: an MCP initialize, a tool call whose result is not an error, or a
  `?cmd=` command answered below 400. Never a request with an `Origin` header (a web page is
  not an AI tool), tool discovery or the bare guide. It runs after the work, off the event
  loop, never inside another transaction. It is not sync state (the rule above still holds).
  The name is the tool's own untrusted claim: cleaned by `common.clean_source_client`, shown
  as text, never logged, and it grants nothing. A stamp that fails is logged and swallowed,
  because the call it records has already been answered for. The table is account bookkeeping,
  not content: in `admin._LIST_TABLES` and `cleanup.py`, out of `apps.content_tables()`, and its
  rows cascade with their list, so a version that does not know the table can still delete one.
  A REST call reaches the tools without the HTTP request: `api_v1._as` passes its `Origin` on.
  Messages name the account page through `apps.settings_page` (Settings in Todo, Notes and
  Projects; Connect in Simple Sites and Common Brain).
- **Schema changes** go in `db._migrate` as idempotent steps (`CREATE TABLE IF NOT EXISTS`
  does not alter a table that exists, and the live database does).
- **One place decides the client address:** `ratelimit.client_ip`. Do not read
  `request.client` or a forwarded header anywhere else, and do not turn on uvicorn's
  `--proxy-headers`.
- `pages.router` ends in a catch-all that is one path segment deep, so it cannot shadow
  `/api/...` or `/mcp/...`. Only the `/<token>/mcp` route is registered after it, so that
  route can never shadow an existing one.
- **The short host (`SITES_SHORT_URL`, e.g. ss.page) serves page and link addresses only.**
  `main._ShortHost` lets through `GET`/`HEAD /<address>` and `POST /<address>/unlock`, plus
  `GET`/`POST`/`OPTIONS /<address>/data`. One-segment short names resolve to link redirects
  while the account has a paid tier or its 30-day grace has not passed. It sends every other
  GET to the same path on `SITES_BASE_URL`, and 404s the rest, so no app, API,
  agent link, sign-in or session cookie ever answers there. `sites.address` hands out the
  short host; `SITES_BASE_URL` keeps serving the same addresses.
- Deliberate shortcuts are marked `# simplification: <the ceiling and the way up>`.

## Working here

- Worktrees go in `.claude/worktrees/`, one branch per worktree, branched from `master`.
- `scripts/check.sh` runs every CI check locally (ruff, pyright, pytest, ESLint, Prettier, the
  frontend tests and build); run it before a PR. One suite: `uv run pytest backend/tests`, or
  `npm test` in `frontend/`. `backend/paid/smoke.sh` checks the hosted service after a deploy.
- Formatting is ruff format and Prettier. Claude Code's hook formats each file it saves; CI
  refuses anything unformatted.
- Tests default to `OPEN_SIGNUP=true` (see `conftest.py`); one-list behaviour is in `test_hosting.py`.
- Run locally: `OPEN_SIGNUP=true uv run uvicorn backend.main:app --workers 1 --reload`,
  plus `npm run dev` in `frontend/`.

## Review guidelines

For every reviewer on every PR, on top of the rules above.
- P1: any change to `.github/`, `scripts/check.sh`, the ruff, pyright, ESLint or Prettier
  settings, or `.claude/hooks/`, unless the PR says why. These are what keep CI honest.
- P1: a deleted, skipped or weakened test, or a new `noqa`, `type: ignore`, `pyright: ignore`,
  `eslint-disable` or `ts-ignore`.
- P1: a break of any rule under "Rules that are easy to break".
- Skip style and formatting: the formatters own them.
