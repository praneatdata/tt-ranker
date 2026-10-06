"""Form, weekly movement and rank movement, derived from stored matches.

These are the only new *claims* the redesign makes about the data, so they are
tested the way the ratings are: against blobs shaped exactly like the ones
store.apply_match writes.
"""
import pytest

from web import derive

A, B, C, D = "U0A", "U0B", "U0C", "U0D"
WEEK = "tt:wk:2026-W38"


def match(side_a, side_b, games_a, games_b, doubles=False, week=WEEK,
          deltas=None, split=None):
    """A stored match blob, with the two delta sets a real one carries."""
    return {"side_a": list(side_a), "side_b": list(side_b),
            "games_a": games_a, "games_b": games_b, "doubles": doubles,
            "week": week, "deltas": deltas or {}, "split_rated": {"deltas": split or {}}}


# --- which matches belong to a tab -----------------------------------------

def test_a_tab_only_counts_its_own_format():
    singles, doubles = match([A], [B], 2, 0), match([A, B], [C, D], 2, 1, doubles=True)
    assert derive.in_view(singles, "") and not derive.in_view(doubles, "")
    assert derive.in_view(doubles, "doubles") and not derive.in_view(singles, "doubles")
    assert derive.in_view(singles, "overall") and derive.in_view(doubles, "overall")


def test_a_format_tab_reads_its_own_elo():
    """The overall figure and the format's own figure are different numbers for
    the same match, and reading the wrong one is the whole risk here."""
    blob = match([A], [B], 2, 1, deltas={A: 25}, split={A: 9})
    assert derive.deltas_of(blob, "") == {A: 9}
    assert derive.deltas_of(blob, "overall") == {A: 25}


def test_a_match_too_old_to_have_a_split_contributes_nothing():
    """Matches stored before doubles had its own ladder carry no split. They
    must not fall back to the overall figure, which measures another ladder."""
    old = {"side_a": [A], "side_b": [B], "games_a": 2, "games_b": 0, "week": WEEK,
           "doubles": False, "deltas": {A: 20, B: -20}}
    assert derive.deltas_of(old, "") == {}
    assert derive.deltas_of(old, "overall") == {A: 20, B: -20}


# --- form -------------------------------------------------------------------

def test_form_reads_oldest_first_and_stops_at_five():
    # History arrives newest-first; the strip reads left to right in time, so
    # the four losses (newest) end up on the right.
    history = [match([A], [B], 0, 2)] * 4 + [match([A], [B], 2, 0)] * 3
    assert derive.form(history, "")[A] == "WLLLL"
    assert derive.form(history, "")[B] == "LWWWW"


def test_a_draw_is_its_own_letter():
    assert derive.form([match([A], [B], 1, 1)], "") == {A: "D", B: "D"}


def test_form_ignores_the_other_format():
    history = [match([A, B], [C, D], 2, 0, doubles=True), match([A], [B], 0, 2)]
    assert derive.form(history, "")[A] == "L"
    assert derive.form(history, "doubles")[A] == "W"


def test_somebody_who_has_not_played_has_no_form():
    assert C not in derive.form([match([A], [B], 2, 0)], "")


# --- weekly movement --------------------------------------------------------

def test_only_this_week_counts():
    history = [match([A], [B], 2, 0, split={A: 9, B: -9}),
               match([A], [B], 2, 0, week="tt:wk:2026-W37", split={A: 99, B: -99})]
    delta, played = derive.weekly(history, "", WEEK)
    assert delta == {A: 9, B: -9} and played == {A: 1, B: 1}


def test_a_week_of_matches_adds_up():
    history = [match([A], [B], 2, 0, split={A: 9, B: -9}),
               match([A], [B], 0, 2, split={A: -4, B: 4})]
    delta, played = derive.weekly(history, "", WEEK)
    assert delta == {A: 5, B: -5} and played == {A: 2, B: 2}


def test_playing_and_breaking_even_is_not_the_same_as_not_playing():
    """The page says these differently, so the data has to tell them apart."""
    history = [match([A], [B], 2, 0, split={A: 9, B: -9}),
               match([A], [B], 0, 2, split={A: -9, B: 9})]
    delta, played = derive.weekly(history, "", WEEK)
    assert delta[A] == 0 and played[A] == 2
    assert C not in played


# --- rank movement ----------------------------------------------------------

def rank(pairs):
    return [(uid, {"rating": rating}) for uid, rating in pairs]


def test_climbing_past_somebody_is_a_place_gained():
    """A's 12 points took them from below B to above: one place each way."""
    moves = derive.rank_movement(rank([(A, 1000), (B, 995)]), {A: 12, B: -12})
    assert moves == {A: 1, B: -1}


def test_being_passed_while_you_sat_out_still_counts_as_falling():
    """The ladder is relative; you can lose a place without playing, and that
    is a real fall rather than a gap in the data."""
    moves = derive.rank_movement(rank([(A, 1010), (B, 1000)]), {A: 30, B: 0})
    assert moves == {A: 1, B: -1}


def test_a_week_nobody_played_moves_nobody():
    assert derive.rank_movement(rank([(A, 1000), (B, 900)]), {A: 0, B: 0}) == {}
    assert derive.rank_movement(rank([(A, 1000)]), {}) == {}


def test_holding_your_place_is_zero_not_missing():
    moves = derive.rank_movement(rank([(A, 1050), (B, 990)]), {A: 10, B: -10})
    assert moves == {A: 0, B: 0}


# --- the week's activity ----------------------------------------------------

@pytest.mark.parametrize("played,expected", [
    ({}, 0), ({A: 0}, 0), ({A: 2, B: 1}, 2), (None, 0)])
def test_active_counts_people_who_actually_played(played, expected):
    assert derive.active_this_week(played) == expected


# --- rating history ---------------------------------------------------------

def stamped(when, **kw):
    blob = match([A], [B], 2, 1, **kw)
    blob["applied_at"] = when
    return blob


def test_a_rating_line_starts_where_the_player_started():
    """The first point is the rating they came in on, not the one they left
    with, or a five-match run would draw as four."""
    history = [stamped("2026-09-17T10:00:00+05:30",
                       deltas={A: 10}, split={A: 10})]
    history[0]["before"] = {A: 1000}
    history[0]["after"] = {A: 1010}
    series = derive.rating_series(history, A, derive.OVERALL)
    assert [rating for _, rating in series] == [1000, 1010]


def test_a_rating_line_runs_oldest_to_newest():
    older = stamped("2026-09-16T10:00:00+05:30")
    older["before"], older["after"] = {A: 1000}, {A: 1010}
    newer = stamped("2026-09-17T10:00:00+05:30")
    newer["before"], newer["after"] = {A: 1010}, {A: 1004}
    series = derive.rating_series([newer, older], A, derive.OVERALL)
    assert [rating for _, rating in series] == [1000, 1010, 1004]


def test_a_rating_line_reads_the_format_it_was_asked_for():
    blob = stamped("2026-09-17T10:00:00+05:30")
    blob["before"], blob["after"] = {A: 1000}, {A: 1025}
    blob["split_rated"] = {"deltas": {A: 9}, "before": {A: 1000}, "after": {A: 1009}}
    assert derive.rating_series([blob], A, "")[-1][1] == 1009
    assert derive.rating_series([blob], A, derive.OVERALL)[-1][1] == 1025


def test_a_match_with_no_figure_for_this_format_is_skipped_not_flattened():
    blob = stamped("2026-09-17T10:00:00+05:30")
    blob["before"], blob["after"] = {A: 1000}, {A: 1025}
    blob.pop("split_rated")
    assert derive.rating_series([blob], A, "") == []


# --- head to head -----------------------------------------------------------

def test_two_players_who_have_never_met_have_no_record():
    assert derive.head_to_head([match([A], [B], 2, 0)], A, C) is None


def test_a_head_to_head_counts_matches_games_and_draws():
    history = [match([A], [B], 2, 0), match([B], [A], 2, 1), match([A], [B], 1, 1)]
    h2h = derive.head_to_head(history, A, B)
    assert h2h["matches"] == 3
    assert h2h["wins"] == {A: 1, B: 1} and h2h["draws"] == 1
    assert h2h["games"] == {A: 4, B: 3}


def test_partners_are_not_opponents():
    """A doubles match the two played *together* says nothing about which is
    better, so it has no place in their head-to-head."""
    together = match([A, B], [C, D], 2, 0, doubles=True)
    assert derive.head_to_head([together], A, B) is None
    assert derive.head_to_head([together], A, C)["matches"] == 1


def test_opponents_are_ranked_by_how_often_you_played_them():
    history = [match([A], [B], 2, 0), match([A], [B], 2, 0), match([A], [C], 2, 0)]
    assert derive.opponents(history, A) == [(B, 2), (C, 1)]


# --- grouping ---------------------------------------------------------------

def at(day, hour=12):
    from datetime import datetime, timedelta, timezone
    return datetime(2026, 9, day, hour, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_days_are_named_the_way_people_say_them():
    history = [stamped(at(17).isoformat()), stamped(at(16).isoformat()),
               stamped(at(14).isoformat()), stamped(at(1).isoformat())]
    labels = [label for label, _, _ in derive.group_by_day(history, at(17, 20))]
    assert labels[:2] == ["Today", "Yesterday"]
    assert labels[2] == "Monday"        # within the week, so named
    assert labels[3] == "1 Sep"         # older, so dated


def test_a_match_too_old_to_carry_a_date_is_not_given_one():
    history = [stamped(at(17).isoformat()), match([A], [B], 2, 0)]
    groups = derive.group_by_day(history, at(17, 20))
    assert groups[-1][0] == "Earlier" and groups[-1][1] is None


# --- match of the week ------------------------------------------------------

def test_a_week_with_no_matches_has_no_match_of_the_week():
    assert derive.match_of_week([], WEEK) is None
    assert derive.match_of_week([match([A], [B], 2, 0, week="other")], WEEK) is None


def test_a_decider_wins_over_a_bigger_swing():
    """Stated rule: the closest finish first, the biggest swing second."""
    decider = match([A], [B], 2, 1, deltas={A: 5, B: -5})
    decider["before"] = {A: 1100, B: 1100}
    blowout = match([C], [D], 3, 0, deltas={C: 40, D: -40})
    blowout["before"] = {C: 1000, D: 1000}
    blob, reason = derive.match_of_week([blowout, decider], WEEK)
    assert blob is decider and reason == "Went the distance"


def test_without_a_decider_the_biggest_swing_is_named_as_such():
    small = match([A], [B], 2, 0, deltas={A: 5, B: -5})
    big = match([C], [D], 2, 0, deltas={C: 40, D: -40})
    blob, reason = derive.match_of_week([small, big], WEEK)
    assert blob is big and reason == "Biggest swing"


def test_a_week_that_moved_nothing_is_not_dressed_up():
    assert derive.match_of_week([match([A], [B], 2, 0)], WEEK) is None


# --- the numbers ------------------------------------------------------------

def player(**kw):
    base = {"rating": 1000, "wins": 0, "losses": 0, "draws": 0, "games_won": 0,
            "games_lost": 0, "peak": 1000, "streak": 0, "best_streak": 0, "matches": 0}
    base.update(kw)
    return base


def test_nothing_is_counted_before_anything_has_happened():
    assert derive.numbers({}, []) == []
    assert derive.numbers({A: player()}, []) == []          # signed up, never played


def test_every_figure_says_where_it_came_from():
    players = {A: player(rating=1050, wins=3, games_won=8, games_lost=2, matches=4)}
    rows = derive.numbers(players, [match([A], [B], 2, 0, deltas={A: 12})])
    assert {row[3] for row in rows} == {"players", "matches"}
    # The fifth field is whose figure it is, so the stats page can link the name.
    assert ("Highest rating", 1050, A, "players", A) in rows


def test_a_win_rate_needs_enough_games_to_mean_anything():
    thin = {A: player(rating=1100, wins=1, games_won=2, games_lost=0, matches=1)}
    assert not [row for row in derive.numbers(thin, []) if row[0] == "Best win rate"]
    thick = {A: player(rating=1100, wins=3, games_won=8, games_lost=2, matches=3)}
    assert [row for row in derive.numbers(thick, []) if row[0] == "Best win rate"]


def test_the_closest_match_ignores_a_draw():
    """A draw isn't a close finish, it's no finish."""
    drawn = match([A], [B], 1, 1)
    drawn.update({"points_a": 22, "points_b": 22})
    decided = match([C], [D], 2, 1)
    decided.update({"points_a": 33, "points_b": 32})
    rows = dict((row[0], row) for row in derive.numbers({A: player(games_won=1)},
                                                        [drawn, decided]))
    assert "1 point between them" in rows["Closest match"][2]


def test_a_scoreline_seen_once_is_not_the_most_common():
    history = [match([A], [B], 1, 0)]
    history[0]["games"] = [[11, 7]]
    assert not [row for row in derive.numbers({A: player(games_won=1)}, history)
                if row[0] == "Most common game"]


# --- turning up ------------------------------------------------------------

from datetime import datetime, timedelta  # noqa: E402

import store  # noqa: E402

NOW = datetime(2026, 9, 18, 19, 30, tzinfo=store.IST)


def day(back, hour=12):
    from datetime import timedelta
    return (NOW - timedelta(days=back)).replace(hour=hour).isoformat()


def played(back, uid=A, other=B):
    blob = match([uid], [other], 2, 0)
    blob["applied_at"] = day(back)
    return blob


def test_the_grid_is_whole_weeks_of_real_days():
    columns, counts, span = derive.contributions(
        [played(0), played(0), played(9)], A, NOW)
    assert all(len(week) == 7 for week in columns)
    assert counts[NOW.date()] == 2
    start, end = span
    assert end == NOW.date()
    # Drawn from the oldest session, not from a year ago that we can't see.
    assert start == (NOW - timedelta(days=9)).date()


def test_days_outside_the_span_are_not_drawn_as_quiet_days():
    """An empty square has to mean nobody played. A day we have no record of is
    a different claim, so it is left out of the grid entirely."""
    columns, _, (start, end) = derive.contributions([played(3)], A, NOW)
    drawn = [cell for week in columns for cell in week if cell]
    assert all(start <= d <= end for d, _ in drawn)
    assert len(drawn) == (end - start).days + 1


def test_a_player_with_nothing_on_record_gets_no_grid():
    assert derive.contributions([], A, NOW) == ([], {}, None)
    assert derive.contributions([played(1, uid=C, other=D)], A, NOW)[0] == []


def test_the_grid_follows_the_format_tab():
    doubles = match([A, C], [B, D], 2, 0, doubles=True)
    doubles["applied_at"] = day(1)
    singles_only = derive.contributions([doubles, played(2)], A, NOW, view="")
    both = derive.contributions([doubles, played(2)], A, NOW, view=derive.OVERALL)
    assert sum(singles_only[1].values()) == 1
    assert sum(both[1].values()) == 2


def test_a_quiet_ladder_counts_its_days_literally():
    """Four sessions in a day is a lot here. Scaling to the busiest day would
    make one session look like a heavy day on a week where nobody played twice."""
    assert derive.heat_level(0, 3) == 0
    assert [derive.heat_level(n, 3) for n in (1, 2, 3)] == [1, 2, 3]


def test_a_busy_ladder_scales_to_its_busiest_day():
    assert derive.heat_level(1, 12) == 1
    assert derive.heat_level(12, 12) == derive.HEAT_LEVELS
    assert derive.heat_level(6, 12) < derive.HEAT_LEVELS
