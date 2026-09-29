"""
Everything a web page reads, in two round trips.

Each page used to assemble itself from the store's helpers one call at a time —
the player set, then each player, then the names, then the history, then the
wallets (twice), then each fixture's pot — and /ladder came to seventeen round
trips per render. Almost every one of those keys is known before anything has
been read, so they all go in one pipeline. The reads that need its answers —
each player's hash, the matches the history lists, the live fixtures and their
pots — go in a second.

Parsing stays with the helpers that already own each shape (store.players_from,
betting.bets_from and so on), so a page renders from exactly the data it did
before; only the number of trips to fetch it has changed.

Read-only, apart from one courtesy the old path also paid for: fixture ids
whose record has expired are swept out of the live index on the way past.
"""
import json

import betting
import kv
import shame
import store


class PageData:
    """What load() read. Every field is present; the ones a page didn't ask
    for are empty, not missing, so a render never has to check."""

    def __init__(self):
        self.players = {}        # uid -> record, as store.all_players()
        self.names = {}          # uid -> name, as store.names()
        self.fetched = None      # raw tt:names:fetched, for bot.refresh_names
        self.titles = None       # raw tt:titles, for awards.current
        self.history = []        # newest first, as store.recent_matches()
        self.ladder_history = None   # the same, only when it is the whole ladder's
        self.has_players = False
        self.by_player = {}      # uid -> that player's recent matches
        self.week_delta, self.week_played = {}, {}
        self.wallets = None      # {uid: spins} when asked for, else None
        self.fixtures = []       # as betting.live()
        self.pools = {}          # sid -> betting.pool() for every live fixture
        self.match_count = None
        self.shame = {}          # as shame.counts()


def load(players=True, history=0, uid=None, uids=(), week=False, wallets=False,
         fixtures=False, count=False, shame_rows=False):
    """Read what a page asks for. `history` is how many recent matches: the
    whole ladder's, or `uid`'s. `uids` asks for each of those players' own
    recent matches as well (the compare page), fetched once however many of
    them a match appears in; it needs `history` for the length."""
    data = PageData()

    # --- wave one: every key that is known before anything is read ---------
    first = [("players", ["SMEMBERS", store.PLAYERS_KEY]),
             ("handles", ["HGETALL", store.HANDLES_KEY]),
             ("chosen", ["HGETALL", store.NAMES_KEY]),
             ("fetched", ["GET", store.NAMES_FETCHED_KEY]),
             ("titles", ["GET", store.TITLES_KEY])]
    if history:
        key = store.player_history_key(uid) if uid else store.HISTORY_KEY
        first.append(("history", ["LRANGE", key, 0, history - 1]))
    for other in dict.fromkeys(uids) if history else ():
        first.append((("of", other),
                      ["LRANGE", store.player_history_key(other), 0, history - 1]))
    if week:
        delta, played = store.week_reads()
        first += [("delta", delta), ("played", played)]
    if wallets:
        first.append(("wallets", ["HGETALL", betting.WALLET_KEY]))
    if fixtures:
        first.append(("live", ["SMEMBERS", betting.LIVE_KEY]))
    if count:
        first.append(("count", ["LLEN", store.HISTORY_KEY]))
    if shame_rows:
        first.append(("shame", ["HGETALL", shame.SHAME_KEY]))
    got = dict(zip([name for name, _ in first], kv.pipeline([c for _, c in first])))

    data.names = store.merge_names(got["handles"], got["chosen"])
    data.fetched, data.titles = got["fetched"], got["titles"]
    if week:
        data.week_delta, data.week_played = store.week_from(got["delta"], got["played"])
    if wallets:
        data.wallets = betting.balances_from(got["wallets"])
    if count:
        data.match_count = min(int(got["count"] or 0), store.HISTORY_LIMIT)
    if shame_rows:
        data.shame = shame.counts_from(got["shame"])

    # --- wave two: whatever the first wave's answers point at ---------------
    uid_list = list(got["players"] or []) if players else []
    history_ids = list(got.get("history") or [])
    per_player = {other: list(got.get(("of", other)) or []) for other in dict.fromkeys(uids)}
    match_ids = list(dict.fromkeys(history_ids + [m for ids in per_player.values() for m in ids]))
    live_ids = sorted(got.get("live") or [], key=lambda s: int(s) if str(s).isdigit() else 0)

    second, spans = [], {}

    def add(name, cmds):
        spans[name] = (len(second), len(second) + len(cmds))
        second.extend(cmds)

    add("players", [["HGETALL", store.player_key(u)] for u in uid_list])
    add("matches", _mget_cmds([store.match_key(m) for m in match_ids]))
    add("sched", _mget_cmds([betting.sched_key(s) for s in live_ids]))
    add("bets", [["HGETALL", betting.bets_key(s)] for s in live_ids])
    results = kv.pipeline(second) if second else []

    def part(name):
        start, end = spans[name]
        return results[start:end]

    data.players = store.players_from(uid_list, part("players"))
    data.has_players = bool(players)

    blobs = {}
    for mid, raw in zip(match_ids, _flatten(part("matches"))):
        if raw:
            blobs[mid] = json.loads(raw)
    data.history = [blobs[m] for m in history_ids if m in blobs]
    if history and not uid:
        data.ladder_history = data.history
    data.by_player = {other: [blobs[m] for m in ids if m in blobs]
                      for other, ids in per_player.items()}

    stale = []
    for sid, raw, placed in zip(live_ids, _flatten(part("sched")), part("bets")):
        if raw:
            data.fixtures.append(json.loads(raw))
            data.pools[sid] = betting.pool_from(betting.bets_from(placed))
        else:
            stale.append(sid)
    if stale:
        try:
            kv.srem(betting.LIVE_KEY, *stale)
        except Exception:
            pass
    return data


def _mget_cmds(keys):
    return [["MGET", *keys[i:i + kv.MGET_CHUNK]] for i in range(0, len(keys), kv.MGET_CHUNK)]


def _flatten(replies):
    out = []
    for reply in replies:
        out += reply or []
    return out
