"""Shared fixtures: every test runs against a real temporary SQLite file."""

import datetime

import pytest
from fastapi.testclient import TestClient

from backend import apps, common, db, lists, ratelimit, sessions, settings, signin

# What a browser sends with every request from the app's own pages
# (router._same_origin).
BROWSER = {"Sec-Fetch-Site": "same-origin"}


@pytest.fixture()
def todo_db(tmp_path, monkeypatch):
    """Point the database at a temp directory with a live schema."""
    from backend.tests.paid.helpers import clear_settings

    clear_settings(monkeypatch)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    for name in (
        "PUBLIC_BASE_URL",
        "RAILWAY_PUBLIC_DOMAIN",
        "RESET_CODE",
        "TRUST_PROXY",
        "TRUSTED_IP_HEADER",
        "RESEND_API_KEY",
        "MAIL_FROM",
        "SNAPSHOT_INTERVAL_SECONDS",
        "FILES_S3_ENDPOINT",
        "FILES_S3_BUCKET",
        "FILES_S3_KEY_ID",
        "FILES_S3_SECRET",
        "FILES_S3_REGION",
    ):
        monkeypatch.delenv(name, raising=False)
    # The hosted mode, so a test can make as many lists as it likes; the one-list
    # default is exercised by test_hosting.py.
    monkeypatch.setenv("OPEN_SIGNUP", "true")
    db.init_db()
    yield
    db.close_db()


@pytest.fixture()
def L(todo_db) -> int:
    """A fresh list's id."""
    return lists.create_list("America/Chicago")["list_id"]


@pytest.fixture()
def client(todo_db):
    """The app with its lifespan running, as a browser on its own pages. It keeps
    cookies, so after it creates a list it is signed in to it."""
    from backend.main import app

    ratelimit.clear_all()

    with TestClient(app, headers=BROWSER) as c:
        yield c


@pytest.fixture()
def create(client):
    """POST /api/lists from the shared client as a browser signed in to nothing:
    one cookie jar holds one session, and creating is refused while signed in."""

    def go(**kwargs):
        client.cookies.clear()
        return client.post("/api/lists", **kwargs)

    return go


@pytest.fixture()
def new_list(client):
    """Create a list the way a browser does. Each list gets its OWN client — one
    cookie jar holds one session, and creating is refused while signed in — which
    holds that list's session and sends X-List and Sec-Fetch-Site by default.

    The client is made without ``with``, so it runs no second lifespan (the
    ``client`` fixture's is running). It speaks https when the configured address
    is https, as a real browser must for the Secure cookie to come back."""
    made = []

    def make(tz="America/Chicago"):
        scheme = "https" if settings.cookie_secure() else "http"
        browser = TestClient(client.app, base_url=f"{scheme}://testserver", headers=BROWSER)
        made.append(browser)
        body = browser.post("/api/lists", json={"tz": tz}).json()
        list_id = browser.get("/api/app/session").json()["list_id"]
        browser.headers["X-List"] = str(list_id)
        return {
            **body,
            "client": browser,
            "api": "/api/app",
            "list_id": list_id,
            "capture_token": lists.get_list(list_id)["capture_token"],
            "session": browser.cookies[sessions.COOKIE],
        }

    yield make
    for browser in made:
        browser.close()


@pytest.fixture()
def freeze(monkeypatch):
    """Freeze the app's one clock at a UTC instant."""

    def at(iso: str):
        instant = datetime.datetime.fromisoformat(iso).replace(tzinfo=datetime.timezone.utc)
        monkeypatch.setattr(common, "utcnow", lambda: instant)
        return instant

    return at


@pytest.fixture()
def mail(monkeypatch, client):
    """Mail switched on, with the send stubbed: the messages that would go out, as (to, text)."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "Todo GTD <signin@todo.example>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://todo.example")
    sent = []
    monkeypatch.setattr(signin, "_send", lambda to, subject, text: sent.append((to, text)))
    return sent


@pytest.fixture()
def confirm():
    """Give a list a confirmed email directly, as redeeming its confirmation link
    would (that flow itself is tested in test_hosting.py)."""
    return confirm_list


def confirm_list(list_id: int, email: str = "me@example.com") -> None:
    """The one place a test stamps a confirmed email (the fixture above returns it)."""
    with db.transaction() as conn:
        lists.set_email_in(conn, list_id, email)
        lists.verify_email_in(conn, list_id)


def turn_on(list_id: int, app: str) -> None:
    """Turn an app on for a list, as Apps under Connect does (test_apps.py tests that)."""
    with db.transaction() as conn:
        lists.set_app_in(conn, list_id, app, True)


def only(list_id: int, *on: str) -> None:
    """Leave exactly these apps on for a list. A new hosted list starts with Todo, Notes
    and Projects; an older account, or one that turned some off, has fewer."""
    with db.transaction() as conn:
        for app in apps.APPS:
            lists.set_app_in(conn, list_id, app, app in on)
