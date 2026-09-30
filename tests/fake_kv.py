"""An in-memory Redis good enough for the commands kv.py sends.

Only the HTTP transport (`kv._post`) is replaced, so every test runs the real
command construction, the real flat-hash unflattening and the real pipeline
batching. Faking kv's public functions instead would leave exactly the layer
most likely to be wrong — argument order, SET options, HGETALL's flat reply —
untested.

Values are stored as strings the way Redis does, so a test fails here for the
same reason production would if a caller forgot to coerce an int back.
"""
import re
from unittest.mock import patch

import kv


class FakeRedis:
    def __init__(self):
        self.data = {}   # key -> str | dict | set | list
        self.ttl = {}

    # --- transport ---------------------------------------------------------

    def post(self, path, payload, timeout=10):
        if path in ("/pipeline", "/multi-exec"):
            return [{"result": self.exec(cmd)} for cmd in payload]
        return {"result": self.exec(payload)}

    def patched(self):
        return patch.object(kv, "_post", self.post)

    def exec(self, cmd):
        name, args = str(cmd[0]).upper(), [str(a) for a in cmd[1:]]
        try:
            fn = getattr(self, "do_" + name.lower())
        except AttributeError:  # pragma: no cover - a new command needs a fake
            raise AssertionError(f"FakeRedis has no implementation for {name}")
        return fn(*args)

    # --- strings -----------------------------------------------------------

    def do_get(self, key):
        value = self.data.get(key)
        return value if isinstance(value, str) else None

    def do_set(self, key, value, *opts):
        opts = [o.upper() for o in opts]
        if "NX" in opts and key in self.data:
            return None
        self.data[key] = value
        if "EX" in opts:
            self.ttl[key] = int(opts[opts.index("EX") + 1])
        return "OK"

    def do_mget(self, *keys):
        return [self.do_get(k) for k in keys]

    def do_incr(self, key):
        value = int(self.data.get(key, 0)) + 1
        self.data[key] = str(value)
        return value

    def do_del(self, *keys):
        return sum(1 for k in keys if self.data.pop(k, None) is not None)

    def do_scan(self, cursor, *opts):
        """Cursor-paged like the real thing, so kv.scan's loop is under test."""
        opts = list(opts)
        pattern = opts[opts.index("MATCH") + 1] if "MATCH" in opts else "*"
        count = int(opts[opts.index("COUNT") + 1]) if "COUNT" in opts else 10
        rx = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$")
        keys = sorted(k for k in self.data if rx.match(k))
        start = int(cursor)
        page = keys[start:start + count]
        nxt = start + count
        return [str(nxt) if nxt < len(keys) else "0", page]

    def do_expire(self, key, seconds):
        self.ttl[key] = int(seconds)
        return 1

    # --- hashes ------------------------------------------------------------

    def do_hset(self, key, *pairs):
        h = self.data.setdefault(key, {})
        added = 0
        for i in range(0, len(pairs) - 1, 2):
            added += pairs[i] not in h
            h[pairs[i]] = pairs[i + 1]
        return added

    def do_hsetnx(self, key, field, value):
        h = self.data.setdefault(key, {})
        if field in h:
            return 0
        h[field] = value
        return 1

    def do_hget(self, key, field):
        return self.data.get(key, {}).get(field)

    def do_hmget(self, key, *fields):
        h = self.data.get(key, {})
        return [h.get(f) for f in fields]

    def do_hgetall(self, key):
        flat = []
        for field, value in self.data.get(key, {}).items():
            flat += [field, value]
        return flat

    def do_hincrby(self, key, field, amount):
        h = self.data.setdefault(key, {})
        h[field] = str(int(h.get(field, 0)) + int(amount))
        return int(h[field])

    def do_hdel(self, key, *fields):
        h = self.data.get(key, {})
        return sum(1 for f in fields if h.pop(f, None) is not None)

    # --- sets --------------------------------------------------------------

    def do_sadd(self, key, *members):
        s = self.data.setdefault(key, set())
        added = sum(1 for m in members if m not in s)
        s.update(members)
        return added

    def do_srem(self, key, *members):
        s = self.data.get(key, set())
        removed = sum(1 for m in members if m in s)
        s.difference_update(members)
        return removed

    def do_smembers(self, key):
        return sorted(self.data.get(key, set()))

    def do_sismember(self, key, member):
        return 1 if member in self.data.get(key, set()) else 0

    # --- lists -------------------------------------------------------------

    def do_lpush(self, key, *values):
        lst = self.data.setdefault(key, [])
        for value in values:
            lst.insert(0, value)
        return len(lst)

    def do_lrange(self, key, start, stop):
        lst = self.data.get(key, [])
        start, stop = int(start), int(stop)
        if stop < 0:
            stop += len(lst)
        return lst[start:stop + 1]

    def do_llen(self, key):
        return len(self.data.get(key, []))

    def do_ltrim(self, key, start, stop):
        lst = self.data.get(key, [])
        start, stop = int(start), int(stop)
        if stop < 0:
            stop += len(lst)
        self.data[key] = lst[start:stop + 1]
        return "OK"

    def do_lrem(self, key, count, value):
        lst = self.data.get(key, [])
        self.data[key] = [v for v in lst if v != value]
        return len(lst) - len(self.data[key])

    # --- helpers for assertions -------------------------------------------

    def player(self, uid):
        """The stored hash for a player, ints restored."""
        import store
        return store._coerce(self.data.get(store.player_key(uid), {}))

    def rating(self, uid):
        return self.player(uid)["rating"]
