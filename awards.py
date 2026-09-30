"""Titles — what there is to win here besides a number.

A rating says how good you are. It says nothing about who turned up four nights
running, who cannot lose at the moment, who cannot win at the moment, or who has
quietly built the biggest pile of spins. Those are the things people actually
talk about, so they get names.

**Nothing here is stored.** Every title is recomputed from matches and player
records, so there is no state to migrate, nothing to backfill, and no way for a
title to drift out of agreement with the ladder it came from. What *is* stored
is the answer, briefly: the weekly figures need a walk over the week's matches,
and neither a page nor a Slack command should pay for that on every request. The
cache is dropped the moment a match is applied, so a title never survives the
result that took it away.

**Ties.** The first tiebreak is who played more — a 3-from-3 week is a smaller
claim than 8-from-8. If two players are level on that too, nobody holds the
title: "joint On Fire" is not a thing anyone says, and a badge nobody can
uniquely claim is worse than no badge.
"""
import json
from collections import namedtuple
from datetime import timedelta

import betting
import kv
import store

# A week is the rolling seven days, not the calendar week — the same "week" that
# /tt history week and the ladder's *This week* chip mean. A title that only
# changed hands at midnight on Sunday would be a dead thing by Wednesday.
WEEK_DAYS = 7
# Floors, so a title is a claim about quality rather than about who happened to
# play once. Six games is the bar the stats page already uses for a win rate.
WEEK_MIN_MATCHES = 3
CAREER_MIN_GAMES = 6

CACHE_SECONDS = 300

Title = namedtuple("Title", "key name blurb tone icon")

# In priority order. Where a player holds more than one, this is which one rides
# beside their name; the profile and the Titles page show the lot.
TITLES = (
    Title("hot", "On Fire",
          "Best win rate over the last seven days", "up", "flame"),
    Title("machine", "The Machine",
          "Most matches played in the last seven days", "ball", "bolt"),
    Title("untouchable", "Untouchable",
          "Best win rate on the ladder, all time", "up", "crown"),
    Title("moneybags", "Moneybags",
          "The fattest wallet in the office", "up", "coin"),
    Title("cold", "Ice Cold",
          "Worst win rate over the last seven days", "down", "snow"),
)

BY_KEY = {title.key: title for title in TITLES}


def week_window(now=None):
    """[start, end) — the rolling seven days ending now."""
    now = now or store.now_ist()
    return now - timedelta(days=WEEK_DAYS), now


def match_records(blobs):
    """{uid: (matches, wins)} over a list of stored matches. A drawn session
    counts as played and not as won, the same way the player records do."""
    out = {}
    for blob in blobs:
        side_a = list(blob.get("side_a") or ())
        side_b = list(blob.get("side_b") or ())
        games_a, games_b = blob.get("games_a", 0), blob.get("games_b", 0)
        for side, won in ((side_a, games_a > games_b), (side_b, games_b > games_a)):
            for uid in side:
                played, wins = out.get(uid, (0, 0))
                out[uid] = (played + 1, wins + (1 if won else 0))
    return out


def _pick(candidates, best=max):
    """The holder, or None. `candidates` is [(uid, score, played)]; ties go to
    whoever played more, and a title nobody can uniquely claim goes unheld.

    The two keys sort in *different* directions for a `min` title. Reversing the
    whole sort instead would reverse the tiebreak with it, and hand Ice Cold to
    whoever played least — 0-from-3 over 0-from-8, which is the smaller claim to
    being the worst week going, not the larger one.
    """
    if not candidates:
        return None
    ranked = sorted(candidates,
                    key=lambda item: (item[1] if best is max else -item[1],
                                      item[2]),
                    reverse=True)
    if len(ranked) > 1:
        first, second = ranked[0], ranked[1]
        if (first[1], first[2]) == (second[1], second[2]):
            return None
    return ranked[0][0]


def compute(players, week_matches, wallets=None):
    """{title key: uid} — pure, so the whole table can be checked cold."""
    held = {}
    week = match_records(week_matches)
    eligible = [(uid, wins / played, played)
                for uid, (played, wins) in week.items()
                if played >= WEEK_MIN_MATCHES and uid in players]
    held["hot"] = _pick(eligible)
    # Ice Cold needs someone to be colder *than*. With one qualifying player
    # they are both the best and the worst week of the seven days, and wearing
    # both badges at once makes a joke of each.
    held["cold"] = _pick(eligible, best=min) if len(eligible) > 1 else None
    if held["cold"] and held["cold"] == held["hot"]:
        held["cold"] = None

    turnout = [(uid, played, played) for uid, (played, _) in week.items()
               if uid in players]
    held["machine"] = _pick(turnout)

    career = []
    for uid, player in (players or {}).items():
        games = int(player.get("games_won", 0)) + int(player.get("games_lost", 0))
        if games >= CAREER_MIN_GAMES:
            career.append((uid, player["games_won"] / games, games))
    held["untouchable"] = _pick(career)

    ranked = betting.rank_wallets(wallets or {}, list(players or ()))
    # Only a wallet that has actually moved is a standing; a table of identical
    # opening balances says nothing, exactly as the ladder page already decides.
    movers = [(uid, spins, spins) for uid, spins, net in ranked if net]
    held["moneybags"] = _pick(movers)

    return {key: uid for key, uid in held.items() if uid}


_UNREAD = object()


def current(now=None, fresh=False, cached=_UNREAD, players=None, wallets=None,
            history=None):
    """The live table, from cache when it is warm. {title key: uid}.

    A page has usually read most of what a cold cache needs already, and the
    cache goes cold after every confirmed match and every CACHE_SECONDS. So it
    can hand over what it holds: `cached` (the raw tt:titles value, None when
    it was empty), `players`, `wallets`, and `history` — recent matches newest
    first, used for the week whenever it reaches back past the week's start.
    Anything not handed over is read here, as before.
    """
    if not fresh:
        if cached is _UNREAD:
            cached = kv.get(store.TITLES_KEY)
        if cached:
            try:
                return json.loads(cached)
            except ValueError:      # a half-written cache is not worth a 500
                pass
    start, end = week_window(now)
    week = _week_from(history, start, end)
    table = compute(store.all_players() if players is None else players,
                    store.matches_in(start, end) if week is None else week,
                    betting.balances() if wallets is None else wallets)
    kv.set_(store.TITLES_KEY, json.dumps(table), ex=CACHE_SECONDS)
    return table


def _week_from(history, start, end):
    """The week's matches out of recent history, or None if that history
    doesn't reach back far enough to be sure it holds all of them."""
    stamped = [(store.applied_at(b), b) for b in history or ()]
    stamped = [(when, b) for when, b in stamped if when is not None]
    if not stamped or stamped[-1][0] >= start:
        return None
    return [b for when, b in stamped if start <= when < end]


def by_player(table):
    """{uid: [title keys]}, each in TITLES order — what a page renders from."""
    out = {}
    for title in TITLES:
        uid = (table or {}).get(title.key)
        if uid:
            out.setdefault(uid, []).append(title.key)
    return out


def holder_rows(table, names=None):
    """[(Title, uid or "")] for every title, in order — the Titles page and
    /tt titles both show the unheld ones too, because the answer to "what can I
    win here" includes the ones currently going spare."""
    return [(title, (table or {}).get(title.key, "")) for title in TITLES]
