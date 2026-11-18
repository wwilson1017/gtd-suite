"""Operator's changed-files-only deck check. Stdlib only; never prints the agent link.

python scripts/sites_sync_check.py --link-file /path/to/link /path/to/deck
Or set SITES_AGENT_LINK. Uses a stable client_ref, so a retry updates the same test site.
The source folder is read only. Playback, seek and the browser's zip download are manual.
"""

import argparse
import concurrent.futures
import contextlib
import hashlib
import io
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


def digest(source: Path | bytes) -> tuple[int, str]:
    if isinstance(source, bytes):
        return len(source), hashlib.sha256(source).hexdigest()
    sha, size = hashlib.sha256(), 0
    with source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
            size += len(chunk)
    return size, sha.hexdigest()


def request(url: str, *, body=None, method="GET", headers=None):
    try:
        return urlopen(Request(url, data=body, method=method, headers=headers or {}), timeout=300)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}; request failed (address withheld)") from None
    except (URLError, OSError):
        raise RuntimeError("Network request failed (address withheld)") from None


class Check:
    def __init__(self, link: str, folder: Path):
        self.link = urlsplit(link)
        if self.link.scheme not in ("http", "https") or not self.link.netloc:
            raise ValueError("The agent link must be an HTTP(S) address")
        self.ref = "sync-check-" + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24]
        self.site_id = None
        self.address = ""
        self.known: set[str] = set()

    def command(self, cmd: str, payload=None, *, site_id=None):
        params = dict(parse_qsl(self.link.query))
        params["cmd"] = cmd
        if site_id is not None:
            params["id"] = str(site_id)
        url = urlunsplit(self.link._replace(query=urlencode(params), fragment=""))
        with request(
            url, body=json.dumps(payload or {}).encode(), method="POST", headers={"Content-Type": "application/json"}
        ) as response:
            result = json.load(response)
        if result.get("ok") is False:
            raise RuntimeError("The agent command refused the request (details withheld)")
        return result

    @staticmethod
    def describe(data):
        manifest, sources = [], {}
        for path, source in sorted(data.items()):
            size, sha = digest(source)
            manifest.append({"path": path, "size": size, "sha256": sha})
            sources[sha] = (source, size)
        return manifest, sources

    @staticmethod
    def upload(missing, sources):
        def put(entry):
            source, size = sources[entry["sha256"]]
            with contextlib.closing(io.BytesIO(source) if isinstance(source, bytes) else source.open("rb")) as body:
                with request(
                    entry["put"]["url"],
                    body=body,
                    method="PUT",
                    headers={**entry["put"]["headers"], "Content-Length": str(size)},
                ) as response:
                    response.read()
            return size

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            return sum(pool.map(put, missing))

    def sync(self, data, label, *, abandon=False):
        started = time.monotonic()
        manifest, sources = self.describe(data)
        sent, sent_bytes = 0, 0
        for _ in range(10):
            result = self.command(
                "SITE_SYNC",
                {"manifest": manifest, "client_ref": self.ref, "name": "deck-check", "title": "Deck publishing check"},
                site_id=self.site_id,
            )
            self.site_id = result["site"]["id"]
            address = result["site"]["address"]
            if self.address and address != self.address:
                raise RuntimeError("The address changed")
            self.address = address
            if result["status"] == "published":
                self.known.update(sources)
                print(
                    f"{label}: {time.monotonic() - started:.2f}s, {sent} uploaded, {sent_bytes:,} bytes, site {self.site_id}"
                )
                return
            missing = result["missing"]
            if any(entry["sha256"] in self.known for entry in missing):
                raise RuntimeError("A previously uploaded blob was requested again")
            chosen = missing[: max(1, len(missing) // 2)] if abandon else missing
            sent_bytes += self.upload(chosen, sources)
            sent += len(chosen)
            if abandon:
                print(f"{label}: left uncommitted after {sent} uploads")
                return
        raise RuntimeError("Sync did not publish after ten attempts")

    def assert_missing(self, path=""):
        try:
            with urlopen(self.address + path, timeout=60):
                raise RuntimeError("An unpublished site or removed file still answers")
        except HTTPError as exc:
            if exc.code != 404:
                raise RuntimeError("The missing resource did not answer 404") from None
        except URLError:
            raise RuntimeError("Could not check the missing resource") from None

    def html(self):
        with request(self.address) as response:
            return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--link-file", type=Path)
    parser.add_argument("--updates", type=int, default=20)
    args = parser.parse_args()
    link = args.link_file.read_text().strip() if args.link_file else os.environ.get("SITES_AGENT_LINK", "").strip()
    if not link:
        parser.error("Supply --link-file or SITES_AGENT_LINK")
    data = {p.relative_to(args.folder).as_posix(): p for p in sorted(args.folder.rglob("*")) if p.is_file()}
    if "index.html" not in data:
        parser.error("The folder needs index.html")
    check = Check(link, args.folder)
    check.sync(data, "initial publish")
    check.sync(data, "unchanged repeat")
    html = data["index.html"].read_bytes()
    videos = [p for p in data if p.lower().endswith(".mp4")]
    for i in range(args.updates):
        changed = {**data, "index.html": html + f"\n<!-- sync check {i} -->".encode()}
        if i % 5 == 1 and len(videos) > 1:
            changed[videos[0]] = data[videos[1]]
        if i % 5 in (2, 3):
            changed[f"__sync_check/{'new' if i % 5 == 2 else 'renamed'}.txt"] = b"sync check fixture"
        check.sync(changed, f"update {i + 1}")
    before = check.html()
    interrupted = {**data, "index.html": html + b"<!-- interrupted -->", "__sync_check/retry.txt": b"retry"}
    check.sync(interrupted, "interrupted update", abandon=True)
    if check.html() != before:
        raise RuntimeError("An uncommitted update replaced the live HTML")
    check.sync(interrupted, "retry")
    a = {**data, "index.html": html + b"<!-- race A -->", "__sync_check/race-a.txt": b"race A"}
    b = {**data, "index.html": html + b"<!-- race B -->", "__sync_check/race-b.txt": b"race B"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(check.sync, variant, label) for variant, label in ((a, "race A"), (b, "race B"))]
        for future in futures:
            future.result()
    current = check.html()
    if current not in (a["index.html"], b["index.html"]):
        raise RuntimeError("Concurrent sync left unexpected HTML")
    winner, loser = ("a", "b") if current == a["index.html"] else ("b", "a")
    with request(check.address + f"__sync_check/race-{winner}.txt") as response:
        if response.read() != f"race {winner.upper()}".encode():
            raise RuntimeError("Concurrent sync mixed manifests")
    check.assert_missing(f"__sync_check/race-{loser}.txt")
    check.command("UNPUBLISH", site_id=check.site_id)
    check.assert_missing()
    check.command("REPUBLISH", site_id=check.site_id)
    if check.html() != current:
        raise RuntimeError("Republishing changed the deck")
    check.sync(data, "restore original deck")
    print("Manual checks in the Sites app: slides, media playback/seek during an update, and Download zip offline.")
    print("Offline live.json fetch is not supported by file:// browsers.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError):
        raise SystemExit("Check failed; inspect the Sites app and retry. No link or signed URL was printed.") from None
