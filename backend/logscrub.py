"""todo-gtd — keep tokens out of the logs.

A token in an address IS a credential, so the token segment of every token
path is replaced with ``***`` before a record is written: /c/, /signin/, /link/
and /mcp/ (the agent link's two shapes), with or without the /api prefix, and the
agent link's token-first shape, /<token>/mcp — plus /w/ and /recover/, which no longer exist but
which old bookmarks still send. A Simple Sites address is a key too (sites.py): a whole path
that looks like one, /<code> or /<name>-<code>, is masked as a whole. The bearer way in, /mcp with an Authorization header, has
no token in its path, and neither has the web app: its session is a cookie. This covers the app's own output only — a proxy in front
(Railway's HTTP log) keeps its own. A program key (keys.py) travels only in a header, and
anything shaped like one, anywhere in a record, is masked too. So is a file's path in a
query (``?path=``), which is no credential but is the person's own words. Signed S3
URLs (brain_import's server-side PUTs) are credentials too, including in httpx's logs.
"""

import logging
import re
from collections.abc import Mapping

from backend import apps, settings

_TOKEN_PATH = re.compile(r"(/(?:w|c|link|signin|recover|mcp|zip|connect)/)[^/?#\s\"']+")
# /<token>/mcp. Only a segment that looks like a token (lists.mint_token makes 43
# characters), so the host of a full URL ending in /mcp is left readable. The class
# keeps - and _: tokens minted before 2026-10-11 carry them and are still live.
_TOKEN_FIRST_PATH = re.compile(r"/[A-Za-z0-9_-]{32,}(/mcp(?![\w-]))")
# A Simple Sites address (sites.ADDRESS_RE) as a whole path: at the start of the text,
# after a space or quote, or right after a URL's host, so a segment deeper in some other
# path is left alone.
# An app's path (/sites, /notes, …) in front is masked with it: on a one-address server a
# visitor's address tried under one is refused (pages.py), and the try is still logged.
_SITE_PATH = re.compile(
    r"(^|[\s\"']|://[^/\s\"']+)(?:/(?:%s))?/(?:[a-z0-9-]{1,20}-)?[A-Za-z0-9]{10}"
    r"(?=$|[\s?#/;\"'])" % "|".join(apps.APPS)
)

_SITE_DATA_QUERY = re.compile(_SITE_PATH.pattern + r"/data\?[^\s\"'<>]*")

_KEY = re.compile(r"\bcb_[A-Za-z0-9]{20,}")
# A file's path in the REST download's query (api_v1.py), or a connect page's code.
_FILE_QUERY = re.compile(r"([?&](?:path|code)=)[^&\s\"']*")
# httpx logs the whole URL; a transport can log only its path and query.
_SIGNED_URL = re.compile(r"(?:https?://|/)[^\s\"'<>]*[?&]X-Amz-[^\s\"'<>]*", re.I)


def scrub(text: str) -> str:
    try:
        domain = settings.sites_content_domain()
    except ValueError:  # a malformed setting must never stop a log line
        domain = ""
    if domain:
        text = re.sub(r"[a-z0-9-]+\." + re.escape(domain) + r"(?![a-z0-9-])", "***." + domain, text, flags=re.I)
    text = _SITE_DATA_QUERY.sub(r"\1/***/data?***", text)
    text = _SIGNED_URL.sub("[signed file URL]", text)
    text = _TOKEN_FIRST_PATH.sub(r"/***\1", _TOKEN_PATH.sub(r"\1***", _KEY.sub("cb_***", text)))
    return _FILE_QUERY.sub(r"\1***", _SITE_PATH.sub(r"\1/***", text))


def _scrub_arg(arg):
    # Scrubs strings and anything that PRINTS a token path (a URL, an exception);
    # an argument with nothing to hide is passed through untouched, type and all.
    text = arg if isinstance(arg, str) else str(arg)
    clean = scrub(text)
    return arg if clean == text else clean


class ScrubTokens(logging.Filter):
    """Scrubs the message, its arguments and the rendered traceback, so an exception
    whose text names a token path is scrubbed too."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            # uvicorn's access line is (client, method, path, http version, status).
            record.args = tuple(_scrub_arg(a) for a in record.args)
        elif isinstance(record.args, Mapping):
            record.args = {k: _scrub_arg(v) for k, v in record.args.items()}
        if not isinstance(record.msg, str):
            # `log.error(exc)` hands over an object, and logging prints str() of it.
            record.msg = _scrub_arg(record.msg)
        elif scrub(record.msg) != record.msg:
            if record.args:
                # The TEMPLATE spells the path and an argument fills the token in
                # ("refused /c/%s"). Scrubbing the template alone would eat the
                # placeholder and break formatting, so render first, then scrub. Only
                # this case loses the args: uvicorn's access template never names a
                # path, so its formatter still gets the tuple it unpacks.
                record.msg, record.args = scrub(record.getMessage()), None
            else:
                record.msg = scrub(record.msg)
        if record.exc_info and not record.exc_text:
            # Render the traceback now so the scrubbed text is what every handler's
            # Formatter reuses (Formatter.format only renders exc_info when exc_text
            # is empty).
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def install() -> None:
    """Send the app's own records to stderr and scrub them and uvicorn's.

    A logger's filter sees only records logged ON that logger, so the filter
    goes on uvicorn's loggers and on the root HANDLERS (which see every
    record that propagates up from ``backend.*``). ``uvicorn.asgi`` is the
    trace-level logger (``--log-level trace``), which prints the whole ASGI
    scope, ``path`` and ``raw_path`` included."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:     %(name)s: %(message)s")
    scrubber = ScrubTokens()
    for handler in logging.getLogger().handlers:
        handler.addFilter(scrubber)
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn.asgi"):
        logging.getLogger(name).addFilter(scrubber)
