"""The pages beyond the ladder: matches, players, profile, stats, log, errors.

Every one of them is a pure function from data to a document, so none of this
needs a database — which is also the property that lets a page be checked for
what it *doesn't* say when the data isn't there.
"""
import re

import pytest

import awards
from web.pages import compare, errors, log, matches, players, profile, stats

A, B, C = "U0A", "U0B", "U0C"
NAMES = {A: "Ann", B: "Bob", C: "Cal"}
WEEK = "tt:wk:2026-W38"


def player(**kw):
    base = {"rating": 1000, "wins": 0, "losses": 0, "draws": 0, "games_won": 0,
            "games_lost": 0, "peak": 1000, "streak": 0, "best_streak": 0,
            "matches": 0, "points_won": 0, "points_lost": 0}
    base.update(kw)
    return base


def match(side_a=(A,), side_b=(B,), games_a=2, games_b=1, when="2026-09-17T10:00:00+05:30",
          doubles=False, **kw):
    blob = {"side_a": list(side_a), "side_b": list(side_b), "games_a": games_a,
            "games_b": games_b, "doubles": doubles, "week": WEEK,
            "applied_at": when, "games": [[11, 7], [9, 11], [11, 5]],
            "points_a": 31, "points_b": 23,
            "deltas": {A: 7, B: -7}, "before": {A: 1000, B: 1000},
            "after": {A: 1007, B: 993},
            "split_rated": {"deltas": {A: 9, B: -9}, "before": {A: 1000, B: 1000},
                            "after": {A: 1009, B: 991}}}
    blob.update(kw)
    return blob


def now():
    from datetime import datetime, timedelta, timezone
    return datetime(2026, 9, 17, 20, tzinfo=timezone(timedelta(hours=5, minutes=30)))


# --- every page, whatever the data -----------------------------------------

PAGES = {
    "matches": lambda: matches.render([], {}, {}),
    "players": lambda: players.render({}, {}),
    "profile": lambda: profile.render(A, player(), {A: player()}, NAMES),
    "compare": lambda: compare.render([A, B], {A: player(), B: player()}, NAMES),
    "stats": lambda: stats.render({}, {}),
    "log": lambda: log.render(),
    "not_found": lambda: errors.not_found(),
    "no_database": lambda: errors.no_database(),
    "broken": lambda: errors.broken(),
}


@pytest.mark.parametrize("name", sorted(PAGES))
def test_every_page_is_a_whole_document(name):
    html = PAGES[name]()
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert 'name="viewport"' in html


@pytest.mark.parametrize("name", sorted(PAGES))
def test_no_page_asks_the_network_for_anything(name):
    """The strict-network rule the ladder is built on applies to all of them."""
    html = PAGES[name]()
    assert "http://" not in html and "https://" not in html
    assert "<link" not in html and "@import" not in html


@pytest.mark.parametrize("name", sorted(PAGES))
def test_every_page_carries_the_brand_and_a_way_back(name):
    html = PAGES[name]()
    assert "Rally" in html and "Table Tennis League" in html
    assert 'href="/ladder"' in html


# --- matches ---------------------------------------------------------------

def test_matches_are_grouped_under_the_day_they_were_played():
    html = matches.render([match(), match(when="2026-09-16T10:00:00+05:30")],
                          {A: player()}, NAMES, now=now())
    assert "Today" in html and "Yesterday" in html
    assert html.count('class="match"') == 2


def test_an_empty_match_list_offers_a_way_out_rather_than_a_blank():
    html = matches.render([], {A: player()}, NAMES, params={"day": "today"}, now=now())
    assert "Nothing here" in html and "Clear filters" in html
    assert "no data" not in html.lower()


def test_the_filters_say_what_is_being_filtered():
    html = matches.render([match()], {A: player()}, NAMES,
                          params={"player": A, "format": "singles", "label": "today"},
                          now=now())
    assert "Ann" in html and "Singles" in html and "today" in html


def test_a_filtered_list_reports_the_format_its_own_rating():
    """Filtered to singles, the cards show what the match did to the singles
    rating — the same number the singles board shows."""
    singles = matches.render([match()], {A: player()}, NAMES,
                             params={"format": "singles"}, now=now())
    everything = matches.render([match()], {A: player()}, NAMES, now=now())
    assert "+9" in singles and "+7" not in singles
    assert "+7" in everything


def test_a_doubles_match_reports_no_singles_change():
    """It never touched the singles rating, so under a singles filter the card
    shows no figure at all rather than the doubles one."""
    pair = match(side_a=[A, C], side_b=[B, "U0D"], doubles=True)
    html = matches.render([pair], {A: player()}, NAMES,
                          params={"format": "singles"}, now=now())
    assert "+9" not in html and "+7" not in html


# --- players ---------------------------------------------------------------

def test_the_players_page_separates_the_ranked_from_the_placing():
    people = {A: player(rating=1050, games_won=6, games_lost=2),
              B: player(rating=990, games_won=1, games_lost=1)}
    html = players.render(people, NAMES, placement_games=4)
    assert "Ranked" in html and "Still placing" in html
    assert 'href="/player/U0A"' in html and 'href="/player/U0B"' in html


def test_a_placing_player_has_no_rank_to_show():
    people = {B: player(games_won=1, games_lost=1)}
    html = players.render(people, NAMES, placement_games=4)
    assert "#01" not in html and "Placing" in html


def test_an_empty_league_says_how_to_start_it():
    html = players.render({}, {})
    assert "Nobody here yet" in html and "How to log a match" in html


# --- profile ---------------------------------------------------------------

def test_a_profile_leads_with_the_rating_and_the_standing():
    html = profile.render(A, player(rating=1064, wins=4, games_won=10, games_lost=2),
                          {A: player()}, NAMES, rank=1)
    assert "1064" in html and "#1 on the singles ladder" in html
    assert "Ann" in html


def test_a_profile_without_a_rank_says_what_is_missing():
    html = profile.render(B, player(games_won=1, games_lost=1), {B: player()},
                          NAMES, placement_games=4)
    assert "games from the singles board" in html


def test_a_rating_line_needs_two_points_before_it_is_drawn():
    """One match is not a trend, and the page says so instead of drawing one."""
    html = profile.render(A, player(), {A: player()}, NAMES, history=[])
    assert "Not enough matches yet" in html and "<svg class=" not in html


def test_a_rating_line_appears_once_there_is_a_run():
    html = profile.render(A, player(), {A: player()}, NAMES,
                          history=[match(), match(when="2026-09-16T10:00:00+05:30")])
    assert 'class="chart-line"' in html


def body(html):
    """The document without its stylesheet — the sheet has section comments in
    it, and a page's *content* is what these assertions are about."""
    return html[html.index("<body>"):]


def test_head_to_head_is_absent_until_somebody_has_been_played():
    html = profile.render(A, player(), {A: player()}, NAMES, history=[])
    assert "Head to head" not in body(html)


def test_head_to_head_names_the_opponent_that_was_asked_for():
    history = [match(side_b=[B]), match(side_b=[C]), match(side_b=[C])]
    html = profile.render(A, player(), {A: player()}, NAMES, history=history, versus=B)
    picked = re.search(r'<a class="rival on"[^>]*>(.*?)</a>', html, re.S).group(1)
    assert "Bob" in picked


def test_a_profile_shows_the_format_it_is_on():
    """The singles tab lists singles matches; the doubles one lists doubles."""
    singles, doubles = match(), match(side_a=[A, C], side_b=[B, "U0D"], doubles=True)
    on_singles = profile.render(A, player(), {A: player()}, NAMES,
                                history=[singles, doubles], view="")
    on_doubles = profile.render(A, player(), {A: player()}, NAMES,
                                history=[singles, doubles], view="doubles")
    assert on_singles.count('class="match"') == 1
    assert on_doubles.count('class="match"') == 1
    assert ">Doubles<" in on_doubles[on_doubles.index("Matches"):]


# --- stats -----------------------------------------------------------------

def test_the_numbers_are_grouped_by_where_they_came_from():
    people = {A: player(rating=1050, wins=3, games_won=8, games_lost=2, matches=4)}
    html = stats.render(people, NAMES, history=[match()])
    assert "Leaders" in html and "From the matches" in html


def test_a_league_with_nothing_to_count_says_so():
    html = stats.render({}, {})
    assert "Nothing to count yet" in html


def test_the_window_is_stated_rather_than_implied():
    """"Most" over the last 120 matches is a different claim from "most ever"."""
    people = {A: player(rating=1050, wins=3, games_won=8, games_lost=2, matches=4)}
    html = stats.render(people, NAMES, history=[match()], window=120)
    assert "Counted over all 1 matches on record." in html


# --- log --------------------------------------------------------------------

def test_the_log_page_is_honest_about_what_it_is():
    html = log.render()
    assert "read-only by design" in html
    assert "<form" not in html          # it never pretends to accept a result
    assert "/tt log" in html


def test_the_log_page_names_the_channel_when_it_knows_it():
    assert "#table-tennis" in log.render(channel_hint="table-tennis")


# --- errors -----------------------------------------------------------------

def test_a_missing_player_is_a_named_problem_not_a_blank_page():
    html = errors.not_found("player")
    # The apostrophe arrives escaped, which is the point of escaping it.
    assert "Nothing here" in html and "player isn&#x27;t on the ladder" in html
    assert "Back to the ladder" in html


def test_a_missing_database_says_which_variables_are_missing():
    assert "KV_REST_API_URL" in errors.no_database()


def test_a_broken_page_keeps_its_detail_for_when_it_is_asked_for():
    assert "ValueError: nope" not in errors.broken()
    assert "ValueError: nope" in errors.broken("ValueError: nope")


# --- search -----------------------------------------------------------------

def test_the_players_grid_can_be_searched_from_the_server():
    """The box works without script, so a shared link filters too."""
    people = {A: player(games_won=4, games_lost=1), B: player(games_won=4, games_lost=1)}
    html = players.render(people, NAMES, query="ann", placement_games=4)
    # Scoped to the grid: the compare pickers list everyone whatever is searched.
    grid = html[html.index('class="pc-grid"'):]
    assert "Ann" in grid and "Bob" not in grid


def test_a_search_that_finds_nobody_says_which_name_failed():
    people = {A: player(games_won=4, games_lost=1)}
    html = players.render(people, NAMES, query="zzz")
    assert "Nobody by that name" in html and "zzz" in html
    assert "Show everyone" in html


def test_a_hostile_search_term_is_escaped_in_what_comes_back():
    html = players.render({}, NAMES, query='<script>alert(1)</script>')
    assert "<script>alert(1)</script>" not in body(html)
    assert "&lt;script&gt;" in html


def test_the_search_box_filters_in_the_browser_too():
    """With script it narrows what is already rendered; the rows carry their
    own searchable text so a keystroke fetches nothing."""
    html = players.render({A: player(games_won=4, games_lost=1)}, NAMES)
    field = re.search(r'<input type="search"[^>]*>', html).group(0)
    assert 'data-filter=".pc-grid"' in field and 'data-filter-item=".pc"' in field
    assert 'data-search="ann"' in html


def test_matches_carry_every_name_in_them_for_the_search():
    html = matches.render([match()], {A: player()}, NAMES, now=now())
    card = re.search(r'<article class="match"([^>]*)>', html).group(1)
    assert "ann" in card and "bob" in card and "singles" in card


# --- compare ----------------------------------------------------------------

def test_compare_asks_for_two_players_before_it_says_anything():
    html = compare.render([], {}, NAMES)
    assert "Pick two players" in html and "compare-bar" in html
    assert "Side by side" not in body(html)


def test_compare_never_shows_one_player_against_nobody():
    people = {A: player()}
    assert "Side by side" not in body(compare.render([A], people, NAMES))


def test_compare_stops_at_the_ceiling():
    """Four columns is what stays readable; a fifth is dropped rather than
    squeezed in."""
    people = {uid: player() for uid in (A, B, C, "U0D", "U0E")}
    names = dict(NAMES, **{"U0D": "Dee", "U0E": "Eve"})
    html = compare.render([A, B, C, "U0D", "U0E"], people, names)
    heads = re.search(r'<thead>(.*?)</thead>', html, re.S).group(1)
    assert heads.count("<th") == compare.MAX and "Eve" not in heads


def test_compare_marks_whichever_column_leads_each_row():
    people = {A: player(rating=1100, matches=5, games_won=9, games_lost=3, peak=1100),
              B: player(rating=1000, matches=9, games_won=6, games_lost=9)}
    html = compare.render([A, B], people, NAMES)
    rows = re.findall(r'<tr>(.*?)</tr>', html, re.S)
    rating = next(row for row in rows if ">Rating<" in row)
    # The higher rating is the marked cell, and it is the left column here.
    assert rating.index('class="cmp-cell leads"') < rating.index("1000")
    played = next(row for row in rows if ">Matches<" in row)
    assert played.index("cmp-cell leads") > played.index(">5<")   # B played more


def test_a_row_everyone_ties_marks_nobody():
    people = {A: player(rating=1000), B: player(rating=1000)}
    html = compare.render([A, B], people, NAMES)
    rating = next(row for row in re.findall(r'<tr>(.*?)</tr>', html, re.S)
                  if ">Rating<" in row)
    assert "leads" not in rating


def test_three_players_get_a_grid_of_who_beat_whom():
    people = {uid: player() for uid in (A, B, C)}
    history = [match(side_a=[A], side_b=[B]), match(side_a=[C], side_b=[A])]
    html = compare.render([A, B, C], people, NAMES, history=history)
    assert "cmp-grid" in html and "Wins each way" in html
    # A pair who never met is a dash, not a nil-nil.
    assert "never met" in html


def test_compare_says_so_when_two_players_have_never_met():
    people = {A: player(), B: player()}
    html = compare.render([A, B], people, NAMES, history=[match(side_a=[A], side_b=[C])])
    assert "They haven&#x27;t played" in html


def test_compare_draws_both_rating_lines_on_one_scale():
    people = {A: player(), B: player()}
    history = [match(), match(when="2026-09-16T10:00:00+05:30")]
    html = compare.render([A, B], people, NAMES, history=history)
    assert html.count('class="chart-line l0"') == 1
    assert html.count('class="chart-line l1"') == 1
    assert "legend-key" in html


def test_a_player_with_one_match_is_not_stretched_to_fill_the_chart():
    """Both lines end at now; the shorter one starts further along rather than
    being spread over a run it did not play."""
    from web import components as c
    pair = c.rating_chart_pair([("Long", [("", 1000), ("", 1010), ("", 1020)]),
                                ("Short", [("", 990), ("", 1000)])])
    short = re.search(r'class="chart-line l1" points="([^"]*)"', pair).group(1)
    assert short.split()[0].split(",")[0] != "18.0"     # not from the left edge


# --- the spins board --------------------------------------------------------

def test_the_spins_board_says_where_the_money_came_from():
    from web.pages import ladder
    html = ladder.render({}, NAMES, [], {}, {}, 4, board="spins",
                         spins=[(A, 7000, 2000), (B, 3000, -2000)], start_spins=5000)
    assert "7,000" in html and "opened with 5,000" in html
    assert "a spin won is a spin somebody else lost" in html
    assert "2 of 2 have moved off the start" in html


# --- the compare mode on the players page ----------------------------------

def test_the_players_grid_is_a_grid_until_you_ask_to_compare():
    people = {A: player(games_won=4, games_lost=1)}
    plain = players.render(people, NAMES, placement_games=4)
    picking = players.render(people, NAMES, placement_games=4, comparing=True)
    assert 'class="pc"' in body(plain) and "compare-bar" not in body(plain)
    assert 'class="pc pc-pick"' in picking and "compare-bar" in body(picking)
    assert "compare-dialog" in picking      # somewhere for the result to appear


def test_the_toggle_says_which_way_it_will_go():
    people = {A: player(games_won=4, games_lost=1)}
    assert "Compare players" in players.render(people, NAMES)
    assert "Done comparing" in players.render(people, NAMES, comparing=True)


def test_a_picked_player_is_marked_on_their_card():
    people = {A: player(games_won=4, games_lost=1), B: player(games_won=4, games_lost=1)}
    html = players.render(people, NAMES, placement_games=4, comparing=True,
                          compare=[A])
    cards = re.findall(r'<button type="button" class="pc pc-pick([^"]*)"[^>]*'
                       r'data-uid="([^"]*)"', html)
    assert (" is-picked", A) in cards and ("", B) in cards


def test_the_tray_offers_one_more_slot_than_is_filled():
    """Two pickers to start, and the + reveals the rest — up to the ceiling."""
    from web import components
    tray = components.compare_tray(NAMES, [A])
    live = re.findall(r'<select class="cmp-pick"[^>]*>', tray)
    assert len(live) == components.COMPARE_MAX
    assert sum(1 for s in live if "hidden" not in s) == 2


def test_a_full_tray_hides_no_slots_and_offers_no_more():
    from web import components
    full = [A, B, C, "U0D"][:components.COMPARE_MAX]
    tray = components.compare_tray(dict(NAMES, **{"U0D": "Dee"}), full)
    live = re.findall(r'<select class="cmp-pick"[^>]*>', tray)
    assert len(live) == components.COMPARE_MAX
    assert not [s for s in live if "hidden" in s]


def test_the_popup_renders_the_same_comparison_without_the_page():
    people = {A: player(), B: player()}
    bare = compare.render([A, B], people, NAMES, bare=True)
    assert "<!doctype html>" not in bare and "<nav" not in bare
    assert "Side by side" in bare


# --- titles ----------------------------------------------------------------

TITLES_HELD = {"hot": A, "moneybags": B}
WORN = {A: ["hot"], B: ["moneybags"]}


def test_the_titles_page_lists_every_title_held_or_not():
    from web.pages import titles as page_titles
    html = page_titles.render(TITLES_HELD, {A: player(), B: player()}, NAMES)
    for title in awards.TITLES:
        assert title.name in html and title.blurb in html
    assert "Going spare" in html          # the three nobody holds
    assert f'href="/player/{A}"' in html


def test_a_title_follows_the_player_onto_every_page():
    """The point of the feature: a chip is not a section on one page, it is
    part of how a person is rendered."""
    from web.pages import compare as page_compare
    from web.pages import ladder as page_ladder
    from web.pages import matches as page_matches
    from web.pages import players as page_players
    from web.pages import profile as page_profile

    people = {A: player(rating=1100, wins=4, games_won=12, games_lost=4, matches=4),
              B: player(rating=900, losses=4, games_won=4, games_lost=12, matches=4)}
    history = [match()]
    pages = {
        "ladder": page_ladder.render(people, NAMES, history, {}, {}, 1,
                                     history=history, titles=WORN),
        "players": page_players.render(people, NAMES, history, placement_games=1,
                                       titles=WORN),
        "matches": page_matches.render(history, people, NAMES, now=now(),
                                       titles=WORN),
        "profile": page_profile.render(A, people[A], people, NAMES, history,
                                       placement_games=1, titles=WORN),
        "compare": page_compare.render([A, B], people, NAMES, history,
                                       titles=WORN),
    }
    for name, html in pages.items():
        assert "On Fire" in html, f"{name} is not showing the title"


def test_a_page_given_no_titles_is_still_the_page():
    """Every chip is optional everywhere. The titles table is a cache read that
    is allowed to fail, so no page may depend on it."""
    from web.pages import ladder as page_ladder
    people = {A: player(rating=1100, matches=4, games_won=12, games_lost=4)}
    html = page_ladder.render(people, NAMES, [], {}, {}, 1)
    assert "<h1" in html and "title-chip" not in html.split("</style>")[1]
# --- turning up, and getting there -----------------------------------------

def dated(back, uid=A, other=B):
    from datetime import timedelta
    blob = match(side_a=[uid], side_b=[other])
    blob["applied_at"] = (now() - timedelta(days=back)).isoformat()
    return blob


def test_the_profile_draws_a_square_for_every_day_it_knows_about():
    history = [dated(0), dated(0), dated(4), dated(11)]
    html = profile.render(A, player(matches=4, games_won=8, games_lost=4),
                          {A: player(), B: player()}, NAMES, history,
                          placement_games=1, now=now())
    assert "Turning up" in body(html)
    # 12 days inclusive, and the two on one day are one darker square.
    assert html.count('class="heat heat-') >= 12
    assert "2 matches on" in html          # the day they played twice
    assert "as far back as the ladder keeps" in html


def test_the_graph_says_every_count_in_words_as_well_as_a_shade():
    """Colour is the summary here, never the information."""
    html = profile.render(A, player(matches=2, games_won=4), {A: player()},
                          NAMES, [dated(0), dated(4)], placement_games=1, now=now())
    # The played days and the quiet ones in between, each said in words.
    assert "No matches on" in body(html) and "1 match on" in body(html)
    assert 'role="img"' in body(html) and "aria-label=" in body(html)


def test_a_player_with_no_history_gets_no_graph():
    html = profile.render(A, player(), {A: player()}, NAMES, [],
                          placement_games=1, now=now())
    assert "Turning up" not in body(html)


def test_the_graph_is_left_out_when_the_page_is_not_told_the_date():
    """`now` is the caller's to supply — the page never reaches for a clock of
    its own, which is what keeps it renderable in a test."""
    html = profile.render(A, player(matches=1), {A: player()}, NAMES, [dated(0)],
                          placement_games=1)
    assert "Turning up" not in body(html)


def test_a_name_goes_to_the_person_it_names_on_every_page():
    from web.pages import ladder as page_ladder
    from web.pages import matches as page_matches
    from web.pages import stats as page_stats

    people = {A: player(rating=1100, wins=4, games_won=12, games_lost=4, matches=4),
              B: player(rating=900, losses=4, games_won=4, games_lost=12, matches=4)}
    history = [match()]
    pages = {
        "ladder": page_ladder.render(people, NAMES, history, {}, {}, 1,
                                     history=history),
        "matches": page_matches.render(history, people, NAMES, now=now()),
        "stats": page_stats.render(people, NAMES, history),
        "profile": profile.render(A, people[A], people, NAMES, history,
                                  placement_games=1, now=now()),
    }
    for name, html in pages.items():
        assert f'href="/player/{A}"' in html, f"{name} leaves the name a dead end"


def test_a_link_keeps_the_reader_on_the_format_they_were_reading():
    from web.pages import ladder as page_ladder
    people = {A: player(rating=1100, matches=4, games_won=12, games_lost=4)}
    html = page_ladder.render(people, NAMES, [], {}, {}, 1, view="doubles")
    assert f'href="/player/{A}?view=doubles"' in html


# --- the wall of shame -----------------------------------------------------

# Built by hand rather than through shame.record(), so these stay what the rest
# of this file is: page rendering with no database anywhere near it.
def a_wall(*rows):
    import shame
    return [(uid, row, shame.score(row)) for uid, row in rows]


def test_the_shame_page_lists_the_worst_first():
    from web.pages import shame as page
    html = page.render(a_wall((B, {"rejected": 3}), (A, {"ducked": 1})),
                       {A: "Ada", B: "Bo"})
    assert html.index("Bo") < html.index("Ada")


def test_the_shame_page_says_it_is_a_joke():
    """Rejecting a wrong score is the ladder working. If the page ever stops
    saying so, the column goes rather than the wording."""
    from web.pages import shame as page
    html = page.render(a_wall((A, {"rejected": 1})), {A: "Ada"})
    assert "joke board" in html and "keeping the results honest" in html


def test_an_empty_wall_says_what_is_missing_rather_than_no_data():
    from web.pages import shame as page
    html = page.render([], {})
    assert "Nothing on it" in html and "no data" not in html.lower()


def test_every_name_on_the_wall_is_a_link_to_that_player():
    from web.pages import shame as page
    html = page.render(a_wall((A, {"ducked": 1})), {A: "Ada"})
    assert f'href="/player/{A}"' in html


def test_the_shame_page_explains_what_each_column_costs():
    """The weighted total is the thing people will query, so the key spells out
    what each kind is worth rather than leaving it to be reverse-engineered."""
    import shame
    from web.pages import shame as page
    html = page.render([], {})
    key = html[html.index("shame-key"):]
    for kind, name, blurb, _ in shame.KINDS:
        assert name in key, name
        assert blurb.split()[0] in key, blurb
        assert f'class="w num">{shame.WEIGHTS[kind]}<' in key, kind


def test_the_wall_is_in_the_nav():
    from web import layout
    assert ("Shame", "/shame", True) in layout.NAV_ITEMS


def test_the_shame_page_makes_no_external_request():
    from web.pages import shame as page
    html = page.render(a_wall((A, {"ducked": 1})), {A: "Ada"})
    assert "http://" not in html and "https://" not in html


def test_a_name_nobody_has_set_still_renders():
    from web.pages import shame as page
    html = page.render(a_wall((A, {"bailed": 1})), {})
    assert A[-4:] in html
