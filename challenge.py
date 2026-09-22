"""Challenges — asking for a game, and agreeing how long it runs.

`/tt schedule` puts a fixture up as a fact: it is happening, back it if you like.
A challenge is the step before that, where the other person still gets a say. So
it carries buttons rather than a start time, and nothing is on the board until
the person being challenged says yes.

**The length is the other half of it.** "Play me" and "play me, best of five" are
different invitations, and the second is the one people actually argue about. So
a challenge names how long the session runs and both sides agree to it before
anybody walks to the table.

That agreed length is **a statement of intent, not a constraint**. It is shown on
the challenge and carried onto the fixture, but `/tt log` still takes whatever
was really played — a best-of-five that stopped at 2-0 is logged as two games,
and nothing here second-guesses it. Enforcing it would mean rejecting true
results to protect a plan, which is the wrong way round.

Accepting turns the challenge into an ordinary fixture, so betting, moving and
calling it off all work exactly as they already do. There is no second kind of
scheduled match to keep in step.
"""
import json
from datetime import datetime, timedelta

import betting
import elo
import kv
import parsing
import store

LIVE_KEY = "tt:chal:live"
SEQ_KEY = "tt:chal:seq"

# A challenge nobody answers is a dead letter, not a standing offer. Matches the
# window a logged session gets before it applies on its own.
EXPIRE_HOURS = 24
# Long enough that the sweep always finds one before Redis expires it out from
# under us, the same margin store.py leaves for pending matches.
TTL_SECONDS = 7 * 24 * 3600

# "Play me" on its own means a quick best-of-three. Short enough that saying yes
# costs twenty minutes, which is the point of a challenge you can accept on the
# way past someone's desk.
DEFAULT_GAMES = 3

# What the form offers, and the only place the wording and the numbers live
# together — the menu label is generated from the same row the rules come from,
# so a "Best of 5" that quietly meant four games is not expressible.
LENGTH_CHOICES = (
    ("bo3", 3, 2),
    ("bo5", 5, 3),
    ("bo7", 7, 4),
    ("g1", 1, None),
    ("g3", 3, None),
    ("g5", 5, None),
)
DEFAULT_CHOICE = "bo3"


def choice_label(key):
    """How one option reads in the menu — the same phrasing the challenge, the
    DM and the fixture all use, so the form never promises different words."""
    games, first_to = length_of(key)
    return length_note({"games": games, "first_to": first_to})


def length_of(key):
    """(games, first_to) for a menu key, falling back to the default rather than
    raising: a value we don't recognise came from a stale open form, and losing
    somebody's challenge over it would be worse than a best-of-three."""
    for choice, games, first_to in LENGTH_CHOICES:
        if choice == key:
            return games, first_to
    return DEFAULT_GAMES, DEFAULT_GAMES // 2 + 1


def chal_key(cid):
    return f"tt:chal:{cid}"


def issue(side_a, side_b, games, by, first_to=None, starts_at=None,
          channel="", now=None, band=None):
    """Open a challenge. `games` is the agreed session length.

    `band` is (low, high) on an **open** call — one with no `side_b`, which
    anyone rated inside the band may take. The band is stored rather than
    recomputed, because it is a promise made to the channel when it was posted.
    """
    record = {
        "id": str(kv.incr(SEQ_KEY)),
        "side_a": list(side_a), "side_b": list(side_b),
        "band": [int(band[0]), int(band[1])] if band else [],
        "games": int(games),
        "first_to": int(first_to) if first_to else None,
        "starts_at": store.stamp(starts_at) if starts_at else "",
        "from": by,
        "created_at": store.stamp(now),
        "channel": channel or "", "ts": "",
        "state": "open",
        "fixture": "",
        "answered_by": "", "answered_at": "",
    }
    save(record)
    kv.sadd(LIVE_KEY, record["id"])
    return record


def save(record):
    kv.set_(chal_key(record["id"]), json.dumps(record), ex=TTL_SECONDS)
    return record


def get(cid):
    raw = kv.get(chal_key(cid))
    return json.loads(raw) if raw else None


def live():
    """Every challenge still awaiting an answer, oldest first. An id whose JSON
    has aged out is dropped from the set rather than left to be re-read."""
    out, stale = [], []
    for cid in (kv.smembers(LIVE_KEY) or []):
        record = get(cid)
        (out.append(record) if record else stale.append(cid))
    if stale:
        kv.pipeline([["SREM", LIVE_KEY, cid] for cid in stale])
    return sorted(out, key=lambda r: int(r.get("id", 0) or 0))


def claim(cid):
    """Atomic: exactly one caller can answer a given challenge.

    Two people on the challenged side pressing Accept at the same moment would
    otherwise both put a fixture up for the same match.
    """
    return kv.srem(LIVE_KEY, cid) == 1


def release(cid):
    """Put it back when answering fell over, so it stays answerable."""
    kv.sadd(LIVE_KEY, cid)


def _finish(record, state, by, now=None):
    record["state"] = state
    record["answered_by"] = by or ""
    record["answered_at"] = store.stamp(now)
    return save(record)


def decline(record, by, now=None):
    return _finish(record, "declined", by, now)


def withdraw(record, by, now=None):
    return _finish(record, "withdrawn", by, now)


def expire(record, now=None):
    return _finish(record, "expired", "", now)


def accept(record, by, channel="", now=None, side_b=None):
    """Say yes, and turn it into an ordinary fixture.

    `side_b` fills in the far side of an open call — whoever took it, and their
    partner if it was a doubles one. It is written onto the record as well as
    into the fixture, so the settled challenge says who actually answered it.

    The fixture is the only thing that exists afterwards: betting, moving it and
    calling it off are all the machinery that already handles a scheduled match,
    so a challenge never becomes a second kind of match to keep in step.
    """
    now = now or store.now_ist()
    if side_b:
        record["side_b"] = list(side_b)
    lead = timedelta(minutes=parsing.DEFAULT_LEAD_MINUTES)
    when = starts_at(record) or (now + lead)
    if when <= now:
        # Agreed for a time that has since gone by — start the window from now
        # rather than opening a fixture that is already due.
        when = now + lead
    fixture = betting.schedule(
        record["side_a"], record["side_b"], when, created_by=record["from"],
        channel=channel or record.get("channel", ""), note=length_note(record),
        now=now)
    record["fixture"] = fixture["id"]
    _finish(record, "accepted", by, now)
    return fixture


def starts_at(record):
    try:
        return datetime.fromisoformat(record["starts_at"])
    except (KeyError, ValueError, TypeError):
        return None


def is_expired(record, now=None, hours=EXPIRE_HOURS):
    """Unanswered past its window. Keyed off the clock rather than the state, so
    one sweep settles it however many runs were missed."""
    if record.get("state") != "open":
        return False
    try:
        made = datetime.fromisoformat(record["created_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return (now or store.now_ist()) - made >= timedelta(hours=hours)


def length_note(record):
    """How the agreed length reads. One phrase, used on the challenge, the DM
    and the fixture it becomes, so all three say the same thing."""
    games, first_to = int(record.get("games", 0)), record.get("first_to")
    if first_to:
        return f"Best of {games} — first to {first_to}"
    if games == 1:
        return "One game"
    return f"{games} games"


def sides_of(record):
    return list(record.get("side_a", ())), list(record.get("side_b", ()))


def is_open_call(record):
    """An invitation to the channel rather than to a person: nobody on the far
    side yet, and a rating band in place of a name."""
    return not record.get("side_b")


def band_of(record):
    """(low, high), or None when it is aimed at named players."""
    band = record.get("band") or []
    return (int(band[0]), int(band[1])) if len(band) == 2 else None


def side_size(record):
    """How many the taker has to bring. One or two, matching whoever asked —
    you cannot answer a doubles call on your own."""
    return max(1, len(record.get("side_a", ())))


def admits(record, rating):
    """Whether a rating is inside the band. No band admits everyone.

    Checked when somebody presses, not when the call went up: people drift, and
    the honest question is whether they are a fair match *now*.
    """
    band = band_of(record)
    if not band:
        return True
    return band[0] <= rating <= band[1]


def band_note(record):
    """How the band reads on the post. One phrase, so the channel message, the
    list and the refusal all say the same thing."""
    band = band_of(record)
    if not band:
        return ""
    return f"anyone rated {band[0]}–{band[1]}"


def may_answer(record, uid):
    """Who is allowed to say yes.

    On a directed challenge, only the people being challenged. On an open call,
    anyone who isn't already in it — the challenger cannot take their own
    invitation, which is just `/tt schedule`, and neither can the partner they
    named. The rating band is a separate question (`admits`), because failing it
    deserves a different answer than not being invited.
    """
    if is_open_call(record):
        return uid not in set(record.get("side_a", ()))
    return uid in set(record.get("side_b", ()))


def may_decline(record, uid):
    """Who is allowed to say no — which is not the same set as may_answer().

    On a directed challenge they match: being asked is what gives you the
    standing to turn it down. An open call is addressed to the channel, so
    nobody has been asked and nobody can answer for everyone. Declining one
    would let a single uninterested passer-by close an invitation meant for
    forty people, which is a veto nobody was offered — so the way to decline an
    open call is to leave it alone.
    """
    if is_open_call(record):
        return False
    return may_answer(record, uid)


def may_withdraw(record, uid):
    """Whoever threw it down, or anyone on their side."""
    return uid in set(record.get("side_a", ())) or uid == record.get("from")


def open_call_by(uid):
    """This player's open challenge, if they have one out.

    `open_between` keys on the pair, and an open call has no pair — so the
    equivalent guard is one standing offer per person. Five identical callouts
    from the same player is a spammed channel, not five chances of a game.
    """
    for record in live():
        if is_open_call(record) and uid in set(record.get("side_a", ())):
            return record
    return None


def open_between(side_a, side_b):
    """An open challenge between exactly these two sides, either way round —
    so the same pair can't stack up five identical invitations."""
    want = (frozenset(side_a), frozenset(side_b))
    for record in live():
        have = (frozenset(record["side_a"]), frozenset(record["side_b"]))
        if have == want or have == want[::-1]:
            return record
    return None


def validate_length(games, first_to=None):
    """Raises ValueError with something a player can read."""
    if games < 1:
        raise ValueError("A session is at least one game.")
    if games > elo.MAX_GAMES:
        raise ValueError(f"{games} games is more than the {elo.MAX_GAMES} a "
                         "session can hold.")
    if first_to and first_to > games:
        raise ValueError(f"First to {first_to} needs more than {games} games.")
