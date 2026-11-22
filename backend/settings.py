"""todo-gtd — everything the environment configures, read at call time.

DATA_DIR            where todo.db and backups/ live (db.py); a mounted volume when hosted
PUBLIC_BASE_URL     the address every generated link starts with (the anchor app's, todo)
<APP>_BASE_URL      another app's own address (apps.py names each variable); a
                    request on its host gets that app, and its links start with it
SITES_SHORT_URL     a shorter address Simple Sites hands its pages and links out at (e.g.
                    https://ss.page); its host serves those and nothing else (main.py)
SITES_CONTENT_DOMAIN  isolated page domain, without a scheme; needs SITES_BASE_URL
SITES_CONTENT_LISTS   while set, only these comma-separated list ids use content hosts
OPEN_SIGNUP         true = hosted, anyone may create a list; default false = one list
SIGNUP_CLOSED       true = hosted, but no new accounts: sign-in and existing accounts work (router.py)
RESET_CODE          self-host only: the secret POST /api/reset accepts
TRUST_PROXY         1 = take the client address from the proxy's header (ratelimit.py)
TRUSTED_IP_HEADER   which header that is; default X-Real-IP
RESEND_API_KEY      with MAIL_FROM and a configured base address, turns sign-in by email on (signin.py)
MAIL_FROM           the sender, on a domain verified with Resend
SNAPSHOT_INTERVAL_SECONDS   how often backup.py snapshots; default one hour
FILES_S3_ENDPOINT   with FILES_S3_BUCKET, FILES_S3_KEY_ID and FILES_S3_SECRET, the S3-compatible
                    store Common Brain's files live in (objectstore.py), e.g.
                    https://<account>.r2.cloudflarestorage.com; unset, Files is off
FILES_S3_BUCKET     the bucket, addressed path-style
FILES_S3_KEY_ID     the store's access key id, with read and write on the bucket
FILES_S3_SECRET     its secret
SITES_FILES_PREFIX  the bucket prefix this deployment keeps Sites files under (default sites); one per deployment
FILES_S3_REGION     the region requests are signed for; default auto (R2's), MinIO and S3 name one
"""

from contextvars import ContextVar

import os
import re
from urllib.parse import urlsplit

from fastapi import Request

from backend import apps


_origin: ContextVar[str] = ContextVar("request_origin", default="")


def old_url(app: str) -> str:
    """A family app's own host on the hosted service: an old address. The app lives at its
    path on the main address; the host keeps answering for the agent links handed out there
    and for the browsers signed in there. "" for every other app, and for a self-hosted
    install, where a configured host stays the app's one address."""
    if app == apps.ANCHOR or app not in apps.FAMILY or not open_signup() or not configured_base_url():
        return ""
    return app_base_url(app)


def moved_to(request: Request) -> str:
    """Where this request's app lives now, when the request came in on its old host."""
    if request.scope.get("app_prefix"):
        return ""
    app = app_for(request)
    return app_url(app) if old_url(app) else ""


def app_url(app: str, request: Request | None = None) -> str:
    """Where an app is reached: its configured address, else its path on the main address
    (a family app's configured host on the hosted service is an old address: old_url).
    With no address configured at all, the main address is the request's own, and only
    when the request came in on the main host: another app's host serves no paths."""
    own = app_base_url(app)
    if own and not old_url(app):
        return own
    if request is None:
        origin = configured_base_url() or _origin.get()
    else:
        origin = configured_base_url() or (str(request.base_url).rstrip("/") if on_main_host(request) else "")
    if not origin:
        return ""
    return origin + ("" if app == apps.ANCHOR else f"/{app}")


def on_main_host(request: Request) -> bool:
    """Any host that is not another app's configured one, the short host or the content
    host: the anchor's, as app_for reads it. A proxy that rewrites Host still reaches the
    apps at their paths, since the links handed out name the configured address anyway."""
    host = request.headers.get("host", "").strip().lower()
    if on_short_host(request):
        return False
    domain = sites_content_domain()
    hostname = request.url.hostname or ""
    if domain and (hostname == domain or hostname.endswith("." + domain)):
        return False
    return not any(
        urlsplit(app_base_url(key)).netloc.lower() == host
        for key in apps.APPS
        if key != apps.ANCHOR and app_base_url(key)
    )


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def open_signup() -> bool:
    return _flag("OPEN_SIGNUP")


def signup_closed() -> bool:
    """The hosted service takes no new accounts (POST /api/lists, the one way one is made).
    A self-hosted server keeps its one-list claim."""
    return open_signup() and _flag("SIGNUP_CLOSED")


def sites_files_prefix() -> str:
    """Where this deployment keeps Sites' objects in the bucket, ending in "/". Every
    deployment sharing a bucket needs its own: the daily reconcile deletes any key under
    it that this database has no row for (sites.reconcile_blobs)."""
    prefix = os.environ.get("SITES_FILES_PREFIX", "").strip().strip("/")
    # A letter first: Brain's keys start with a list id; staging/ is Brain's upload area.
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", prefix or "sites") or prefix == "staging":
        raise ValueError("SITES_FILES_PREFIX must start with a letter, use a-z, 0-9 and -, and not be staging")
    return (prefix or "sites") + "/"


def files_s3() -> dict | None:
    """Common Brain's file store (objectstore.py): endpoint, bucket, key_id, secret and
    region, or None while any of the first four is unset, and then Files is off."""
    cfg = {
        name.lower(): os.environ.get(f"FILES_S3_{name}", "").strip()
        for name in ("ENDPOINT", "BUCKET", "KEY_ID", "SECRET")
    }
    if not all(cfg.values()):
        return None
    return {
        **cfg,
        "endpoint": cfg["endpoint"].rstrip("/"),
        "region": os.environ.get("FILES_S3_REGION", "").strip() or "auto",
    }


def trust_proxy() -> bool:
    return _flag("TRUST_PROXY")


def trusted_ip_header() -> str:
    return os.environ.get("TRUSTED_IP_HEADER", "").strip() or "X-Real-IP"


def reset_code() -> str:
    return os.environ.get("RESET_CODE", "")


def snapshot_interval() -> float:
    try:
        return max(1.0, float(os.environ.get("SNAPSHOT_INTERVAL_SECONDS", "")))
    except ValueError:
        return 3600.0


def configured_base_url() -> str:
    """PUBLIC_BASE_URL, else the domain Railway gave the service, else ""."""
    explicit = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    railway = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{railway}" if railway else ""


def app_base_url(app: str) -> str:
    """An app's configured address, or "" when it has none (the anchor's falls
    back to Railway's domain, as configured_base_url says)."""
    if app == apps.ANCHOR:
        return configured_base_url()
    return os.environ.get(apps.APPS[app].base_env, "").strip().rstrip("/")


def sites_short_url() -> str:
    """SITES_SHORT_URL, the address Simple Sites' pages and links are handed out at,
    or "" (then they are on SITES_BASE_URL, which serves them either way). Only
    while Sites itself has an address."""
    if not app_base_url("sites"):
        return ""
    return os.environ.get("SITES_SHORT_URL", "").strip().rstrip("/")


def sites_content_domain() -> str:
    """The isolated pages domain, without a scheme; off unless Sites is served."""
    if not app_base_url("sites"):
        return ""
    domain = os.environ.get("SITES_CONTENT_DOMAIN", "").strip().lower().removesuffix(".")
    if not domain:
        return ""
    if (
        len(domain) > 253
        or "." not in domain
        or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in domain.split("."))
    ):
        raise ValueError("SITES_CONTENT_DOMAIN must be a DNS domain without a scheme or port")
    return domain


def sites_content_allowed(list_id: int) -> bool:
    """An unset rollout gate allows everyone; an empty or invalid gate allows nobody."""
    allowed = os.environ.get("SITES_CONTENT_LISTS")
    return allowed is None or str(list_id) in {part.strip() for part in allowed.split(",")}


def on_short_host(request: Request) -> bool:
    url = sites_short_url()
    return bool(url) and request.headers.get("host", "").strip().lower() == urlsplit(url).netloc.lower()


def app_for(request: Request) -> str:
    """The middleware-selected prefix, else a configured host, else the anchor."""
    if request.scope.get("app_prefix"):
        return request.scope["app_prefix"][1:]
    if on_short_host(request):
        return "sites"
    host = request.headers.get("host", "").strip().lower()
    for app in apps.APPS:
        url = app_base_url(app) if app != apps.ANCHOR else ""
        if url and urlsplit(url).netloc.lower() == host:
            return app
    return apps.ANCHOR


def base_url(request: Request) -> str:
    """What every generated link (agent, capture, sign-in) starts with: the
    request's app's configured address or its path on the main address (falling
    back to the request origin when unconfigured). Sign-in mail
    never uses the fallback: see signin.py. On an old host (old_url) links keep
    starting with that host, so nothing handed out there changes."""
    if on_short_host(request):  # only pages are served there (main.py), so only for _same_origin
        return sites_short_url()
    app = app_for(request)
    if not request.scope.get("app_prefix") and (old := old_url(app)):
        return old
    return app_url(app, request)


def cookie_secure() -> bool:
    """Whether the session cookie is ``Secure``: when the configured address is
    https. The app cannot tell from the request — behind Railway's proxy it sees
    plain http — and locally (and in tests) there is no https at all."""
    return configured_base_url().startswith("https://")
