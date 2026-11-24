# Self-hosting

Everything you need to run your own copy. Short version: one container, one worker, a
persistent `/data` volume.

- [Docker](#docker) · [Railway](#railway) · [Locked out](#locked-out) · [Settings](#settings)
- [Files](#files) · [Backups](#backups) · [Restore](#restore) · [Admin tool](#admin-tool)

## Docker

1. Clone the repo and install Docker with Compose.
2. In `docker-compose.yml`, set `PUBLIC_BASE_URL` to the address you'll open. The default,
   `http://localhost:8000`, works on the same machine. Put a public server behind HTTPS.
3. `docker compose up --build -d`. The named volume holds the database and backups at
   `/data`. Check it with `curl http://localhost:8000/healthz`.
4. Open the address and press **Start**. The first visitor owns the server: one account,
   all five apps at `/`, `/notes`, `/projects`, `/sites` and `/brain`.

To upgrade, run the same `docker compose up --build -d`. Don't remove the volume.

## Railway

1. **New project → Deploy from GitHub repo**, and pick your fork. Railway finds the `Dockerfile`.
2. **Add a volume** mounted at **`/data`**. Without it, every deploy wipes the database.
3. **Variables:** `TRUST_PROXY=1`. Set `PUBLIC_BASE_URL` only for your own domain.
4. **Settings → Networking → Generate domain** (or add your own).
5. **Settings → Deploy → Healthcheck path:** `/healthz`.
6. Open the address and press **Start**. Use **Settings → Sign in on another device** for your phone.

Keep one replica (Railway won't allow more with a volume anyway). A deploy restarts the
service, so expect a few seconds of downtime.

Railway's HTTP log records full paths, including agent, capture and sign-in tokens. The
app's own log masks them as `***`.

## Locked out

Set `RESET_CODE` to a long random string, let the service redeploy, open the home page,
choose **Reset access** and type the code. That signs out every browser, revokes program
keys, removes the email, replaces the agent and capture links, and signs you in. Then
remove the variable. This also recovers a server a stranger claimed first.

Or, from the service's shell: `python -m scripts.admin signin-link 1` prints a one-hour
sign-in link and changes nothing else.

## Settings

Only two matter for most people: a persistent `DATA_DIR`, and `PUBLIC_BASE_URL`.

| Variable | Default | What it does |
|---|---|---|
| `DATA_DIR` | `data` (`/data` in the image) | Where `todo.db` and `backups/` live. Must be persistent and writable, or the app won't start. |
| `PUBLIC_BASE_URL` | Railway's domain, else the request's address | The start of every link the app makes. Set it for your own domain. `https://` makes the session cookie `Secure`. |
| `OPEN_SIGNUP` | `false` | `true` lets anyone create an account. Unset runs a single account. |
| `SIGNUP_CLOSED` | `false` | With open signup, `true` stops new accounts (403). Everyone else carries on as normal. |
| `FREE_MAX` | `true` | With open signup, a confirmed email gets the biggest limits. `false` keeps confirmed accounts on the smaller ones (`backend/plans/caps.py`). |
| `RESET_CODE` | unset | Single-account servers only: turns on **Reset access**. Remove it afterwards. |
| `TRUST_PROXY` | `false` | `1` behind a proxy that sets the client-address header itself (Railway does). Never on a server reached directly. |
| `TRUSTED_IP_HEADER` | `X-Real-IP` | The proxy's client-address header. Behind Cloudflare use `CF-Connecting-IP`, and only if the server can't be reached around it. For `X-Forwarded-For` the first entry is used. |
| `NOTES_BASE_URL`, `PROJECTS_BASE_URL` | unset | Give Notes or Projects its own address. Unset, they're at `/notes` and `/projects`. With open signup they live at those paths anyway, and the host becomes an old address that still works. |
| `SITES_BASE_URL` | unset | Simple Sites' own address. Unset, Sites is at `/sites`, and pages and links are served at the main address's top level. |
| `SITES_SHORT_URL` | unset | A shorter address for pages and links (e.g. `https://ss.page`). Needs `SITES_BASE_URL`, which keeps serving every address too. |
| `SITES_CONTENT_DOMAIN` | unset | An isolated domain giving each page its own subdomain, when the person turns that on in Sites Settings. Needs `SITES_BASE_URL`. Make sure `abuse@<domain>` exists. |
| `BRAIN_BASE_URL` | unset | Common Brain's own address. Unset, it's at `/brain`. An account started there gets every app. |
| `RESEND_API_KEY`, `MAIL_FROM` | unset | Both together turn on email: confirming an address and signing in by email. `MAIL_FROM` must be on a domain verified with [Resend](https://resend.com). Mail also needs `PUBLIC_BASE_URL` (or Railway's domain), since a mailed link is never built from a request's address. Without mail, hosted accounts stay on the small limits and are never put away. |
| `SNAPSHOT_INTERVAL_SECONDS` | `3600` | How often a backup snapshot is taken. |
| `SNAPSHOT_AGE_RECIPIENT` | unset | An [age](https://age-encryption.org) public key (`age1…`). Set, every snapshot is encrypted to it and only the encrypted file is kept. Unset, snapshots are plain. See [Backups](#backups). |
| `FILES_S3_ENDPOINT`, `FILES_S3_BUCKET`, `FILES_S3_KEY_ID`, `FILES_S3_SECRET` | unset | An S3-compatible store (R2, MinIO, S3, B2), path-style, for Common Brain's files and Sites' file sites. Unset, Files is off. See [Files](#files). |
| `FILES_S3_REGION` | `auto` | `auto` for R2; MinIO and S3 need a real region. |
| `SITES_FILES_PREFIX` | `sites` | Each deployment sharing a bucket needs its own: a daily pass deletes objects under it that its database doesn't know. |
| `PORT` | `8000` | Railway sets it. |

Keep open and click tracking **off** on the Resend domain (the default), so sign-in links
don't pass through a third party.

## Files

Common Brain's files and Simple Sites' file sites live in an S3-compatible bucket, never
on the volume. Uploads go straight from the browser or program to the store.

1. Make a bucket and a read-write key, and set the `FILES_S3_*` variables.
2. Add a CORS rule allowing `PUT` and `GET` from the app's addresses, with the headers
   `content-type` and `x-amz-checksum-sha256`. For Sites' own page addresses, also allow
   `GET` from `https://*.<content domain>`.
3. Add a lifecycle rule deleting `staging/` objects after a day. Keep it to that prefix.
4. From a checkout with the same variables, run `uv run pytest -m objectstore`. Leave Files
   off if it fails: the quota depends on the store refusing a wrong length or checksum.

Limits: 100 GB self-hosted. Hosted Brain files need a confirmed email, then 100 GB. A file
is at most 5 GB (500 MB from the browser). File sites: 25 MB unconfirmed, 1 GB confirmed or
self-hosted, 1,000 files. Every version counts.
Snapshots don't include file bytes.

Unreferenced Sites files are kept 30 days, then deleted. Signed file links already handed
out keep working until they expire (at most 12 hours), even after an unpublish or takedown.

`python scripts/sites_sync_check.py --link-file <agent link file> <folder>` checks large-site
publishing end to end against a real server.

## Backups

Every hour the app writes a snapshot to `DATA_DIR/backups/todo-<time>.db`. It keeps the last
6 hours and one a day for 7 days. Snapshots pause, with a warning, when free space runs low.

**Encrypt them.** A snapshot is the whole database, readable by anyone who gets a copy. To
encrypt them, run `age-keygen -o key.txt` on your own machine, keep `key.txt` somewhere safe
that is not the server (a password manager, and a printed copy), and set
`SNAPSHOT_AGE_RECIPIENT` to the public key it prints. Snapshots are then compressed with
`zstd`, encrypted, and written as `todo-<time>.db.zst.age`, usually a fraction of the
database's size. They can only be opened with `key.txt`: lose it and they are gone. If `zstd`
or `age` fails, that snapshot fails and is logged; a plain one is never written in its place.
Snapshots taken before you set it stay plain until they age out, and ones an earlier version
wrote as `todo-<time>.db.age` (encrypted, not compressed) still restore. The live database is not
encrypted, since the app has to read it.

They share the volume with the database, so they protect against mistakes, not against
losing the volume. Copy them somewhere else:

- **Pull them hourly** to a machine you control with the [Railway CLI](https://docs.railway.com/guides/cli)
  and a project token (**Settings → Tokens**). Fetch only new files, never `todo.db` itself:

  ```bash
  export RAILWAY_TOKEN=<project token> V=<volume name>
  cd <your backup folder>
  railway volume files --volume "$V" list /backups --json </dev/null | jq -r '.files[].name' |
    grep -E '^todo-[0-9TZ]+\.db((\.zst)?\.age)?$' | while read -r name; do
      [ -e "$name" ] || { railway volume files --volume "$V" download "/backups/$name" "$name.part" \
        --overwrite </dev/null && mv "$name.part" "$name"; }
    done
  ```

  Keep the `</dev/null`s (the CLI reads standard input). Have the job warn you when nothing
  new arrives for a few hours.
- **Turn on Railway's volume backups** (the service's **Backups** tab). They're a second way
  back, not an off-site copy.

## Restore

Run these in the service's shell (`docker compose exec suite sh`, or `railway ssh`, in `/app`).

**Whole database.** Replaces everything, sign-ins and links included:

```bash
cd /data
cp backups/todo-20261004T120000Z.db todo.db.restore
mv todo.db.restore todo.db && rm -f todo.db-wal todo.db-shm
```

An encrypted snapshot is decrypted first, with the private key. Either decrypt it on your own
machine and copy the plain file to the server, so the key never touches the server, or type
the key in there (`-i -` reads it from the terminal, and it is not saved):

```bash
age -d -i - backups/todo-20261004T120000Z.db.zst.age | zstd -d --long=27 -o todo.db.restore
```

For an older `.db.age` file there is no `zstd` step:
`age -d -i - -o todo.db.restore backups/todo-20261004T120000Z.db.age`.

Restart straight away (`docker compose restart`, or **Deployments → Restart** on Railway).
The running app still has the old file open, so anything written between the `mv` and the
restart is lost. Where you can, stop the app first, run the commands, then start it.

**One account.** Puts one account's todos, projects and areas back as a snapshot had them,
keeping its links, sign-ins and everything else. Safe while the app runs, and it takes a
fresh snapshot first:

```bash
python -m scripts.restore_list /data/backups/todo-20261004T120000Z.db --list-id 7
```

For an encrypted snapshot add `--identity -` and type the private key when asked, or
`--identity <key file>`. The snapshot is decrypted into a private folder in `DATA_DIR` that
is removed when the restore ends, and the key is never saved. Or decrypt it on your own
machine and pass the plain file, as above.

`python -m scripts.admin find --link=<agent link>` gives the id.

## Admin tool

There's no admin web page; a page that could see every account would be the best thing on
the server to steal. Run the command-line tool inside the container instead. Changes take
effect at once.

```bash
railway ssh --service <your service> "python -m scripts.admin stats"
```

Anywhere else, run it from the app directory with the app's `DATA_DIR`.

| Command | What it does |
|---|---|
| `stats` | Totals: accounts, todos, sign-ups per day, emails, database and snapshot sizes |
| `lists` | One row per account. Filters: `--email`, `--name`, `--created-after`, `--created-before`, `--unused`, `--limit`; `--show-email` |
| `find --link=<link>` | Which account an agent or capture link belongs to |
| `show <id>` | One account's details; `--content` also prints its titles, and is logged |
| `signin-link <id>` | A one-hour, single-use sign-in link. Nothing else changes |
| `sign-out-all <id>` | Signs out every browser; links untouched |
| `set-email <id> <email>`, `clear-email <id>` | Sets (unconfirmed) or removes the email |
| `disable <id>`, `enable <id>` | Turns an account's links and sign-ins off and back on. Deletes nothing |
| `delete <id> --yes-delete-list-<id>` | Deletes an account for good, after a snapshot |
| `snapshots` | The snapshot files |
| `restore <id> --from <snapshot>` | The one-account restore above; `--identity` for an encrypted snapshot |
| `merge-brain FROM TO --name … --folder …` | Folds a Brain-only account into another as a new brain; `--yes` applies |

Read commands take `--json`. An id can also be the account number shown in Settings. The
tool never prints agent or capture links, hides emails unless asked, and logs every change
(not content) to the `admin_log` table.
