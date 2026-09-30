"""
Rebuilding the ladder from the matches themselves.

One replay, used by two callers: `scripts/recompute.py`, to apply a scoring
change to history, and `/tt edit`, to correct a match that was logged wrong.
They share it so they cannot disagree about what the ladder *should* say.

Matches are replayed in the order they were **applied**, not the order they were
played — that is the order the original ratings were calculated in, and Elo is
not commutative, so any other order gives different numbers.

Nothing here touches spins, wallets or settled bets. A rating is not a wallet:
bets were paid on what the channel was told at the time, and a correction to the
ladder is not a reason to reach into people's balances.
"""
import json
from datetime import datetime

import elo
import kv
import parsing
import store


def load_history():
    """Every stored match, oldest application first, plus any ids we've lost."""
    ids = kv.lrange(store.HISTORY_KEY, 0, -1)
    blobs, missing = [], []
    # All of history in one round trip rather than one per match: /tt edit runs
    # this for the preview and again on apply, inside a Slack interaction. The
    # undo snapshots aren't fetched — replay() rebuilds every one of them.
    for mid, raw in zip(ids, kv.mget(store.match_key(m) for m in ids)):
        if raw:
            blobs.append(json.loads(raw))
        else:
            missing.append(mid)
    blobs.sort(key=lambda b: (b.get("applied_at", ""), int(b.get("id", 0) or 0)))
    return blobs, missing


def replay(blobs):
    """(players, rewritten blobs, weekly counters) as if the current elo.py had
    always been in force. Pure — reads nothing and writes nothing."""
    state, weekly, rewritten = {}, {}, []

    for blob in blobs:
        # Re-read the scores under today's rules, which is the point of a replay.
        # A game logged 21-0 is a skunk typed as the number they play to; the
        # rating is identical either way, but the points totals shouldn't carry
        # ten points nobody played.
        blob = dict(blob, games=parsing.normalise_games(
            [tuple(g) for g in blob["games"]]))
        uids = blob["side_a"] + blob["side_b"]
        for uid in uids:
            state.setdefault(uid, store.new_player())

        def entries(side):
            return [{"uid": u, "rating": state[u]["rating"],
                     "games": elo.games_played(state[u])} for u in side]

        rated = elo.rate_match(entries(blob["side_a"]), entries(blob["side_b"]),
                               blob["games"])
        try:
            applied = datetime.fromisoformat(blob["applied_at"])
        except (KeyError, ValueError):
            applied = store.now_ist()

        # Each format carries its own Elo, so it is replayed on its own ratings
        # rather than derived from the overall pass.
        prefix = store.DOUBLES if rated["doubles"] else store.SINGLES

        def split_entries(side):
            return [{"uid": u,
                     "rating": store.split_view(state[u], prefix)["rating"],
                     "games": elo.games_played(store.split_view(state[u], prefix))}
                    for u in side]

        split = elo.rate_match(split_entries(blob["side_a"]),
                               split_entries(blob["side_b"]), blob["games"],
                               doubles_factor=elo.DOUBLES_OWN_K_FACTOR)

        snapshot = {uid: dict(state[uid]) for uid in uids}
        for side, mine, theirs in ((blob["side_a"], "a", "b"),
                                   (blob["side_b"], "b", "a")):
            for uid in side:
                advanced = store._advance(state[uid], rated, mine, theirs, uid,
                                          blob["id"], applied)
                advanced.update(store._advance_split(
                    state[uid], split, mine, theirs, uid, blob["id"], applied, prefix))
                state[uid] = advanced

        week = store.week_key(applied)
        bucket = weekly.setdefault(week, {"delta": {}, "played": {}})
        for uid in uids:
            bucket["delta"][uid] = bucket["delta"].get(uid, 0) + rated["deltas"][uid]
            bucket["played"][uid] = bucket["played"].get(uid, 0) + 1

        fresh = dict(blob)
        fresh.update(rated)
        fresh["split_rated"] = split
        fresh["split_prefix"] = prefix
        fresh["singles_rated"] = split if prefix == store.SINGLES else {}
        fresh["snapshot"] = snapshot
        fresh["week"] = week
        rewritten.append(fresh)

    return state, rewritten, weekly


def write(state, rewritten, weekly, before=None):
    """Commit a replay. `before` supplies the joined-on dates to preserve."""
    before = before if before is not None else store.get_players(list(state))
    # A replay rewrites the results titles are computed from, so it takes the
    # cached table with it — the same way applying and undoing a match do.
    writes = [["DEL", store.TITLES_KEY]]
    for uid, player in state.items():
        # Keep the day they joined; everything else is derived from the replay.
        player["joined"] = (before.get(uid) or {}).get("joined") or player["joined"]
        writes.append(["HSET", store.player_key(uid)] + store._flatten(player))
    for blob in rewritten:
        writes += store.match_writes(blob)

    # Weekly counters are rebuilt, not adjusted: clearing first is the only way
    # to be sure a stale week isn't left behind to be added to.
    for key in kv.scan("tt:wk:*"):
        writes.append(["DEL", key])
    for week, bucket in weekly.items():
        for field, values in (("delta", bucket["delta"]), ("played", bucket["played"])):
            args = []
            for uid, value in values.items():
                args += [uid, value]
            if args:
                writes.append(["HSET", f"{week}:{field}"] + args)

    for i in range(0, len(writes), 50):
        kv.pipeline(writes[i:i + 50])
    return len(writes)


# --- correcting a match that was logged wrong ------------------------------

class EditError(Exception):
    """Phrased for the admin who typed it."""


def _apply_edit(blob, games=None, swap=False):
    """The edited blob, or None to drop the match entirely."""
    if games is None and not swap:
        return None                       # void
    edited = dict(blob)
    if games is not None:
        edited["games"] = games
    if swap:
        # Only the names move. The scores stay in the columns they were typed
        # in, which is what flips the result: turning the score columns round as
        # well would invert it twice and leave the match exactly as it was.
        edited["side_a"], edited["side_b"] = edited["side_b"], edited["side_a"]
    return edited


def plan_edit(mid, games=None, swap=False):
    """What editing match `mid` would do, computed but not written.

    Returns (plan, state, rewritten, weekly). The plan is everything the preview
    and the announcement need; the other three are what write() commits, so the
    numbers a person approves are the exact numbers that get stored.

    Editing an old match re-rates every match after it, because those were rated
    against ratings this one produced. That is the honest thing to do and the
    reason this goes through the whole replay rather than patching one record.
    """
    blobs, missing = load_history()
    if missing:
        raise EditError(
            f"{len(missing)} match{'es' if len(missing) > 1 else ''} in the history "
            "have no stored record, so a replay would be built on an incomplete "
            "ladder. Nothing changed.")
    mid = str(mid)
    target = next((b for b in blobs if str(b["id"]) == mid), None)
    if target is None:
        raise EditError(f"No match `#{mid}` in the history I can still see.")

    edited = _apply_edit(target, games=games, swap=swap)
    if edited is not None and edited["games"] == [tuple(g) for g in target["games"]] \
            and edited["side_a"] == target["side_a"]:
        raise EditError(f"That's what `#{mid}` already says — nothing to change.")

    after = [edited if str(b["id"]) == mid else b
             for b in blobs if edited is not None or str(b["id"]) != mid]
    before_state = {uid: dict(p) for uid, p in replay(blobs)[0].items()}
    state, rewritten, weekly = replay(after)

    # Anyone who was in the edited match or any match after it can move.
    moved = {uid: (before_state.get(uid, store.new_player())["rating"],
                   player["rating"])
             for uid, player in state.items()}
    moved = {uid: pair for uid, pair in moved.items() if pair[0] != pair[1]}
    # A player only in the voided match leaves the ladder's numbers behind.
    for uid, player in before_state.items():
        if uid not in state:
            moved[uid] = (player["rating"], elo.START_RATING)

    plan = {
        "id": mid,
        "void": edited is None,
        "before": {"side_a": target["side_a"], "side_b": target["side_b"],
                   "games": [tuple(g) for g in target["games"]]},
        "after": None if edited is None else {
            "side_a": edited["side_a"], "side_b": edited["side_b"],
            "games": [tuple(g) for g in edited["games"]]},
        "moved": moved,
        "replayed": sum(1 for b in blobs if str(b["id"]) != mid
                        and _applied_after(b, target)),
        "winner_flipped": edited is not None and _winner(target) != _winner(edited),
    }
    return plan, state, rewritten, weekly


def _applied_after(blob, target):
    return (blob.get("applied_at", ""), int(blob.get("id", 0) or 0)) > \
           (target.get("applied_at", ""), int(target.get("id", 0) or 0))


def _winner(blob):
    """Which side took the session, as a frozenset of uids — None if drawn."""
    games_a, games_b, _, _ = elo.tally([tuple(g) for g in blob["games"]])
    if games_a == games_b:
        return None
    return frozenset(blob["side_a"] if games_a > games_b else blob["side_b"])


def commit_edit(plan, state, rewritten, weekly):
    """Write a planned edit. Everything write() does, plus the tidying a void
    needs: the match itself, its place in the history lists, and any player left
    with no matches at all once it's gone."""
    before = store.get_players(list(state) + list(plan["moved"]))
    write(state, rewritten, weekly, before=before)

    cmds = []
    if plan["void"]:
        mid = plan["id"]
        cmds.append(["DEL", store.match_key(mid), store.snap_key(mid)])
        cmds.append(["LREM", store.HISTORY_KEY, 0, mid])
        for uid in plan["before"]["side_a"] + plan["before"]["side_b"]:
            cmds.append(["LREM", store.player_history_key(uid), 0, mid])
    # Someone whose only match was voided keeps their registration but goes back
    # to the start line, rather than keeping a rating nothing supports any more.
    for uid in plan["moved"]:
        if uid not in state:
            fresh = store.new_player()
            fresh["joined"] = (before.get(uid) or {}).get("joined") or fresh["joined"]
            cmds.append(["HSET", store.player_key(uid)] + store._flatten(fresh))
    if cmds:
        kv.pipeline(cmds)
