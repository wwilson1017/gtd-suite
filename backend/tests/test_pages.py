"""The HTML pages: shell injection, manifests, headers, redirects, the invalid-link pages."""

from pathlib import Path

import pytest

from backend import pages

FRONTEND_INDEX = Path(__file__).resolve().parents[2] / "frontend" / "index.html"


@pytest.fixture()
def built(tmp_path, monkeypatch):
    """A stand-in build: the REAL frontend/index.html (so the inject anchor is
    pinned against the file that actually ships) plus one root file."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text(FRONTEND_INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    (static / "icon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    monkeypatch.setattr(pages, "STATIC_DIR", static)
    monkeypatch.setattr(pages, "INDEX_PATH", static / "index.html")
    monkeypatch.setattr(pages, "_index_cache", None)
    return static


def _assert_page_headers(res):
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-robots-tag"] == "noindex, nofollow"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "www-authenticate" not in res.headers


def test_the_real_index_html_has_the_inject_anchor():
    assert FRONTEND_INDEX.read_text(encoding="utf-8").count(pages.INJECT_ANCHOR) == 1


@pytest.mark.parametrize("path", ["/", "/signin/some-token"])
def test_landing_and_signin_serve_the_plain_shell(client, built, path):
    res = client.get(path)
    assert res.status_code == 200
    _assert_page_headers(res)
    assert '<div id="root">' in res.text
    # No manifest: these pages belong to no list.
    assert 'rel="manifest"' not in res.text


def test_loading_the_signin_page_changes_nothing(client, built, new_list):
    made = new_list()
    token = made["client"].post("/api/app/signin-link").json()["url"].rsplit("/", 1)[1]
    assert client.get(f"/signin/{token}").status_code == 200
    assert "set-cookie" not in client.get(f"/signin/{token}").headers
    assert client.post(f"/api/signin/{token}").status_code == 200  # still unspent


def test_a_signed_in_browser_goes_from_home_to_the_app_and_back_only_when_signed_out(client, built, new_list):
    made = new_list()
    c = made["client"]
    home = c.get("/", follow_redirects=False)
    assert (home.status_code, home.headers["location"]) == (303, "/app")
    _assert_page_headers(home)
    for path in ("/app", "/app/inbox", "/app/projects/3"):
        assert c.get(path, follow_redirects=False).status_code == 200, path
    c.post("/api/app/signout")
    for path in ("/app", "/app/inbox"):
        res = c.get(path, follow_redirects=False)
        assert (res.status_code, res.headers["location"]) == (303, "/"), path
        assert "set-cookie" not in res.headers  # the cookie is never touched
    assert c.get("/", follow_redirects=False).status_code == 200
    # A browser that never signed in at all.
    res = client.get("/app/connect", follow_redirects=False)
    assert (res.status_code, res.headers["location"]) == (303, "/")


@pytest.mark.parametrize("sub", ["", "/inbox", "/projects/3", "/connect"])
def test_the_app_page_has_one_manifest_sent_with_credentials(built, new_list, sub):
    res = new_list()["client"].get(f"/app{sub}")
    assert res.status_code == 200
    _assert_page_headers(res)
    assert '<link rel="manifest" href="/app/manifest.webmanifest" crossorigin="use-credentials">' in res.text
    # Injected inside <head>, before the app's own module script runs.
    assert res.text.index('rel="manifest"') < res.text.index("</head>")
    assert "__TODOGTD_BASE__" not in res.text


def test_the_app_manifest_starts_and_stays_at_app(client, built, new_list):
    made = new_list()
    for c in (made["client"], client):  # signed in or not, it answers
        res = c.get("/app/manifest.webmanifest")
        assert res.status_code == 200  # the manifest route, not the page's catch-all
        assert res.headers["content-type"].startswith("application/manifest+json")
        _assert_page_headers(res)
        body = res.json()
        # Scoped to /app, not the site: inside it, the capture page would count as
        # "already installed" and could not be installed as its own app.
        assert (body["id"], body["start_url"], body["scope"], body["name"]) == ("/app", "/app", "/app", "Todo GTD")
        assert body["display"] == "standalone"
        assert {i["src"] for i in body["icons"]} == {"/icon-192.png", "/icon-512.png"}


def test_capture_page_gets_its_own_manifest(client, built, new_list):
    token = new_list()["capture_token"]
    res = client.get(f"/c/{token}")
    assert res.status_code == 200
    _assert_page_headers(res)
    assert f'<link rel="manifest" href="/c/{token}/manifest.webmanifest"' in res.text
    manifest = client.get(f"/c/{token}/manifest.webmanifest").json()
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == f"/c/{token}"
    assert manifest["name"] == "Capture"
    # Its own mark beside Todo GTD's, on Android and on iOS.
    assert {i["src"] for i in manifest["icons"]} == {"/icon-capture-192.png", "/icon-capture-512.png"}
    assert 'sizes="180x180" href="/apple-touch-icon-capture.png"' in res.text


def test_unknown_capture_token_is_an_html_404_never_a_401(client, built, new_list):
    made = new_list()
    # Unknown tokens, and the list's other secrets on the capture page.
    for path in ("/c/not-a-real-token", f"/c/{made['agent_token']}", f"/c/{made['session']}"):
        res = client.get(path)
        assert res.status_code == 404, path
        _assert_page_headers(res)
        assert res.headers["content-type"].startswith("text/html")
        assert "This link isn" in res.text and "re-add it from the new link" in res.text
        # The page never echoes the token and never mounts the app.
        assert path.rsplit("/", 1)[-1] not in res.text
        assert '<div id="root">' not in res.text
    res = client.get("/c/nope/manifest.webmanifest")
    assert res.status_code == 404
    _assert_page_headers(res)


def test_an_old_web_link_says_the_address_is_no_longer_used(client, built, new_list):
    made = new_list()
    for path in ("/w", "/w/", "/w/x", "/w/OLDTOKEN/inbox", "/w/OLDTOKEN/manifest.webmanifest", f"/w/{made['session']}"):
        res = client.get(path)
        assert res.status_code == 404, path
        _assert_page_headers(res)
        assert "This address is no longer used" in res.text and 'href="/"' in res.text
        assert '<div id="root">' not in res.text and "OLDTOKEN" not in res.text
        assert "set-cookie" not in res.headers


def test_catch_all_serves_root_files_and_never_shadows_the_api(client, built):
    icon = client.get("/icon.svg")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg")
    # index.html itself is only ever served through the shell (with its headers).
    assert client.get("/index.html").headers["cache-control"] == "no-store"
    # API, MCP and asset paths that match nothing are 404s, not the landing page.
    # (/mcp itself is the bearer route: test_mcp.py.)
    for path in (
        "/api",
        "/api/nope",
        "/api/w/x/nope",
        "/api/app/nope",
        "/mcp/some-token",
        "/link",
        "/link/some-token",
        "/some-token/mcp",
        "/assets/missing.js",
        "/.well-known/oauth-authorization-server",
        "/.well-known",
        "/register",
        "/authorize",
        "/token",
        "/signin",
    ):
        res = client.get(path)
        assert res.status_code == 404, path
        assert '<div id="root">' not in res.text
    # A path that climbs out of the build directory is not a file to serve.
    assert "FastAPI" not in client.get("/..%2fmain.py").text


def test_pages_say_how_to_build_when_there_is_no_build(client, tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "INDEX_PATH", tmp_path / "missing" / "index.html")
    monkeypatch.setattr(pages, "_index_cache", None)
    res = client.get("/")
    assert res.status_code == 503
    assert "npm run build" in res.text
    _assert_page_headers(res)


@pytest.mark.parametrize("open_signup", [True, False])
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("name", ["terms.html", "privacy.html", "refunds.html", "support.html", "legal.css"])
def test_policy_files_keep_public_addresses_only_on_hosted_servers(
    client, built, monkeypatch, open_signup, method, name
):
    monkeypatch.setenv("OPEN_SIGNUP", str(open_signup).lower())
    public = FRONTEND_INDEX.parent / "public" / "paid"
    (built / "paid").mkdir(exist_ok=True)
    content = (public / name).read_text(encoding="utf-8")
    (built / "paid" / name).write_text(content, encoding="utf-8")
    # Even a leftover file from an older build must not expose policies on a self-host.
    (built / name).write_text("old hosted policy", encoding="utf-8")
    res = client.request(method, f"/{name}")
    assert res.status_code == 200
    if open_signup:
        assert res.headers["content-type"].startswith("text/css" if name.endswith(".css") else "text/html")
        if method == "GET":
            assert res.text == content
    else:
        unknown = client.request(method, "/unknown-file.html")
        assert res.text == unknown.text
        _assert_page_headers(res)
    assert client.get(f"/paid/{name}").status_code == 404


def test_policy_links_still_use_public_addresses():
    from html.parser import HTMLParser

    links = []

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            links.extend(value for key, value in attrs if key == "href" and value and value.startswith("/"))

    names = {"terms.html", "privacy.html", "refunds.html", "support.html", "legal.css"}
    public = FRONTEND_INDEX.parent / "public" / "paid"
    for name in names - {"legal.css"}:
        links.clear()
        Links().feed((public / name).read_text(encoding="utf-8"))
        assert "/legal.css" in links
        assert {f"/{page}" for page in names - {"legal.css"}} <= set(links)
        assert set(links) <= {"/", *(f"/{page}" for page in names)}
