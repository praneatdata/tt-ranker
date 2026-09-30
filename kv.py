"""
Tiny Upstash-Redis REST client — the whole database for tt-ranker.

No SDK, no deps beyond requests: Upstash takes one command as a JSON array over
HTTP, which suits Vercel's serverless runtime, where a pooled DB connection has
nowhere to live between invocations.

`pipeline()` matters more here than it did in pr-raiser: confirming a doubles
match reads four player records and writes four more, and at ~30ms a round trip
that is the difference between a snappy button and a spinner.

Config (set in Vercel + .env, then redeploy):
  KV_REST_API_URL / KV_REST_API_TOKEN                 (Upstash via the Vercel
                                                       Marketplace integration), or
  UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN   (Upstash direct)

Unlike pr-raiser there is no degraded fallback mode — ratings have to live
somewhere — so callers check kv_available() and say so plainly instead.
"""
import os
import ssl

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.ssl_ import create_urllib3_context
except ImportError:  # pragma: no cover - urllib3 always ships with requests
    create_urllib3_context = None


class _RelaxedStrictAdapter(HTTPAdapter):
    """Trusts a corporate TLS proxy without giving up verification.

    The proxy re-signs certificates without an Authority Key Identifier, which
    Python 3.13+ rejects outright — so on a laptop behind it, every call here
    dies with CERTIFICATE_VERIFY_FAILED even once the proxy's CA is trusted.
    Keep full verification and drop only the strict flag, the same trade
    bot.build_app() makes for the Slack client.

    Vercel isn't behind the proxy, so in production this changes nothing.
    """

    def _context(self):
        ctx = create_urllib3_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._context()
        return super().proxy_manager_for(*args, **kwargs)


_SESSION = None


def _session():
    """One pooled Session for the process. Also saves a TCP+TLS handshake per
    command, which adds up when a doubles confirmation makes a dozen calls."""
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        if create_urllib3_context is not None:
            _SESSION.mount("https://", _RelaxedStrictAdapter())
    return _SESSION


def _config():
    url = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    return url, token


def kv_available():
    url, token = _config()
    return bool(url and token)


def _post(path, payload, timeout):
    url, token = _config()
    if not (url and token):
        raise RuntimeError("KV not configured")
    r = _session().post(url.rstrip("/") + path, json=payload, timeout=timeout,
                        headers={"Authorization": f"Bearer {token}"})
    r.raise_for_status()
    return r.json()


def _command(cmd, timeout=10):
    """Run one Redis command (a list like ["HSET", key, field, val]) and return
    its `result`. Raises requests.RequestException on transport/HTTP error."""
    return _post("", [str(c) for c in cmd], timeout).get("result")


def pipeline(cmds, timeout=15, atomic=False):
    """Run several commands in one HTTP round trip; returns a list of results in
    order.

    By default not a transaction — Upstash runs them sequentially and a failure
    surfaces as an {"error": …} entry, so this is for batching reads and
    independent writes. `atomic=True` sends the same batch to /multi-exec
    instead: still one round trip, but nothing else can interleave with it and
    no reader sees half of it. Upstash discards a whole transaction on a syntax
    or limit problem and answers with one {"error": …} rather than a list; that
    is raised, because the caller's writes did not happen.

    Pipelining saves round trips, not commands — Upstash bills each command in a
    pipeline or a transaction separately. See mget() for the case where one
    command can do the work of many.
    """
    if not cmds:
        return []
    body = _post("/multi-exec" if atomic else "/pipeline",
                 [[str(c) for c in cmd] for cmd in cmds], timeout)
    if isinstance(body, dict):
        raise RuntimeError(f"transaction discarded: {body.get('error')}")
    return [entry.get("result") for entry in body]


MGET_CHUNK = 200   # keys per MGET; keeps one reply comfortably small


def mget(keys, timeout=15):
    """GET many keys as one command per MGET_CHUNK keys, in one round trip.

    The difference from pipelined GETs is the bill, not the latency: a
    pipeline of 120 GETs is 120 billed commands, one MGET of 120 keys is one.
    Missing keys come back as None, in order, exactly like GET.
    """
    keys = list(keys)
    if not keys:
        return []
    chunks = [keys[i:i + MGET_CHUNK] for i in range(0, len(keys), MGET_CHUNK)]
    if len(chunks) == 1:
        return _command(["MGET", *chunks[0]], timeout) or []
    out = []
    for part in pipeline([["MGET", *chunk] for chunk in chunks], timeout):
        out += part or []
    return out


# --- strings ---------------------------------------------------------------

def get(key):
    return _command(["GET", key])


def set_(key, value, ex=None, nx=False):
    """SET with optional TTL and NX. Returns None when NX loses the race, which
    is how a caller can claim a key exactly once."""
    cmd = ["SET", key, value]
    if ex:
        cmd += ["EX", int(ex)]
    if nx:
        cmd += ["NX"]
    return _command(cmd)


def incr(key):
    return _command(["INCR", key])


def delete(*keys):
    if not keys:
        return 0
    return _command(["DEL", *keys])


# --- hashes ----------------------------------------------------------------

def hset(key, field, value, nx=False):
    return _command(["HSETNX" if nx else "HSET", key, field, value])


def hget(key, field):
    return _command(["HGET", key, field])


def hmget(key, *fields):
    """Several fields of one hash in one command; None where a field is unset."""
    if not fields:
        return []
    return _command(["HMGET", key, *fields]) or []


def hgetall(key):
    """The hash as a dict (Upstash returns a flat [f1, v1, f2, v2, …])."""
    return unflatten(_command(["HGETALL", key]))


def unflatten(res):
    """Flat [f1, v1, f2, v2, …] → dict. Exposed because pipelined HGETALLs come
    back in the same shape and need the same treatment."""
    res = res or []
    return {res[i]: res[i + 1] for i in range(0, len(res) - 1, 2)}


def hset_many(key, mapping):
    """Set several hash fields in one round trip."""
    args = []
    for k, v in mapping.items():
        args += [k, v]
    return _command(["HSET", key, *args]) if args else 0


def hincrby(key, field, amount=1):
    """Add to a hash field (creating it at 0 first). Atomic, so concurrent
    confirmations can't lose a count the way read-modify-write would."""
    return _command(["HINCRBY", key, field, amount])


def hdel(key, *fields):
    if not fields:
        return 0
    return _command(["HDEL", key, *fields])


# --- sets ------------------------------------------------------------------

def sadd(key, *members):
    """Add members to a set; returns how many were NEW. That count is what makes
    an atomic claim possible — exactly one racing caller sees 1 for a member."""
    if not members:
        return 0
    return _command(["SADD", key, *members])


def srem(key, *members):
    """Remove members; returns how many were actually there. Like sadd, exactly
    one racing caller sees 1 — which is how a pending match is claimed."""
    if not members:
        return 0
    return _command(["SREM", key, *members])


def smembers(key):
    return _command(["SMEMBERS", key]) or []


def sismember(key, member):
    return bool(_command(["SISMEMBER", key, member]))


# --- lists -----------------------------------------------------------------

def lpush(key, *values):
    if not values:
        return 0
    return _command(["LPUSH", key, *values])


def lrange(key, start=0, stop=-1):
    return _command(["LRANGE", key, start, stop]) or []


def llen(key):
    return int(_command(["LLEN", key]) or 0)


def ltrim(key, start, stop):
    return _command(["LTRIM", key, start, stop])


def lrem(key, value, count=0):
    """Remove `value` from a list — how an undone match leaves the history."""
    return _command(["LREM", key, count, value])


# --- keys ------------------------------------------------------------------

def expire(key, seconds):
    """Give a key a TTL so it cleans itself up instead of living forever."""
    return _command(["EXPIRE", key, int(seconds)])


def scan(match="*", count=200):
    """Every key matching a pattern, following the cursor to the end.

    Only used by the admin reset script. Note this database may be shared with
    another bot, which is exactly why that script matches a prefix instead of
    reaching for FLUSHDB.
    """
    keys, cursor = [], "0"
    while True:
        cursor, batch = _command(["SCAN", cursor, "MATCH", match, "COUNT", count])
        keys += batch or []
        if str(cursor) == "0":
            return sorted(set(keys))
