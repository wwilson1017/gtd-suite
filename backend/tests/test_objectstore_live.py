"""The provider test, `pytest -m objectstore`: the store in FILES_S3_* does what
objectstore.py relies on, above all refusing an upload that is not the signed length and
checksum. Skipped unless FILES_S3_* is set. Files stays off for a provider that fails it.
It works in the configured bucket, which must exist, and deletes what it makes."""

import hashlib
import secrets
import time

import httpx2 as httpx
import pytest

from backend import objectstore, settings

pytestmark = [pytest.mark.objectstore, pytest.mark.skipif(settings.files_s3() is None, reason="FILES_S3_* is not set")]


def test_the_store_keeps_exactly_the_reserved_bytes():
    body = "Résumé – 2026\n".encode() * 1000
    staging, final = f"staging/pytest-{secrets.token_hex(8)}", f"pytest/{secrets.token_hex(8)}"
    up = objectstore.presigned_put(staging, len(body), hashlib.sha256(body).hexdigest(), 300)
    try:
        for wrong, headers in (
            (body + b"!", up["headers"]),  # another length
            (body[:-1] + b"?", up["headers"]),  # the same length, other bytes
            (body, {}),
        ):  # no checksum
            assert 400 <= httpx.put(up["url"], content=wrong, headers=headers).status_code < 500
            assert objectstore.head(staging) is None
        assert httpx.put(up["url"], content=body, headers=up["headers"]).status_code == 200
        assert objectstore.head(staging) == len(body)
        objectstore.copy(staging, final)
        got = httpx.get(objectstore.presigned_get(final, "Résumé – 2026.txt", "text/plain", 300))
        assert got.status_code == 200 and got.content == body
        assert got.headers["content-type"].startswith("text/plain")
        assert got.headers["content-disposition"] == (
            "attachment; filename*=UTF-8''R%C3%A9sum%C3%A9%20%E2%80%93%202026.txt"
        )
        inline = objectstore.presigned_get(final, "clip.mp4", "video/mp4", 300, disposition="inline")
        got = httpx.get(inline)
        assert got.status_code == 200 and got.content == body
        assert got.headers["content-disposition"].startswith("inline;")
        ranged = httpx.get(inline, headers={"Range": "bytes=0-99"})
        assert ranged.status_code == 206 and ranged.content == body[:100]
        assert ranged.headers["content-range"] == f"bytes 0-99/{len(body)}"
    finally:
        objectstore.delete(staging)
        objectstore.delete(final)
    assert objectstore.head(staging) is None and objectstore.head(final) is None


def test_slow_put_crosses_its_expiry(record_property):
    """Record whether R2 completes or refuses a PUT already running when its URL expires."""
    key = f"sites/pytest/slow-{secrets.token_hex(8)}"
    body = b"a" * 131072
    up = objectstore.presigned_put(key, len(body), hashlib.sha256(body).hexdigest(), 2)

    def chunks():
        yield body[:65536]
        time.sleep(4)
        yield body[65536:]

    try:
        try:
            response = httpx.put(
                up["url"], content=chunks(), headers={**up["headers"], "Content-Length": str(len(body))}, timeout=20
            )
        except httpx.HTTPError as exc:
            # An early refusal can close the socket while the client is still sending.
            record_property("slow_put_transport", type(exc).__name__)
        else:
            record_property("slow_put_status", response.status_code)
            assert response.status_code == 200 or 400 <= response.status_code < 500
        size = objectstore.head(key)
        record_property("slow_put_stored_bytes", size or 0)
        assert size in (None, len(body))
        inventory = [entry for page in objectstore.list("sites/pytest/") for entry in page]
        if size is not None:
            assert key in {entry["key"] for entry in inventory}
        # The daily reconcile can find these bytes even after their reservation is gone.
    finally:
        objectstore.delete(key)
