"""The wall of shame — who won't play, and who won't admit they did.

A rating says how you do when you turn up. This is the other half: the results
thrown out, the challenges ducked, and the ones left to rot without an answer.

**Counted at the moment it happens, never derived.** A thrown-out result deletes
its pending record — that is the point of throwing it out — so there is nothing
left afterwards to count from. The same goes for a challenge that expires: it
ages out of Redis within the week. So each of these bumps a counter as it
happens, and the counter is the record.

**Nothing here is a judgement about a person.** Throwing out a wrong scoreline
is the ladder working, ducking a challenge you would lose is human, and a
challenge you never saw is not a moral failing. It is a leaderboard of
friction, played for laughs, and the wording is chosen so it reads that way —
if it ever stops reading that way, delete the board rather than the counters.
"""
import kv

SHAME_KEY = "tt:shame"

# Ordered worst-first, which is also the order the board reads in.
KINDS = (
    ("rejected", "Thrown out",
     "Results they pressed *That's wrong* on", ":wastebasket:"),
    ("ducked", "Ducked",
     "Challenges they turned down", ":turtle:"),
    ("ghosted", "Ghosted",
     "Challenges they never answered at all", ":ghost:"),
    ("bailed", "Bailed",
     "Fixtures called off, or left without a result", ":no_entry_sign:"),
)
BY_KIND = {key: (name, blurb, icon) for key, name, blurb, icon in KINDS}

# What each kind costs on the running total. A thrown-out result is the one that
# actually costs somebody else something — they have to log it again — so it
# weighs most. A challenge nobody answered might never have been seen.
WEIGHTS = {"rejected": 3, "ducked": 2, "ghosted": 1, "bailed": 1}


def _field(uid, kind):
    return f"{uid}:{kind}"


def record(uid, kind, n=1):
    """Bump one player's count. Never raises: a wall of shame is a bit of fun
    hanging off the side of a match flow, and it has no business turning a
    confirmed result into an error somebody sees."""
    if not uid or kind not in BY_KIND:
        return
    try:
        kv.hincrby(SHAME_KEY, _field(uid, kind), int(n))
    except Exception:
        pass


def record_many(uids, kind):
    for uid in dict.fromkeys(u for u in uids if u):
        record(uid, kind)


def counts():
    """{uid: {kind: n}} — everyone with anything against their name."""
    out = {}
    for field, raw in (kv.hgetall(SHAME_KEY) or {}).items():
        uid, _, kind = str(field).rpartition(":")
        if not uid or kind not in BY_KIND:
            continue
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.setdefault(uid, {})[kind] = n
    return out


def score(row):
    """One player's running total, weighted by how much each kind actually
    costs somebody else."""
    return sum(WEIGHTS.get(kind, 1) * n for kind, n in (row or {}).items())


def board(limit=10, players=None):
    """[(uid, row, score)] worst first — the wall itself.

    Ties break on uid so two people level don't swap places between refreshes,
    the same rule the spins table already uses.
    """
    rows = counts()
    if players is not None:
        rows = {uid: row for uid, row in rows.items() if uid in players}
    ranked = sorted(rows.items(), key=lambda item: (-score(item[1]), item[0]))
    return [(uid, row, score(row)) for uid, row in ranked[:limit] if score(row)]


def total(kind=None):
    """How much friction there has been in all, or of one kind."""
    rows = counts()
    if kind:
        return sum(row.get(kind, 0) for row in rows.values())
    return sum(sum(row.values()) for row in rows.values())


def for_player(uid):
    return counts().get(uid, {})


def clear(uid=None):
    """Wipe one person's record, or the whole wall. For an admin undoing a
    miscount — the counters have no history to replay them from, so this is the
    only way back."""
    if uid is None:
        kv.delete(SHAME_KEY)
        return
    kv.pipeline([["HDEL", SHAME_KEY, _field(uid, kind)] for kind, *_ in KINDS])


def summary(row):
    """The same, as plain words, for a web page or a player card."""
    bits = []
    for kind, name, _, _ in KINDS:
        if row.get(kind):
            bits.append(f"{row[kind]} {name.lower()}")
    return ", ".join(bits)
