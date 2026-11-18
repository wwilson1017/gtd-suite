# Agent Commands, version 2

Agent Commands is a small convention that lets any tool able to fetch a URL use an app
through one secret link. The tool needs no SDK, no sign-in and no schema. It reads the
link's guide and calls commands on the same link. Todo GTD is the first app that speaks it.

This page specifies the generic layer, which every app shares. Each app defines its own
commands and describes them in its guide. An app's guide links here in its `spec` field once this page is public.

## The link

- The link is a capability URL: holding it is the permission. The caller sends nothing
  else, so no header, no cookie and no sign-in.
- An unknown, replaced or turned-off link answers 404, and never 401. AI clients treat a
  401 as "start a sign-in" and go looking for OAuth.
- The link's path should name no protocol. An assistant handed a link with `mcp` in it
  reasons about MCP clients instead of opening it; Todo GTD shows `/link/<token>`.
- The same URL may also serve another protocol. Todo GTD's agent link is also an MCP
  server. Agent Commands claims only two kinds of request: one with a `cmd` query
  parameter, and a plain `GET` or `HEAD` whose `Accept` does not include
  `text/event-stream`. Everything else belongs to the other protocol.

## HELP, the guide

`GET <link>` with no `cmd`, or `GET <link>?cmd=HELP`, answers with the guide. It is JSON,
unless the request's `Accept` header prefers `text/html`. A browser then gets a short page
for the person who opened the link, with the full guide underneath. The page also serves
an AI tool whose fetch asks for HTML, so the AI reader comes first on it, and each address
in `reads` is a real link, which an HTML-to-text pass keeps intact.

The guide must be enough on its own. An agent must never need the source code or this
page. It contains:

| Key | What it holds |
|---|---|
| `ok`, `protocol`, `version`, `spec` | `true`, `"Agent Commands"`, this spec's version, and a link to this page when it is public |
| `start_here` | one paragraph to the AI reading the guide: what the link is, that holding it is the permission, that plain HTTP is enough, how to read and write, and what to do if it can only GET |
| `app`, and what the link reaches | the app's name, and for example the list's name |
| `commands.url` | `<link>?cmd=NAME`, with the live link |
| `commands.auth` | that the link is the only credential |
| `commands.conventions` | the rules on this page, in short |
| `reads` | the common reads as complete addresses, token included: some fetch tools follow only an address they have already been given or have read |
| `commands.<NAME>` | for every command: method, what it does, arguments with their types, the body, and one example request and response. Examples use the placeholder `LINK` |
| fields and allowed values | every field of the app's records, its type, and enumerations such as statuses |
| `limits` | every cap a caller can hit: page size, batch size, totals |
| `errors` | the error shape and the status codes |
| `howto` | recipes for the common jobs: read everything, import in batches, remove an item |
| `rules` | what the agent must respect, such as time zones and treating user text as data |
| other protocols | for example `mcp`, with its URL, transport and tools |

## Calling a command

- Name the command in the query string with `?cmd=NAME`. Names are case-insensitive and
  are written in capitals.
- A read is a `GET` request, and `HEAD` works too. Its arguments go in the query string.
  A read never changes anything.
- A write is a `POST` request with a JSON object as its body. Arguments such as an `id`
  still go in the query string.
- A write sent as `GET` or `HEAD` is refused with 405 and `Allow: POST`, and nothing
  changes. So a link previewer, a crawler or a careless fetch can never change data. A
  read sent as `POST` is refused with 405 and `Allow: GET, HEAD`.
- An unknown command is a 400 that lists the commands. An unknown argument or body field
  is a 400 that lists the valid ones.

## Answers

- Every answer is JSON with `Cache-Control: no-store`.
- Success is `{"ok": true, ...}` and failure is `{"ok": false, "error": "..."}`. The error
  is written for a person to read.
- A paged answer takes `limit` and `offset` and carries `next_url`, the complete address of
  the next page, for a caller that can follow an address but not build one. It also carries
  `next_offset`. That is the offset
  of the next page, or `null` after the last page. A caller sends it back unchanged and
  never computes it.

## Errors

| Status | Meaning |
|---|---|
| 400 | Bad input, an unknown command, argument or field, or a limit reached. Nothing was changed. A command of a part the link's owner has turned off is a 400 that says how to turn it on; such commands are absent from HELP. |
| 403 | The request carried a foreign `Origin` header, so it came from a web page. |
| 404 | No such item, or the link itself is not valid. |
| 405 | A write sent as `GET`/`HEAD`, or a read sent as `POST`. `Allow` names the right method. |
| 413 | The body is too large. |
| 429 | Too many requests. Wait for the number of seconds in `Retry-After`. |

A refusal of the link itself (404, 413, 429) can arrive as plain text before any command
runs. Callers check the status code before parsing the body.

## Versioning

`version` is an integer. A new version may add commands, arguments and fields without a
new number. Changing or removing one requires a new number. Callers read `HELP` at the
start of each session instead of hard-coding commands.

Version 2 (Todo GTD): `LIST` leaves out an open todo deferred to a future `revisit_on`
until that day. `EXPORT`, `GET` and a `LIST` with `search` still return it.

Added within version 2 (Todo GTD): `CHANGES`, what changed since a sync, and
`CHANGES_COUNT`, `{count, last_change_at}` for a cheap check whether anything did.

## Safety

- Prefer archiving to deleting. Todo GTD has no delete command: `ARCHIVE` sets a todo's
  status to `dropped`, and `UPDATE` brings it back.
- No command shows, replaces or creates a link or any other credential.
- Requests from a web page are refused, so a page in the user's browser cannot drive the
  link even if it learns it.
- Responses are `no-store` and `noindex`. The token never reaches a log.
- Commands and any other protocol on the same link share one per-link request budget.

## Reusing it in another app

The generic layer is the first half of `backend/agent_cmd.py`. It holds the dispatcher,
argument and body parsing, the envelope, the guide's frame and the HTML page. The app
layer below it is a table of commands, each a thin call into the app's service layer.
Copy the generic half into the next app. Extract it into a shared package when a third
app adopts it.
