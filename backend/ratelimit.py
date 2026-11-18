"""todo-gtd — in-process rate limiting for the no-login endpoints.

Every surface is reachable without a login, so each needs a cheap guard
against flooding. Keys are usually client IPs, but any string works (the
capture endpoint also keys by token).
"""

import threading
import time
from collections import OrderedDict

from fastapi import Request

from backend import settings

# Above this many tracked keys, whole expired buckets are dropped. Pruning
# timestamps alone still leaks the keys, so an attacker cycling source IPs
# could grow the dict unboundedly.
_SWEEP_AT = 256

# Hard ceiling on tracked keys. The sweep only drops *expired* buckets, so a
# flood of ever-new source IPs inside one window could still grow the dict to
# rate × window. At the cap, the least-recently-touched bucket is evicted to
# admit the newcomer, bounding memory.
_MAX_TRACKED = 10_000


_limiters: list["IPRateLimiter"] = []


def clear_all() -> None:
    """Empty every limiter (tests)."""
    for limiter in _limiters:
        limiter.clear()


class IPRateLimiter:
    """Fixed-window-ish counter: at most `max_hits` per `window` seconds per key."""

    def __init__(self, window: int, max_hits: int):
        self.window = window
        self.max_hits = max_hits
        # OrderedDict as an LRU: every touched key moves to the end, so the
        # eviction at the cap is an O(1) popitem instead of a full scan on
        # every request during exactly the flood the cap exists to bound.
        self.hits: OrderedDict[str, list[float]] = OrderedDict()
        self._last_sweep = 0.0
        self._lock = threading.Lock()  # handlers run in a threadpool
        _limiters.append(self)

    def allow(self, ip: str) -> bool:
        now = time.time()
        with self._lock:
            # The sweep is O(tracked keys), so once past _SWEEP_AT a spoofed-IP
            # flood would pay a full scan on every request. At most once per
            # second is plenty — the cap below bounds memory between sweeps.
            if len(self.hits) > _SWEEP_AT and now - self._last_sweep >= 1.0:
                self._last_sweep = now
                for stale in [k for k, v in self.hits.items() if not v or now - v[-1] >= self.window]:
                    del self.hits[stale]
            if ip not in self.hits and len(self.hits) >= _MAX_TRACKED:
                self.hits.popitem(last=False)
            self.hits[ip] = [t for t in self.hits.get(ip, []) if now - t < self.window]
            self.hits.move_to_end(ip)
            if len(self.hits[ip]) >= self.max_hits:
                return False
            self.hits[ip].append(now)
            return True

    def forget(self, key: str) -> None:
        with self._lock:
            self.hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self.hits.clear()


def client_ip(request: Request) -> str:
    """The address a limit is keyed on — the ONE place that decides it.

    Directly exposed, that is the peer. Behind a proxy the peer is the proxy for
    everybody, so with TRUST_PROXY=1 the address comes from the header the proxy
    sets (TRUSTED_IP_HEADER, default X-Real-IP — what Railway's edge writes, and
    it overwrites anything the client sent). Only turn it on behind a proxy that
    sets the header itself; otherwise a client picks its own key and has no limit.
    For a list-valued header (X-Forwarded-For) the first entry is used, which is
    the client only when the proxy discards what the client sent, as Railway's does.

    # simplification: one key per address; group IPv6 by /64 if rotation within a prefix shows up
    """
    if settings.trust_proxy():
        forwarded = request.headers.get(settings.trusted_ip_header(), "").split(",")[0].strip()
        if forwarded:
            return forwarded[:64]
    return request.client.host if request.client else "unknown"


# Wrong-token attempts per address, across every token surface (capture, agent,
# sign-in links; pages, API and MCP). A session cookie is not a token surface: a
# stale one is an ordinary signed-out browser. The tokens are 256 bits, so this is
# hygiene rather than the defence: it keeps a scanner from using the server as a
# free oracle. Only MISSES are charged and only misses are refused: a valid link
# is always served, so one bad actor or one misconfigured AI tool behind a shared
# address cannot lock everyone there out of their own lists.
bad_token_limiter = IPRateLimiter(window=600, max_hits=60)

TOO_MANY_WRONG_LINKS = "Too many wrong links from this address. Wait ten minutes and try again."

# Every try at a locked Simple Sites page's password, right or wrong, charged before any
# hashing (pages.site_unlock), so guessing costs the guesser and never the server.
connect_limiter = IPRateLimiter(window=3600, max_hits=10)
password_limiter = IPRateLimiter(window=600, max_hits=20)
data_write_limiter = IPRateLimiter(window=60, max_hits=120)
data_read_limiter = IPRateLimiter(window=60, max_hits=120)


def wrong_token_status(request: Request) -> int:
    """Call when a token matched nothing: counts the miss and says how to answer
    it — 404, or 429 once this address has used up its misses."""
    return 404 if bad_token_limiter.allow(client_ip(request)) else 429
