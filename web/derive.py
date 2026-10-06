"""Form, movement and streaks, derived from stored matches.

Pure functions over the match blobs `store` already writes — nothing here reads
or writes the database, and nothing here recalculates a rating. A blob carries
`deltas` (the overall Elo) and `split_rated.deltas` (that format's own Elo), so
per-format movement is a matter of reading the right one, never of re-rating.

Every function returns only what the data supports. A player with no matches in
the window gets no form; a week with no matches produces no movement. The page
is expected to say "no games" rather than invent a zero that looks like one.
"""

FORM_SHOWN = 5

# view values, matching page.VIEWS: "" is singles, the others are named.
OVERALL = "overall"
DOUBLES = "doubles"


def in_view(blob, view):
    """Does this match belong to the format the tab is showing?"""
    if view == OVERALL:
        return True
    return bool(blob.get("doubles")) == (view == DOUBLES)


def deltas_of(blob, view):
    """The rating changes this match applied, on the ladder being shown.

    The format tabs read the format's own Elo. Matches stored before doubles
    had its own ladder carry `singles_rated` instead, and a doubles match from
    back then carries neither — those contribute nothing rather than borrowing
    the overall figure, which measures a different ladder.
    """
    if view == OVERALL:
        return blob.get("deltas") or {}
    split = blob.get("split_rated") or blob.get("singles_rated") or {}
    return split.get("deltas") or {}


def result_of(blob, uid):
    """W, L or D for one player in one match — None if they weren't in it."""
    if uid in blob.get("side_a", ()):
        mine, theirs = blob["games_a"], blob["games_b"]
    elif uid in blob.get("side_b", ()):
        mine, theirs = blob["games_b"], blob["games_a"]
    else:
        return None
    return "W" if mine > theirs else "L" if mine < theirs else "D"


def form(history, view, limit=FORM_SHOWN):
    """{uid: "WWLDW"} — each player's last `limit` results, oldest first.

    `history` is newest-first, as `store.recent_matches` returns it, so results
    are collected newest-first and reversed on the way out: read left to right,
    the last letter is the most recent match.
    """
    out = {}
    for blob in history:
        if not in_view(blob, view):
            continue
        for uid in tuple(blob.get("side_a", ())) + tuple(blob.get("side_b", ())):
            if len(out.get(uid, "")) >= limit:
                continue
            result = result_of(blob, uid)
            if result:
                out[uid] = out.get(uid, "") + result
    return {uid: results[::-1] for uid, results in out.items()}


def weekly(history, view, week):
    """({uid: rating change}, {uid: matches played}) for one week of one format.

    `week` is the key `store.week_key()` produces and every applied match
    records, so the window is selected by equality rather than by re-parsing
    timestamps — the same bucket the weekly Slack post reports on.
    """
    delta, played = {}, {}
    for blob in history:
        if blob.get("week") != week or not in_view(blob, view):
            continue
        changes = deltas_of(blob, view)
        for uid in tuple(blob.get("side_a", ())) + tuple(blob.get("side_b", ())):
            played[uid] = played.get(uid, 0) + 1
            delta[uid] = delta.get(uid, 0) + int(changes.get(uid, 0))
    return delta, played


def rank_movement(ranked, delta):
    """{uid: places climbed} over a week — positive is up, negative is down.

    Rank isn't stored, so it is reconstructed: take each player's rating a week
    ago (what they have now, less what they gained this week), re-rank the same
    field on those numbers, and compare. That answers "did I pass anyone?",
    which includes being passed while you weren't playing — a real fall, and the
    one the ladder is actually about.

    Approximate in one way worth knowing: the field is today's ranked players,
    so someone who qualified mid-week isn't shown as having entered from
    nowhere. They simply have no movement until their first full week.
    """
    if not ranked or not any(delta.values()):
        return {}
    before = sorted(((uid, player["rating"] - delta.get(uid, 0)) for uid, player in ranked),
                    key=lambda item: (-item[1], item[0]))
    was = {uid: i for i, (uid, _) in enumerate(before)}
    return {uid: was[uid] - now for now, (uid, _) in enumerate(ranked) if uid in was}


def active_this_week(played):
    """How many people have played at all this week."""
    return sum(1 for count in (played or {}).values() if count)


# --- rating history ---------------------------------------------------------

def ratings_of(blob, view):
    """(before, after) rating maps for the ladder being shown.

    Same rule as `deltas_of`: a format tab reads that format's own Elo, and a
    match too old to carry one contributes nothing rather than borrowing the
    overall figure.
    """
    if view == OVERALL:
        return blob.get("before") or {}, blob.get("after") or {}
    split = blob.get("split_rated") or blob.get("singles_rated") or {}
    return split.get("before") or {}, split.get("after") or {}


def rating_series(history, uid, view):
    """[(when, rating), …] oldest first — one point per match, plus the rating
    this player started the window on.

    Read straight out of the stored before/after pair, so the line is the
    rating that actually applied after each match. Nothing is interpolated and
    nothing is re-rated; a match that carries no figure for this format is
    skipped rather than drawn flat.
    """
    points = []
    for blob in reversed(list(history)):        # history is newest first
        if not in_view(blob, view):
            continue
        before, after = ratings_of(blob, view)
        if uid not in after:
            continue
        when = blob.get("applied_at", "")
        if not points and uid in before:
            points.append((when, int(before[uid])))
        points.append((when, int(after[uid])))
    return points


# --- head to head -----------------------------------------------------------

def head_to_head(history, a, b, view=OVERALL, last=5):
    """How two players have actually gone against each other.

    Only counts matches with one of them on each side — a doubles match they
    played *together* says nothing about which is better, so it is left out.
    Returns None when they have never met, so a page can hide the section
    rather than print two zeroes.
    """
    met = []
    for blob in history:
        if not in_view(blob, view):
            continue
        side_a, side_b = blob.get("side_a", ()), blob.get("side_b", ())
        if (a in side_a and b in side_b) or (b in side_a and a in side_b):
            met.append(blob)
    if not met:
        return None

    wins = {a: 0, b: 0}
    draws = 0
    games = {a: 0, b: 0}
    for blob in met:
        result = result_of(blob, a)
        if result == "W":
            wins[a] += 1
        elif result == "L":
            wins[b] += 1
        else:
            draws += 1
        for uid in (a, b):
            side = "a" if uid in blob.get("side_a", ()) else "b"
            games[uid] += blob[f"games_{side}"]
    return {"matches": len(met), "wins": wins, "draws": draws, "games": games,
            "recent": met[:last]}


def opponents(history, uid, view=OVERALL):
    """Everyone this player has faced, most-played first — [(uid, matches), …].

    Partners in doubles don't count as opponents, which is what makes this
    usable as the list behind a head-to-head picker.
    """
    counts = {}
    for blob in history:
        if not in_view(blob, view):
            continue
        side_a, side_b = list(blob.get("side_a", ())), list(blob.get("side_b", ()))
        if uid in side_a:
            others = side_b
        elif uid in side_b:
            others = side_a
        else:
            continue
        for other in others:
            counts[other] = counts.get(other, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


# --- grouping ---------------------------------------------------------------

def _day_of(blob):
    from datetime import datetime
    try:
        return datetime.fromisoformat(blob.get("applied_at", "")).date()
    except (TypeError, ValueError):
        return None


def group_by_day(history, now):
    """[(label, date, [matches]), …] newest day first.

    Matches too old to carry a timestamp are gathered at the end under one
    honest heading rather than being dated by guesswork.
    """
    from datetime import timedelta
    today = now.date()
    groups, undated = [], []
    index = {}
    for blob in history:
        day = _day_of(blob)
        if day is None:
            undated.append(blob)
            continue
        if day not in index:
            index[day] = []
            groups.append(day)
        index[day].append(blob)

    out = []
    for day in sorted(groups, reverse=True):
        if day == today:
            label = "Today"
        elif day == today - timedelta(days=1):
            label = "Yesterday"
        elif today - day < timedelta(days=7):
            label = day.strftime("%A")
        else:
            label = f"{day.day} {day.strftime('%b')}"
        out.append((label, day, index[day]))
    if undated:
        out.append(("Earlier", None, undated))
    return out


# --- turning up --------------------------------------------------------------

# A year is what a contributions graph means, but the ladder only keeps a
# player's last PLAYER_HISTORY_LIMIT matches, so the grid is drawn from the
# oldest session we can still see rather than from a fixed year ago. Every cell
# on it is then a day we actually know about: an empty square means nobody
# played, never "we threw that away".
HEAT_WEEKS = 52
HEAT_LEVELS = 4


def contributions(history, uid, now, view=OVERALL, weeks=HEAT_WEEKS):
    """The contributions grid: (columns, counts, span).

    `columns` is a list of weeks, each a list of seven (date, count) cells
    running Monday to Sunday, oldest week first — the shape a heatmap is drawn
    in. Cells outside the span are None, so the first and last weeks can be
    partial without the grid lying about them.

    `counts` is {date: matches}. `span` is (first day drawn, last day drawn).
    """
    from datetime import timedelta
    mine = [blob for blob in history
            if uid in tuple(blob.get("side_a", ())) + tuple(blob.get("side_b", ()))
            and in_view(blob, view)]
    days = [day for day in (_day_of(blob) for blob in mine) if day]
    if not days:
        return [], {}, None

    today = now.date()
    earliest = today - timedelta(weeks=weeks) + timedelta(days=1)
    start = max(min(days), earliest)
    counts = {}
    for day in days:
        if start <= day <= today:
            counts[day] = counts.get(day, 0) + 1

    # Whole weeks, Monday first, so the rows line up as weekdays the way every
    # graph of this shape does.
    first_column = start - timedelta(days=start.weekday())
    columns, cursor = [], first_column
    while cursor <= today:
        week = []
        for offset in range(7):
            day = cursor + timedelta(days=offset)
            week.append((day, counts.get(day, 0)) if start <= day <= today else None)
        columns.append(week)
        cursor += timedelta(days=7)
    return columns, counts, (start, today)


def heat_level(count, busiest):
    """Which of the HEAT_LEVELS shades a day's count earns, 0 for none.

    Scaled to the busiest day rather than to a fixed count, because a ladder
    where four sessions is a big day and one where four is a Tuesday should both
    produce a graph with some dark squares in it.
    """
    import math
    if not count:
        return 0
    # A quiet ladder counts literally: one session is one shade, and the darkest
    # is only reached by someone who really did play four times in a day.
    if busiest <= HEAT_LEVELS:
        return min(count, HEAT_LEVELS)
    return max(1, min(HEAT_LEVELS,
                      math.ceil(count / (busiest / float(HEAT_LEVELS)))))


# --- the week's one match ---------------------------------------------------

def match_of_week(history, week):
    """One match worth pointing at, and the rule that picked it.

    Two rules, in order, so the card can always name the reason it is there:

      "Went the distance" — the week's closest finish, decided by a single
      game after at least three, with the highest combined rating breaking a
      tie: the best players in the tightest match.

      "Biggest swing" — otherwise, the match that moved a rating furthest.

    Returns (blob, reason) or None. A week with no matches produces nothing,
    and nothing is what the page then shows.
    """
    played = [b for b in history if b.get("week") == week]
    if not played:
        return None

    def combined(blob):
        before = blob.get("before") or {}
        return sum(before.values())

    def swing(blob):
        return max((abs(d) for d in (blob.get("deltas") or {}).values()), default=0)

    deciders = [b for b in played
                if abs(b["games_a"] - b["games_b"]) == 1
                and b["games_a"] + b["games_b"] >= 3]
    if deciders:
        return max(deciders, key=lambda b: (combined(b), swing(b))), "Went the distance"
    best = max(played, key=swing)
    return (best, "Biggest swing") if swing(best) else None


# --- the numbers ------------------------------------------------------------

def _scoreline(game):
    a, b = int(game[0]), int(game[1])
    return f"{max(a, b)}&#8211;{min(a, b)}"


def numbers(players, history, names=None):
    """The stats page, as (label, value, detail, source) rows.

    `source` is "players" for a figure read off the player records and
    "matches" for one counted out of the matches themselves — different claims
    over different windows, so the page groups them and says which is which.

    Every entry is computed from what is stored, and any that cannot be is left
    out entirely: the page renders what comes back and nothing else, which is
    how a missing metric stays missing instead of becoming a zero.
    """
    out = []
    if not players:
        return out

    def who(uid):
        return (names or {}).get(uid) or uid

    def add(label, value, detail, source, uid=""):
        """`uid` is whose figure it is, where it is one person's — the stats
        page turns it into a link, so a name there goes to the same place a
        name anywhere else does."""
        out.append((label, value, detail, source, uid))

    rated = [(uid, p) for uid, p in players.items() if games_played(p)]
    if rated:
        top = max(rated, key=lambda i: i[1]["rating"])
        add("Highest rating", top[1]["rating"], who(top[0]), "players", top[0])

        peak = max(rated, key=lambda i: i[1]["peak"])
        if peak[1]["peak"] > peak[1]["rating"]:
            add("Highest ever", peak[1]["peak"], f"{who(peak[0])}, since fallen",
                "players", peak[0])

        busiest = max(rated, key=lambda i: (i[1]["matches"], games_played(i[1])))
        add("Most matches", busiest[1]["matches"], who(busiest[0]), "players",
            busiest[0])

        most_games = max(rated, key=lambda i: games_played(i[1]))
        add("Most games", games_played(most_games[1]), who(most_games[0]),
            "players", most_games[0])

        winners = [(uid, p) for uid, p in rated if p["wins"]]
        if winners:
            most_wins = max(winners, key=lambda i: i[1]["wins"])
            add("Most wins", most_wins[1]["wins"], who(most_wins[0]), "players",
                most_wins[0])
            # A win rate off two games is noise, so it is gated on the same
            # number of games the overall board asks for before it ranks anyone.
            eligible = [(uid, p) for uid, p in rated if games_played(p) >= 6]
            if eligible:
                best = max(eligible, key=lambda i: i[1]["games_won"] / games_played(i[1]))
                rate = round(100 * best[1]["games_won"] / games_played(best[1]))
                add("Best win rate", f"{rate}%",
                    f"{who(best[0])} · {best[1]['games_won']} of "
                    f"{games_played(best[1])} games", "players", best[0])

        streaks = [(uid, p) for uid, p in rated if p["best_streak"] >= 2]
        if streaks:
            longest = max(streaks, key=lambda i: i[1]["best_streak"])
            add("Longest win streak", longest[1]["best_streak"], who(longest[0]),
                "players", longest[0])

        cold = [(uid, p) for uid, p in rated if p["streak"] <= -2]
        if cold:
            worst = min(cold, key=lambda i: i[1]["streak"])
            add("Coldest streak", abs(worst[1]["streak"]),
                f"{who(worst[0])} · still running", "players", worst[0])

    if history:
        gains = [(uid, delta, blob) for blob in history
                 for uid, delta in (blob.get("deltas") or {}).items() if delta > 0]
        if gains:
            uid, delta, blob = max(gains, key=lambda item: item[1])
            add("Biggest single gain", f"+{delta}",
                f"{who(uid)} · {_sides(blob, names)}", "matches", uid)

        closest = _closest(history)
        if closest:
            blob, margin = closest
            add("Closest match", f"{blob['games_a']}&#8211;{blob['games_b']}",
                f"{_sides(blob, names)} · {margin} "
                f"point{'s' if margin != 1 else ''} between them", "matches")

        common = _common_scoreline(history)
        if common:
            score, count = common
            add("Most common game", score, f"played {count} times", "matches")

        longest = max(history, key=lambda b: len(b.get("games", ())))
        if len(longest.get("games", ())) >= 4:
            add("Longest session", len(longest["games"]),
                f"games · {_sides(longest, names)}", "matches")
    return out


def _sides(blob, names=None):
    def side(uids):
        return " & ".join((names or {}).get(u) or u for u in uids)
    return f"{side(blob.get('side_a', ()))} v {side(blob.get('side_b', ()))}"


def _closest(history):
    """The match settled by the fewest points across the whole session. Only
    matches that were actually decided count — a draw isn't a close finish,
    it's no finish."""
    best = None
    for blob in history:
        if blob["games_a"] == blob["games_b"]:
            continue
        margin = abs(int(blob.get("points_a", 0)) - int(blob.get("points_b", 0)))
        if not margin:
            continue
        if best is None or margin < best[1]:
            best = (blob, margin)
    return best


def _common_scoreline(history):
    counts = {}
    for blob in history:
        for game in blob.get("games", ()):
            try:
                key = _scoreline(game)
            except (TypeError, ValueError, IndexError):
                continue
            counts[key] = counts.get(key, 0) + 1
    if not counts:
        return None
    score = max(counts.items(), key=lambda item: (item[1], item[0]))
    return score if score[1] > 1 else None


def _rivalry(history):
    """The pair who have met most often, one on each side."""
    counts = {}
    for blob in history:
        for one in blob.get("side_a", ()):
            for two in blob.get("side_b", ()):
                pair = tuple(sorted((one, two)))
                counts[pair] = counts.get(pair, 0) + 1
    if not counts:
        return None
    pair = max(counts.items(), key=lambda item: (item[1], item[0]))
    return pair if pair[1] > 1 else None


def games_played(player):
    """Games, not matches — the same measure elo.py uses."""
    return int(player.get("games_won", 0)) + int(player.get("games_lost", 0))
