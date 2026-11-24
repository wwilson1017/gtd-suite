"""Common Brain and Sites file bytes, in any S3-compatible object store (Cloudflare R2, MinIO, S3, B2).

No SDK: requests are signed here with AWS Signature Version 4 (hmac and hashlib),
path-style (``<endpoint>/<bucket>/<key>``), in FILES_S3_REGION. The
calls here HEAD, copy, delete, stream and list, with httpx. ``head`` and ``put`` (a local
file, uploaded) also take another store's settings: the backup bucket's (backup.push). Normally bytes travel between the store
and the client on presigned links; brain_import uses those links for zip attachments.

Object keys are random ASCII (files.py makes them), never a file's path, so the signing needs
no Unicode rules. The only person's text in a signed URL is a download's filename, sent as
RFC 5987 ``filename*=UTF-8''…``.

A presigned PUT signs ``content-length`` and ``x-amz-checksum-sha256``: the store refuses any
other body, so what it keeps is exactly what was reserved, or nothing. ``pytest -m objectstore``
proves a provider does that; Files stays off for one that doesn't.
"""

import base64
import builtins
import hashlib
import hmac
import datetime
from collections.abc import Iterator, Generator
from typing import BinaryIO
from xml.etree import ElementTree
from urllib.parse import quote, urlsplit

import httpx2 as httpx

from backend import common, settings

_ALGORITHM = "AWS4-HMAC-SHA256"
_EMPTY = hashlib.sha256(b"").hexdigest()  # the payload hash of a call with no body
_CHUNK = 1 << 20


class StoreError(common.ValidationError):
    """The store could not be reached or refused the server's call: a refusal like any
    other, and the caller tries again."""


def _cfg() -> dict:
    cfg = settings.files_s3()
    if cfg is None:
        raise StoreError("Files are off on this server: it has no file store (FILES_S3_*).")
    return cfg


def _q(text: str, safe: str = "-_.~") -> str:
    return quote(text, safe=safe)


def _query(params: dict) -> str:
    return "&".join(f"{_q(k)}={_q(v)}" for k, v in sorted(params.items()))


def _scope(cfg: dict, stamp: str) -> str:
    return f"{stamp[:8]}/{cfg['region']}/s3/aws4_request"


def _signature(cfg: dict, method: str, path: str, params: dict, headers: dict, payload: str, stamp: str) -> str:
    """SigV4 over one request: `headers` by lowercase name, host among them."""
    canonical = "\n".join(
        [
            method,
            _q(path, "/-_.~"),
            _query(params),
            "".join(f"{k}:{v.strip()}\n" for k, v in sorted(headers.items())),
            ";".join(sorted(headers)),
            payload,
        ]
    )
    key = ("AWS4" + cfg["secret"]).encode()
    for part in _scope(cfg, stamp).split("/"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    to_sign = "\n".join([_ALGORITHM, stamp, _scope(cfg, stamp), hashlib.sha256(canonical.encode()).hexdigest()])
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


def _presign(
    cfg: dict,
    method: str,
    path: str,
    seconds: int,
    headers: dict | None = None,
    params: dict | None = None,
    now: datetime.datetime | None = None,
) -> str:
    """A link that makes this one request, until `seconds` from now, with `headers` sent as signed."""
    stamp = (now or common.utcnow()).strftime("%Y%m%dT%H%M%SZ")
    headers = {"host": urlsplit(cfg["endpoint"]).netloc, **(headers or {})}
    params = {
        **(params or {}),
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": f"{cfg['key_id']}/{_scope(cfg, stamp)}",
        "X-Amz-Date": stamp,
        "X-Amz-Expires": str(seconds),
        "X-Amz-SignedHeaders": ";".join(sorted(headers)),
    }
    signature = _signature(cfg, method, path, params, headers, "UNSIGNED-PAYLOAD", stamp)
    return f"{cfg['endpoint']}{_q(path, '/-_.~')}?{_query(params)}&X-Amz-Signature={signature}"


def presigned_put(key: str, size: int, sha256_hex: str, seconds: int, *, now: datetime.datetime | None = None) -> dict:
    """How a client uploads exactly these bytes to `key`: PUT them to `url` with `headers`
    (every HTTP client sends the Content-Length itself; it is signed too)."""
    cfg = _cfg()
    checksum = base64.b64encode(bytes.fromhex(sha256_hex)).decode()
    headers = {"content-length": str(size), "x-amz-checksum-sha256": checksum}
    return {
        "method": "PUT",
        "url": _presign(cfg, "PUT", f"/{cfg['bucket']}/{key}", seconds, headers, now=now),
        "headers": {"x-amz-checksum-sha256": checksum},
    }


def presigned_get(key: str, filename: str, content_type: str, seconds: int, disposition: str = "attachment") -> str:
    """A download link that saves the object as `filename`, with `content_type`."""
    if disposition not in ("attachment", "inline"):
        raise ValueError("Invalid disposition")
    cfg = _cfg()
    return _presign(
        cfg,
        "GET",
        f"/{cfg['bucket']}/{key}",
        seconds,
        params={
            "response-content-disposition": f"{disposition}; filename*=UTF-8''{_q(filename, '')}",
            "response-content-type": content_type,
        },
    )


def _signed(
    method: str,
    key: str,
    headers: dict | None = None,
    params: dict | None = None,
    cfg: dict | None = None,
    payload: str = _EMPTY,
) -> tuple[str, dict]:
    """`cfg` names another store in settings.files_s3's shape (the backup bucket); the
    Files store without it. `payload` is the body's SHA-256, in hex."""
    cfg = cfg or _cfg()
    path = f"/{cfg['bucket']}/{key}"
    stamp = common.utcnow().strftime("%Y%m%dT%H%M%SZ")
    signed = {
        "host": urlsplit(cfg["endpoint"]).netloc,
        "x-amz-content-sha256": payload,
        "x-amz-date": stamp,
        **(headers or {}),
    }
    signature = _signature(cfg, method, path, params or {}, signed, payload, stamp)
    auth = (
        f"{_ALGORITHM} Credential={cfg['key_id']}/{_scope(cfg, stamp)}, "
        f"SignedHeaders={';'.join(sorted(signed))}, Signature={signature}"
    )
    url = cfg["endpoint"] + _q(path, "/-_.~")
    if params:
        url += "?" + _query(params)
    return url, {**{k: v for k, v in signed.items() if k != "host"}, "authorization": auth}


def _call(
    method: str,
    key: str,
    headers: dict | None = None,
    timeout: float = 10,
    *,
    params: dict | None = None,
    cfg: dict | None = None,
) -> httpx.Response:
    """One signed call; only ListObjectsV2 may address the bucket itself."""
    if not key and not (method == "GET" and params and params.get("list-type") == "2"):
        raise ValueError("No object key")
    url, signed = _signed(method, key, headers, params, cfg)
    try:
        return httpx.request(method, url, timeout=timeout, headers=signed)
    except httpx.HTTPError:
        raise StoreError("The file store could not be reached. Try again in a minute.") from None


def stream(key: str) -> Generator[bytes, None, None]:
    """Signed GET, bounded chunks and a closed connection even if the reader stops early."""
    if not key:
        raise ValueError("No object key")
    url, headers = _signed("GET", key)
    try:
        with httpx.stream("GET", url, headers=headers, timeout=60) as response:
            if response.status_code != 200:
                raise _refused(response, "a read")
            yield from response.iter_bytes(chunk_size=65_536)
    except httpx.HTTPError:
        raise StoreError("The file store could not be reached. Try again in a minute.") from None


def list(prefix: str) -> Iterator[builtins.list[dict]]:
    """Yield pages of {key, modified} from signed ListObjectsV2 calls."""
    params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
    while True:
        response = _call("GET", "", params=params)
        if response.status_code != 200:
            raise _refused(response, "an inventory check")
        try:
            root = ElementTree.fromstring(response.content)
            page = []
            for item in root.findall("{*}Contents"):
                key, modified = item.findtext("{*}Key"), item.findtext("{*}LastModified")
                if key is None or modified is None or not key.startswith(prefix):
                    raise ValueError("Invalid inventory")
                page.append({"key": key, "modified": datetime.datetime.fromisoformat(modified)})
            truncated = root.findtext("{*}IsTruncated") == "true"
            token = root.findtext("{*}NextContinuationToken")
            if truncated and (not token or token == params.get("continuation-token")):
                raise ValueError("Invalid pagination")
        except (ValueError, ElementTree.ParseError):
            raise StoreError("The file store returned an invalid inventory.") from None
        yield page
        if not truncated:
            return
        assert token is not None
        params["continuation-token"] = token


def _refused(res: httpx.Response, what: str) -> StoreError:
    return StoreError(f"The file store answered {res.status_code} to {what}. Try again in a minute.")


def head(key: str, cfg: dict | None = None) -> int | None:
    """The object's size, or None when there is none."""
    # R2 gzips a compressible object's HEAD for a client that accepts it, and then sends no length.
    res = _call("HEAD", key, {"accept-encoding": "identity"}, cfg=cfg)
    if res.status_code == 404:
        return None
    if res.status_code != 200:
        raise _refused(res, "a check")
    return int(res.headers["content-length"])


def put(key: str, file: BinaryIO, cfg: dict | None = None) -> None:
    """Upload an open local file to `key`, streamed from disk: read once for its SHA-256,
    then sent with its length and that hash signed, so the store keeps these bytes or nothing."""
    if not key:
        raise ValueError("No object key")
    digest = hashlib.sha256()
    for chunk in iter(lambda: file.read(_CHUNK), b""):
        digest.update(chunk)
    headers = {
        "content-length": str(file.tell()),
        "x-amz-checksum-sha256": base64.b64encode(digest.digest()).decode(),
    }
    url, signed = _signed("PUT", key, headers, cfg=cfg, payload=digest.hexdigest())
    file.seek(0)
    try:
        # simplification: the timeout bounds each connect, read and write, not the whole upload;
        # a store that trickles holds the caller's thread. Add a deadline if that ever happens.
        res = httpx.request("PUT", url, headers=signed, timeout=60, content=iter(lambda: file.read(_CHUNK), b""))
    except httpx.HTTPError:
        raise StoreError("The file store could not be reached. Try again in a minute.") from None
    if res.status_code != 200:
        raise _refused(res, "an upload")


def copy(source: str, key: str) -> None:
    """Copy the object at `source` to `key`, inside the store (S3 CopyObject: up to 5 GB)."""
    res = _call("PUT", key, {"x-amz-copy-source": _q(f"/{_cfg()['bucket']}/{source}", "/-_.~")}, timeout=600)
    # A copy can fail after its 200 has started: the error is then in the body.
    if res.status_code != 200 or b"<Error>" in res.content:
        raise _refused(res, "a copy")


def delete(key: str) -> None:
    """Delete the object; one already gone is fine."""
    res = _call("DELETE", key)
    if res.status_code not in (200, 204, 404):
        raise _refused(res, "a delete")
