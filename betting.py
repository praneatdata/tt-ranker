"""
Spins — the office currency — and the pools people stake them into.

A scheduled match opens a betting window that shuts the moment the match is due
to start. Everyone who backed the winning side splits the whole pot in
proportion to what they staked.

**Pari-mutuel, not fixed odds.** Nobody here is the bookmaker. Every spin paid
out came from another player's stake, so the money supply can't inflate however
many upsets land, and there is no house to go bust. The cost is that you don't
know your exact return when you stake — so the match message carries a live "if
it settled now" figure, and the Elo-implied odds beside it as a guide.

Two rules the maths rests on:

1. **Stakes are taken when the bet is placed, payouts credited at settlement.**
   A wallet can never go negative, and an abandoned match refunds exactly what
   went in.
2. **The pot is conserved to the last spin.** Proportional shares are floored,
   and the rounding remainder goes to the largest winning stake rather than
   quietly evaporating.

Players may bet on their own matches, including against themselves. That's a
deliberate house rule, so the only guard is daylight: `backing_against_self()`
flags it and the match message says so out loud.
"""
import json
from datetime import datetime, timedelta

import elo
import kv
import parsing
import store

CURRENCY = "spins"
START_SPINS = 5000
# Handed to every player at the start of each week. The cron jobs call the payer
# and it claims each week once, so whichever job fires first that week pays and
# the rest are no-ops.
#
# Set to zero, the only spins in the system are the ones people opened with: the
# pool is finite and losing costs something real. But a player who busts out then
# stays busted until an admin moves some across with `/tt transfer`, and people
# did bust out. This is the floor that lets them back in — losing everything
# costs you a week, not the game.
WEEKLY_STIPEND = 1000
MIN_BET = 5

# Winning a session pays, scaled to how convincing it was — by games, because
# that is what "close" and "wipeout" mean to the person who played it.
#
# **This mints.** Until now the weekly stipend was the only thing that created
# spins, and everything else was strictly zero-sum; a prize is new money by
# definition. It stays small on purpose: a whole week of matches pays out a
# small fraction of one week's stipend, so the pool grows slowly enough that a
# wallet still means what it did. If that stops being true, this is the dial.
WIN_PRIZE = ((3, 20, "wipeout"), (2, 10, "decent"), (1, 5, "close"))

WALLET_KEY = "tt:wallet"
LIVE_KEY = "tt:sched:live"
SEQ_KEY = "tt:sched:seq"
STIPEND_KEY = "tt:stipend:paid"
LEDGER_LIMIT = 30
# Long enough that a match nobody ever reports still gets swept and refunded.
SCHED_TTL_SECONDS = 14 * 24 * 3600
# A scheduled match whose result never arrives is voided and refunded after this.
ABANDON_HOURS = 48


def sched_key(sid):
    return f"tt:sched:{sid}"


def bets_key(sid):
    return f"tt:bets:{sid}"


def ledger_key(uid):
    return f"tt:ledger:{uid}"


# --- wallets ---------------------------------------------------------------

def ensure_wallets(uids):
    """Open a wallet for anyone who hasn't got one. HSETNX so an existing
    balance is never reset by someone merely being looked at."""
    uids = [u for u in dict.fromkeys(uids) if u]
    if uids:
        kv.pipeline([["HSETNX", WALLET_KEY, u, START_SPINS] for u in uids])
    return uids


def balance(uid):
    raw = kv.hget(WALLET_KEY, uid)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return START_SPINS  # never opened one; this is what it would hold


def balances():
    out = {}
    for uid, raw in (kv.hgetall(WALLET_KEY) or {}).items():
        try:
            out[uid] = int(raw)
        except (TypeError, ValueError):
            continue
    return out


def standings(uids=None):
    """The spins leaderboard: [(uid, held, net)] richest first.

    Pure ranking over `balances()`. Anyone in `uids` without a wallet is ranked
    at START_SPINS, because that is what their wallet would hold the moment it
    was opened — `balance()` already reads it that way. Ties break on uid so the
    order is stable between two refreshes.
    """
    return rank_wallets(balances(), uids)


def rank_wallets(held, uids=None):
    """Sort wallets richest first, filling in anyone who never opened one. Kept
    separate from the store read so the ranking itself can be tested cold."""
    table = {u: START_SPINS for u in (uids or []) if u}
    table.update(held or {})
    ranked = sorted(table.items(), key=lambda item: (-item[1], item[0]))
    return [(uid, spins, spins - START_SPINS) for uid, spins in ranked]


def circulating(uids=None):
    """Every spin in existence: in wallets, plus whatever is staked on a fixture
    that has not settled.

    A stake has left its wallet but not the economy — it comes back at
    settlement. Counting wallets alone makes the total appear to shrink whenever
    betting is open, which is exactly when someone is most likely to look.

    Fills in anyone in `uids` without a wallet at START_SPINS, the same way
    standings() does, so the total and the table it sits under agree.
    """
    held = {u: START_SPINS for u in (uids or []) if u}
    held.update(balances() or {})
    return sum(held.values()) + sum(pool(r["id"])["total"] for r in live())


def adjust(uid, amount, reason, now=None):
    """Move a wallet and note why. Returns the new balance."""
    ensure_wallets([uid])
    new = int(kv.hincrby(WALLET_KEY, uid, int(amount)))
    entry = json.dumps({"at": store.stamp(now), "delta": int(amount),
                        "reason": reason, "balance": new})
    try:
        kv.pipeline([["LPUSH", ledger_key(uid), entry],
                     ["LTRIM", ledger_key(uid), 0, LEDGER_LIMIT - 1]])
    except Exception:
        pass  # the ledger is a courtesy; the balance is the truth
    return new


def ledger(uid, limit=10):
    out = []
    for raw in kv.lrange(ledger_key(uid), 0, max(0, limit - 1)):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out


def transfer(sender, recipient, amount, by=None, now=None):
    """Move spins from one wallet to another. Returns (ok, message).

    Zero-sum on purpose: it debits and credits the same number, so the only
    thing in the system that mints spins is still the Monday stipend. An admin
    handing out a prize is a transfer out of their own wallet, not new money.
    """
    if not (sender and recipient):
        return False, "Who's paying whom?"
    if sender == recipient:
        return False, "That's the same wallet."
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, f"How many {CURRENCY}? Whole numbers only."
    if amount < 1:
        return False, f"That has to be at least 1 {CURRENCY}."

    ensure_wallets([sender, recipient])
    held = balance(sender)
    if amount > held:
        return False, f"<@{sender}> only has {held:,} {CURRENCY}."

    # Named both ways in the ledger, and marked when a third party moved it, so
    # /tt wallet can always answer "where did that come from".
    hand = f" by <@{by}>" if by and by not in (sender, recipient) else ""
    adjust(sender, -amount, f"sent to <@{recipient}>{hand}", now)
    adjust(recipient, amount, f"from <@{sender}>{hand}", now)
    return True, (f"Moved *{amount:,} {CURRENCY}* from <@{sender}> to "
                  f"<@{recipient}>.")


# --- winning pays -----------------------------------------------------------

def prize_for(games_a, games_b):
    """(spins, what it reads as) for the winning side. (0, "") for a draw.

    A pure function of the scoreline, which is what lets an undo reverse it
    exactly without anything having been written down at the time.
    """
    margin = abs(int(games_a) - int(games_b))
    if not margin:
        return 0, ""
    for least, amount, label in WIN_PRIZE:
        if margin >= least:
            return amount, label
    return 0, ""


def winners_of(blob):
    """The side that took the session, or [] if nobody did."""
    ga, gb = blob.get("games_a", 0), blob.get("games_b", 0)
    if ga == gb:
        return []
    return list(blob["side_a"] if ga > gb else blob["side_b"])


def pay_prize(blob, now=None):
    """Credit the winners. Returns {uid: spins}, empty on a draw.

    Each winner is paid in full rather than the pair splitting one prize: it is
    a prize for winning, and halving it for doubles would make the sensible move
    "play singles for the money".
    """
    amount, label = prize_for(blob.get("games_a", 0), blob.get("games_b", 0))
    winners = winners_of(blob)
    if not (amount and winners):
        return {}
    ensure_wallets(winners)
    for uid in winners:
        adjust(uid, amount, f"won a match ({label})", now)
    return {uid: amount for uid in winners}


def take_back_prize(blob, now=None):
    """Reverse what pay_prize gave, for an undone match. Recomputed from the
    scoreline rather than read back, so the two can never disagree."""
    amount, label = prize_for(blob.get("games_a", 0), blob.get("games_b", 0))
    winners = winners_of(blob)
    if not (amount and winners):
        return {}
    for uid in winners:
        adjust(uid, -amount, f"match undone ({label})", now)
    return {uid: -amount for uid in winners}


def pay_stipend(week=None, now=None):
    """Top every wallet up once a week. Idempotent per week — the claim is the
    SADD, so a cron retry can't pay twice."""
    week = week or store.week_key(now)
    if WEEKLY_STIPEND <= 0:
        # Claim nothing: turning it back on later should pay the week it is
        # turned on in, not skip it because a disabled run marked it done.
        return {"status": "disabled", "week": week}
    if kv.sadd(STIPEND_KEY, week) != 1:
        return {"status": "already_paid", "week": week}
    players = list(store.all_players())
    if not players:
        kv.srem(STIPEND_KEY, week)  # nothing to pay; let a later run try
        return {"status": "no_players", "week": week}
    ensure_wallets(players)
    for uid in players:
        adjust(uid, WEEKLY_STIPEND, "weekly stipend", now)
    return {"status": "paid", "week": week, "players": len(players),
            "each": WEEKLY_STIPEND}


# --- scheduling ------------------------------------------------------------

def schedule(side_a, side_b, starts_at, created_by, channel="", note="", now=None):
    """Open a match and its betting window."""
    record = {
        "id": str(kv.incr(SEQ_KEY)),
        "side_a": list(side_a), "side_b": list(side_b),
        "starts_at": store.stamp(starts_at),
        "created_by": created_by,
        "created_at": store.stamp(now),
        "channel": channel or "", "ts": "",
        "note": note or "",
        "state": "open",
        "winner": "", "settled_at": "", "match_id": "",
    }
    save(record)
    kv.sadd(LIVE_KEY, record["id"])
    ensure_wallets(side_a + side_b + [created_by])
    return record


def save(record):
    kv.set_(sched_key(record["id"]), json.dumps(record), ex=SCHED_TTL_SECONDS)
    return record


def get(sid):
    raw = kv.get(sched_key(sid))
    return json.loads(raw) if raw else None


def live():
    """Every match not yet settled or voided, oldest first. Ids whose JSON has
    expired drop out of the index on the way past."""
    ids = sorted(kv.smembers(LIVE_KEY), key=lambda s: int(s) if s.isdigit() else 0)
    if not ids:
        return []
    raws = kv.pipeline([["GET", sched_key(i)] for i in ids])
    out, stale = [], []
    for sid, raw in zip(ids, raws):
        (out if raw else stale).append(json.loads(raw) if raw else sid)
    if stale:
        kv.srem(LIVE_KEY, *stale)
    return out


def starts_at(record):
    try:
        return datetime.fromisoformat(record["starts_at"])
    except (KeyError, ValueError):
        return None


def is_due(record, now=None):
    when = starts_at(record)
    return bool(when and (now or store.now_ist()) >= when)


def close_if_due(record, now=None):
    """Shut the betting window the moment the match is due.

    Checked on read as well as by the sweep: crons run daily, and a window that
    stayed open because nothing had run yet would let people bet on a match
    already in progress.
    """
    if record.get("state") == "open" and is_due(record, now):
        record["state"] = "closed"
        save(record)
        return True
    return False


def reschedule(record, when, by="", now=None):
    """Move a fixture's start time. Returns (ok, message).

    Plans change, and the alternative people were using was calling the match
    off and putting it up again — which hands every stake back and loses the
    pool. Moving the time keeps the bets, because the bet was on who wins, not
    on when they played.

    **A window that has already shut stays shut.** If the old start time has
    passed, the match may have begun, and anyone who watched two games knows
    something the pool does not. Reopening betting on the strength of a
    postponement is the one way this could be used to steal spins, so a closed
    fixture moves its time and keeps its pool frozen. An open one stays open.
    """
    now = now or store.now_ist()
    state = record.get("state")
    if state not in ("open", "closed"):
        return False, f"That fixture is already {state or 'gone'}."
    if when <= now:
        return False, "That time has already gone by."
    if when - now > timedelta(days=parsing.MAX_LEAD_DAYS):
        return False, (f"That's more than {parsing.MAX_LEAD_DAYS} days out — "
                       "put it up nearer the time.")
    was = starts_at(record)
    if was and abs((when - was).total_seconds()) < 60:
        return False, "That's when it was already set for."

    record["starts_at"] = store.stamp(when)
    record["moved_at"] = store.stamp(now)
    record["moved_by"] = by or ""
    record["moves"] = int(record.get("moves", 0)) + 1
    save(record)
    return True, ""


def is_abandoned(record, now=None, hours=ABANDON_HOURS):
    """Long past its start with no result in. Deliberately keyed off the clock
    rather than the state: a fixture that is both overdue and abandoned must be
    closed *and* refunded by the same sweep, not one per daily run."""
    when = starts_at(record)
    return bool(record.get("state") in ("open", "closed") and when
                and (now or store.now_ist()) - when >= timedelta(hours=hours))


# --- bets ------------------------------------------------------------------

def bets(sid):
    """{uid: (side, amount)} for one match."""
    out = {}
    for uid, raw in (kv.hgetall(bets_key(sid)) or {}).items():
        side, _, amount = str(raw).partition(":")
        try:
            out[uid] = (side, int(amount))
        except ValueError:
            continue
    return out


def pool(sid):
    """The pot, split by side, plus how many people are on each."""
    placed = bets(sid)
    totals = {"a": 0, "b": 0}
    backers = {"a": 0, "b": 0}
    for side, amount in placed.values():
        if side in totals:
            totals[side] += amount
            backers[side] += 1
    return {"a": totals["a"], "b": totals["b"], "total": totals["a"] + totals["b"],
            "backers_a": backers["a"], "backers_b": backers["b"], "bets": placed}


def projected(pot, side):
    """What a spin on `side` returns if the pot settled as it stands. 0.0 means
    nobody is on that side yet, so any stake would take the lot."""
    staked = pot["a"] if side == "a" else pot["b"]
    if not staked:
        return 0.0
    return pot["total"] / staked


def place_bet(record, uid, side, amount, now=None):
    """Stake spins on a side. Returns (ok, message).

    The stake leaves the wallet now. Settlement only ever credits, so a wallet
    cannot go negative and a voided match refunds exactly what went in.
    """
    if side not in ("a", "b"):
        return False, "Pick a side."
    close_if_due(record, now)
    if record["state"] != "open":
        when = starts_at(record)
        shut = when.strftime("%H:%M") if when else "already"
        return False, (f"Betting on `#{record['id']}` closed at {shut} — "
                       "the match is under way.")
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return False, f"How many {CURRENCY}? Whole numbers only."
    if amount < MIN_BET:
        return False, f"Smallest stake is {MIN_BET} {CURRENCY}."

    ensure_wallets([uid])
    existing = bets(record["id"]).get(uid)
    if existing and existing[0] != side:
        return False, (f"You're already on the other side of `#{record['id']}` "
                       f"for {existing[1]} {CURRENCY}. Pick one.")
    held = balance(uid)
    if amount > held:
        return False, f"You have {held} {CURRENCY}."

    adjust(uid, -amount, f"stake on #{record['id']}", now)
    staked = (existing[1] if existing else 0) + amount
    kv.hset(bets_key(record["id"]), uid, f"{side}:{staked}")
    return True, (f"{amount} {CURRENCY} on "
                  f"{'their' if side == 'a' else 'the other'} side — "
                  f"you're in for {staked}.")


def backing_against_self(record):
    """Players who staked on the side they aren't playing for.

    Allowed by house rule, so the guard is visibility: the match message names
    them, and everyone can draw their own conclusions.
    """
    placed = bets(record["id"])
    out = []
    for uid, (side, amount) in placed.items():
        mine = "a" if uid in record["side_a"] else ("b" if uid in record["side_b"] else None)
        if mine and side != mine:
            out.append((uid, amount))
    return sorted(out)


# --- settlement ------------------------------------------------------------

def payouts(placed, winner):
    """{uid: spins returned}. Losers get 0; a void or a no-winner pot refunds.

    Shares are floored and the remainder handed to the largest winning stake, so
    the pot comes out to exactly what went in — spins are never quietly burned.
    """
    total = sum(amount for _, amount in placed.values())
    if not total:
        return {}
    if winner not in ("a", "b"):
        return {uid: amount for uid, (_, amount) in placed.items()}
    winning = {uid: amount for uid, (side, amount) in placed.items() if side == winner}
    won_total = sum(winning.values())
    if not won_total:
        return {uid: amount for uid, (_, amount) in placed.items()}

    out = {uid: (amount * total) // won_total for uid, amount in winning.items()}
    remainder = total - sum(out.values())
    if remainder:
        out[max(winning, key=lambda u: (winning[u], u))] += remainder
    for uid in placed:
        out.setdefault(uid, 0)
    return out


def claim(sid):
    """Take a match out of the live index. True for exactly one caller, so a
    settlement and a sweep racing each other can't pay a pot twice."""
    return kv.srem(LIVE_KEY, sid) == 1


def settle(record, winner, match_id="", now=None):
    """Pay out a decided match. The caller must have won claim() first."""
    placed = bets(record["id"])
    paid = payouts(placed, winner)
    for uid, amount in paid.items():
        if amount:
            adjust(uid, amount, f"#{record['id']} settled", now)
    record.update({"state": "settled", "winner": winner,
                   "settled_at": store.stamp(now), "match_id": match_id or "",
                   "payouts": paid, "staked": {u: a for u, (_, a) in placed.items()}})
    save(record)
    return record


def void(record, reason="", now=None):
    """Call it off and hand every stake back."""
    placed = bets(record["id"])
    for uid, (_, amount) in placed.items():
        adjust(uid, amount, f"#{record['id']} refunded", now)
    record.update({"state": "void", "voided_at": store.stamp(now),
                   "reason": reason, "refunds": {u: a for u, (_, a) in placed.items()}})
    save(record)
    return record


def side_of(record, side_a, side_b):
    """Which side of a scheduled match a confirmed session corresponds to, or
    None if it isn't the same fixture. Order within a side doesn't matter, and
    neither does which side was typed first."""
    mine, theirs = set(record["side_a"]), set(record["side_b"])
    got_a, got_b = set(side_a), set(side_b)
    if (mine, theirs) == (got_a, got_b):
        return "same"
    if (mine, theirs) == (got_b, got_a):
        return "flipped"
    return None


def find_for_result(side_a, side_b):
    """The scheduled match a just-confirmed session settles, if any.

    Matched on the players alone, so nobody has to quote an id when logging.
    Oldest first, so a standing fixture between two regulars settles in order.
    """
    for record in live():
        if record.get("state") in ("open", "closed") and side_of(record, side_a, side_b):
            return record
    return None


def winner_from(record, side_a, games_a, games_b):
    """"a" | "b" | "draw" — the result expressed in the *scheduled* match's
    terms, whichever way round the session happened to be logged."""
    if games_a == games_b:
        return "draw"
    session_a_won = games_a > games_b
    logged_same_way = set(record["side_a"]) == set(side_a)
    if logged_same_way:
        return "a" if session_a_won else "b"
    return "b" if session_a_won else "a"


def elo_odds(record):
    """(chance side A takes a game, chance side B does) from current ratings —
    shown next to the pool as a sanity check on what the crowd thinks."""
    players = store.load_for_match(record["side_a"] + record["side_b"])
    entries = lambda side: [{"uid": u, "rating": players[u]["rating"],
                             "games": elo.games_played(players[u])} for u in side]
    chance = elo.win_probability(entries(record["side_a"]), entries(record["side_b"]))
    return chance, 1.0 - chance
