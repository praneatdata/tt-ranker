"""RALLY's ladder — the live standings as one self-contained HTML document.

Linked from the Slack channel and opened mostly on phones, usually seconds
after a game, to answer one question: *did I move?* Everything here serves
that. The rating is the loudest figure on the page, the week's change sits
beside it, and anyone can find their own row without scrolling past a hero.

The design system lives in `web/` — tokens, stylesheet, icons, components and
the pure maths behind form and movement. This module is the ladder page only:
it decides what the page says and in what order, and hands the saying of it to
those pieces.

Nothing here reads the database or talks to Slack. Every input is passed in, so
the whole page renders inside a test with neither running.

No external requests: the page is built inside a Vercel function and a strict
corporate network is assumed, so the stylesheet is inline, the icons are inline
SVG and there are no web fonts — the type stack names Space Grotesk and Space
Mono first and falls through to the system grotesk where they aren't installed.
"""
import elo
from .. import components as c
from .. import derive, icons, layout
from ..components import display_name, e  # noqa: F401  (re-exported)

REFRESH_SECONDS = layout.REFRESH_SECONDS

# Singles first, and first means default: it is the honest ladder, since a
# doubles result is one number split between two people and can't say who did
# what. "" is singles; the others are named. The old ?view=singles links still
# resolve here — the route folds them onto "".
VIEWS = (("", "Singles"), ("doubles", "Doubles"), ("overall", "Overall"))

# What each tab is, said plainly at the top of it. The doubles note carries its
# caveat rather than leaving people to assume the number means what the singles
# one means.
NOTES = {
    "": ("Singles only, on its own rating — no doubles result has ever touched "
         "these numbers. A doubles result is one figure split between two "
         "people, so it can say how a pair did but not who did what."),
    "doubles": ("Doubles only, on its own rating. Read it as how the teams you "
                "play on do, not as your own level: a doubles result moves both "
                "partners by the same amount, so only a pair's combined rating "
                "is really measured — the split between the two is a guess the "
                "maths cannot check. Play with varied partners and it settles "
                "close to the truth; always partner the same person and the two "
                "of you drift together, high or low, with nothing to separate "
                "you. Singles is the tab that can."),
}

SPINS_SHOWN = 10
RECENT_SHOWN = 8       # the default glance
FILTERED_SHOWN = 50    # once someone has asked for a day or a player, show it

# Which leaderboard the standings show. Spins belong to no format — they are
# won and lost on fixtures, not on a ladder — so the board toggle and the
# format tabs are never both in play at once.
BOARDS = (("", "Ratings"), ("spins", "Spins"))


def render(players, names, recent, week_delta, week_played, placement_games,
           channel_hint="", updated="", view="", spins=None, start_spins=0,
           circulating=None, filters=None, history=(), match_count=None,
           log_href="", week="", board="", wallets=None, titles=None):
    """The whole page.

    `players` is whichever record set the view wants: singles views for the
    singles tab, doubles views for the doubles one. Ranking and rendering don't
    know the difference, which is the point of shaping a per-format record like
    an ordinary one.

    `titles` is awards.by_player()'s map of who is wearing what. Pass none
    and no chips appear — the page is still the page.

    `history` is recent match blobs, newest first — the one read the page makes
    beyond the players themselves. Form, per-format weekly movement and rank
    movement are all derived from it; pass none and those simply don't appear.
    """
    ranked = sorted(((u, p) for u, p in players.items()
                     if elo.games_played(p) >= placement_games),
                    key=lambda i: (-i[1]["rating"], -elo.games_played(i[1]), i[0]))
    placing = sorted(((u, p) for u, p in players.items()
                      if elo.games_played(p) < placement_games),
                     key=lambda i: (-elo.games_played(i[1]), i[0]))

    # The overall tab reads the weekly counters the bot keeps as matches are
    # confirmed. The format tabs have no such counter — a weekly figure that
    # counted every game would be a lie beside a one-format rating — so theirs
    # is summed from the matches themselves.
    if view == derive.OVERALL:
        delta, played = dict(week_delta or {}), dict(week_played or {})
    else:
        delta, played = derive.weekly(history, view, week)
    known = view == derive.OVERALL or bool(history)
    form = derive.form(history, view)
    moves = derive.rank_movement(ranked, delta) if known else {}

    # A table of identical opening balances tells nobody anything, so the
    # spins board — and the toggle that reaches it — appear only once somebody
    # has actually won or lost some.
    has_spins = any(net for _, _, net in (spins or []))
    on_spins = board == "spins" and has_spins
    body = "".join(part for part in (
        _hero(players, ranked, placing, names, placement_games, played,
              match_count, history, log_href),
        _controls(board, view, has_spins, on_spins),
        "" if on_spins else
        (f'<section class="wrap"><p class="note wide">{NOTES[view]}</p></section>'
         if NOTES.get(view) else ""),
        _spins_board(spins or [], names, start_spins, circulating, wallets)
        if on_spins else "",
        "" if on_spins else _featured(ranked, placing, names, placement_games,
                                      delta, played, form, log_href, known,
                                      titles, view),
        "" if on_spins else _board(ranked, names, delta, played, form, moves,
                                   known, titles, view),
        "" if on_spins else _placing(placing, names, placement_games, view),
        _of_the_week(history, week, names, view, titles),
        _recent(recent, names, players, filters or {}, view, titles),
    ) if part)

    return layout.document("RALLY — Table Tennis League", body, current="Ladder",
                           log_href=log_href, channel_hint=channel_hint,
                           updated=updated)


# --- hero ------------------------------------------------------------------

def _hero(players, ranked, placing, names, placement_games, played,
          match_count, history, log_href):
    """Brand, title and the four figures that say how alive the ladder is.

    `played` is the view's own count of who has played this week, so the figure
    beside a doubles ladder counts doubles — the alternative, a league-wide
    number under a one-format board, reads as that format's and isn't.
    """
    stats = [c.stat(len(players), "Players" if len(players) != 1 else "Player")]
    rated = match_count if match_count is not None else (len(history) or None)
    if rated is not None:
        stats.append(c.stat(rated, "Matches rated"))
    active = derive.active_this_week(played)
    if active:
        stats.append(c.stat(active, "Active this week"))
    if ranked:
        stats.append(c.stat(len(ranked), "Ranked"))

    note = _headline(players, ranked, placing, names, placement_games)
    return (
        '<section class="hero rise"><div class="wrap hero-in">'
        + icons.rally_arc()
        + '<p class="eyebrow live"><span class="live-dot"></span>'
          '<span id="freshness">Updated just now</span></p>'
          "<h1>The Ladder</h1>"
        + (f'<p class="hero-note">{note}</p>' if note else "")
        + (f'<ul class="hero-stats">{"".join(stats)}</ul>' if players else "")
        + "</div></section>")


def _headline(players, ranked, placing, names, placement_games):
    """The line under the tagline — only when there is something to explain.

    A ladder in full swing needs no sentence about itself; one that hasn't
    started yet needs to say what would start it.
    """
    if not players:
        return ("Nobody has joined yet. Play a game, log it in Slack with "
                "<code>/tt log</code>, and the first rating appears here.")
    if not ranked:
        closest = placing[0] if placing else None
        if closest and elo.games_played(closest[1]):
            need = placement_games - elo.games_played(closest[1])
            return (f"Nobody has played {placement_games} games yet — "
                    f"{c.e(display_name(closest[0], names))} is {need} away, and "
                    "everyone starts at 1000.")
        return (f"Signed up, no games played yet. {placement_games} games each "
                "and this fills up.")
    return ""


def _tabs(view):
    """One URL per view, so a tab can be pasted into the channel."""
    links = []
    for value, label in VIEWS:
        on = ' class="on" aria-current="page"' if (view or "") == value else ""
        href = f"?view={value}" if value else "?"
        links.append(f'<a{on} href="{c.e(href)}" data-keep>{label}</a>')
    return ('<nav class="tabs" aria-label="Format">' + "".join(links) + "</nav>")


# --- the leader ------------------------------------------------------------

def _featured(ranked, placing, names, placement_games, delta, played, form,
              log_href, known=True, titles=None, view=""):
    """Whoever is top, at scoreboard size. Before anyone qualifies it counts
    down to the first ranked player instead of showing an empty panel."""
    if ranked:
        uid, player = ranked[0]
        streak = c.streak_badge(player["streak"], long=True)
        pairs = [
            ("Record", c.record(player)),
            ("Games", c.games_line(player)),
            ("Peak", f'<span class="num">{player["peak"]}</span>'),
        ]
        meta = "".join(f'<div class="pair"><span class="pair-value">{value}</span>'
                       f'<span class="pair-label">{c.e(label)}</span></div>'
                       for label, value in pairs)
        strip = c.form_strip(form.get(uid, ""))
        return (
            '<section class="wrap rise rise-1"><div class="featured">'
            + icons.net()
            + '<div class="featured-in">'
              '<div class="featured-rank"><span class="hash num">#01</span></div>'
              '<div class="featured-body">'
              '<p class="eyebrow bright">#1 on the ladder</p>'
              f'<div class="featured-who">{c.avatar(uid, names, "avatar-lg")}'
            + c.player_link(uid, names, view, classes="featured-name")
            + "</div>"
            + f'<div class="featured-tags">{c.titles_of(uid, titles)}'
              f'{streak}{strip}</div>'
            + "</div>"
              '<div class="featured-rating">'
              f'<span class="value num">{player["rating"]}</span>'
              f'{c.movement(delta.get(uid, 0), played.get(uid, 0)) if known else ""}</div>'
            + f'<div class="featured-meta">{meta}</div>'
            + "</div></div></section>")

    if placing and elo.games_played(placing[0][1]):
        uid, player = placing[0]
        need = placement_games - elo.games_played(player)
        return (
            '<section class="wrap rise rise-1"><div class="featured is-empty">'
            '<div class="featured-in"><div class="featured-body">'
            '<p class="eyebrow">No leader yet</p>'
            f'<p class="featured-name">{need} {"game" if need == 1 else "games"} '
            "until the ladder has a leader</p>"
            f'<p class="note" style="margin:0">{c.e(display_name(uid, names))} is '
            f"closest, on {elo.games_played(player)}.</p></div>"
            '<div class="featured-rating">'
            f'<span class="value num">{need}</span></div>'
            "</div></div></section>")

    return ('<section class="wrap rise rise-1">'
            + c.empty_state("No matches yet", "Your first rally is waiting.",
                            "Log the first match", log_href or "#how")
            + "</section>")


# --- the board -------------------------------------------------------------

def _board(ranked, names, delta, played, form, moves, known=True, titles=None,
           view=""):
    """The standings. `known` is False when this view has no way to work out
    weekly movement, in which case the column simply isn't there — better than
    reporting a change of zero that nobody measured."""
    if not ranked:
        return ""
    rows = []
    for i, (uid, player) in enumerate(ranked, start=1):
        rows.append(
            f'<li class="row{" is-top" if i == 1 else ""}">'
            f'<span class="row-rank"><span class="pos num">{i:02d}</span>'
            f'{c.rank_move(moves.get(uid, 0))}</span>'
            f'<span class="row-who">{c.avatar(uid, names)}'
            + c.player_link(uid, names, view, classes="row-name")
            + c.titles_of(uid, titles, limit=1)
            + "</span>"
            + f'<span class="row-meta">{c.record(player)} &middot; '
            f'{c.games_line(player)}{c.streak_badge(player["streak"])}</span>'
            f'<span class="row-form">'
            f'{c.form_strip(form.get(uid, ""), label=False)}</span>'
            f'<span class="row-score"><span class="rating num">{player["rating"]}</span>'
            f'{c.movement(delta.get(uid, 0), played.get(uid, 0), compact=True) if known else ""}</span>'
            "</li>")
    return ('<section class="wrap rise rise-2">'
            '<div class="section-head"><h2>Standings</h2>'
            f'<p class="eyebrow">{len(ranked)} ranked</p></div>'
            f'<ol class="board">{"".join(rows)}</ol></section>')


def _placing(placing, names, placement_games, view=""):
    if not placing:
        return ""
    chips = []
    for uid, player in placing[:24]:
        need = placement_games - elo.games_played(player)
        chips.append(f'<li>{c.avatar(uid, names, "avatar-sm")}'
                     + c.player_link(uid, names, view)
                     + f'<span class="need num">{need} to go</span></li>')
    return ('<section class="wrap rise">'
            '<div class="section-head"><h2>Still placing</h2></div>'
            f'<p class="note wide">{placement_games} games and you join the standings '
            "above. Ratings are already moving.</p>"
            f'<ul class="placing">{"".join(chips)}</ul></section>')


def _controls(board, view, has_spins, on_spins):
    """The two controls, on one line: which board, then which format.

    They do different jobs, so they do not look the same — the board toggle
    carries an icon and its own outline, and the format tabs step aside
    entirely on the spins board, which belongs to no format.
    """
    toggle = _board_toggle(board, view, has_spins)
    tabs = "" if on_spins else _tabs(view)
    if not (toggle or tabs):
        return ""
    return f'<section class="wrap controls">{toggle}{tabs}</section>'


def _board_toggle(board, view, has_spins):
    """Ratings or spins. Only shown once there is a spins table to switch to —
    a toggle with nothing on the other side is furniture, not a control."""
    if not has_spins:
        return ""
    links = []
    for value, label in BOARDS:
        on = ' class="on" aria-current="page"' if (board or "") == value else ""
        query = {}
        if value:
            query["board"] = value
        elif view:
            query["view"] = view      # coming back lands on the tab you left
        from urllib.parse import urlencode
        href = ("?" + urlencode(query)) if query else "?"
        links.append(f'<a{on} href="{c.e(href)}" data-keep>{label}</a>')
    return ('<nav class="tabs board-toggle" aria-label="Leaderboard">'
            f'<span class="toggle-icon" aria-hidden="true">{icons.swap()}</span>'
            + "".join(links) + "</nav>")


def _spins_board(spins, names, start_spins, circulating, wallets=None):
    """The betting leaderboard, built like the ratings one so nobody has to
    learn a second table.

    `wallets` is {uid: (won, lost)} where it is known; without it the board
    still shows what everyone holds and how far that is from where they began,
    which is the part that is always derivable.
    """
    if not spins:
        return ""
    rows = []
    for i, (uid, held, net) in enumerate(spins, start=1):
        if net > 0:
            move = (f'<span class="move up">{c.UP} <span class="num">+{net:,}</span>'
                    '<span class="sr-only"> spins up on the start</span></span>')
        elif net < 0:
            move = (f'<span class="move down">{c.DOWN} <span class="num">{net:,}</span>'
                    '<span class="sr-only"> spins down on the start</span></span>')
        else:
            move = f'<span class="move">{c.LEVEL} <span>where they started</span></span>'
        rows.append(
            f'<li class="row{" is-top" if i == 1 else ""}">'
            f'<span class="row-rank"><span class="pos num">{i:02d}</span></span>'
            f'<span class="row-who">{c.avatar(uid, names)}'
            + c.player_link(uid, names, classes="row-name")
            + "</span>"
            + f'<span class="row-meta">opened with {start_spins:,}</span>'
            f'<span class="row-score"><span class="rating num">{held:,}</span>'
            f'{move}</span></li>')
    total = circulating if circulating is not None else sum(h for _, h, _ in spins)
    moved = sum(1 for _, _, net in spins if net)
    return ('<section class="wrap rise rise-1">'
            '<div class="section-head"><h2>Spins</h2>'
            f'<p class="eyebrow">{total:,} in circulation</p></div>'
            '<p class="note wide">Play money, staked on scheduled matches in Slack. '
            f'Everyone opened with {start_spins:,} and nothing mints more, so a '
            'spin won is a spin somebody else lost — which is why this table '
            f'always adds up. {moved} of {len(spins)} have moved off the start.</p>'
            f'<ol class="board">{"".join(rows)}</ol></section>')


# --- match of the week ------------------------------------------------------

def _of_the_week(history, week, names, view=derive.OVERALL, titles=None):
    """One match from this week, and the rule that picked it.

    `derive.match_of_week` returns nothing when the week has no matches, or
    none that moved anything — and nothing is then what this shows. The reason
    is printed beside it, so the card is never an unexplained favourite.
    """
    picked = (derive.match_of_week([b for b in history if derive.in_view(b, view)], week)
              if history and week else None)
    if not picked:
        return ""
    blob, reason = picked
    return ('<section class="wrap rise">'
            '<div class="section-head"><h2>Match of the week</h2>'
            f'<p class="eyebrow bright">{c.e(reason)}</p></div>'
            f'<div class="motw">{c.match_card(blob, names, view, titles)}'
            "</div></section>")


# --- spins -----------------------------------------------------------------

DAY_CHIPS = c.DAY_CHIPS   # kept as page.DAY_CHIPS for anything that imports it


def _recent(recent, names, players, filters, view=derive.OVERALL, titles=None):
    """The match list, with the player and day filters above it.

    `filters` is {"player": uid, "day": what was asked for, "label": how to say
    it} — already validated by the caller, so anything here is safe to echo.
    The filters are plain links and a GET form: they work with no script, and
    the one line of script merely saves the tap on a Go button.
    """
    player = filters.get("player") or ""
    day = filters.get("day") or ""
    label = filters.get("label") or ""
    filtered = bool(player or day)
    # A format tab shows that format, here as everywhere else on the page.
    recent = [blob for blob in recent if derive.in_view(blob, view)]
    if not recent and not filtered and not players:
        return ""

    heading = "Recent matches"
    if filtered:
        bits = [c.e(display_name(player, names))] if player else []
        if label:
            bits.append(c.e(label))
        heading = "Matches &middot; " + " &middot; ".join(bits)

    shown = recent[:FILTERED_SHOWN if filtered else RECENT_SHOWN]
    cards = "".join(c.match_card(blob, names, view, titles) for blob in shown)

    if not recent:
        cards = c.empty_state(
            "Nothing here" if filtered else "No matches yet",
            "Try another day, or clear the filters." if filtered
            else "Your first rally is waiting.")
    count = ""
    if filtered and recent:
        count = (f'<p class="count">{len(recent)} matches, showing the latest '
                 f'{len(shown)}.</p>' if len(recent) > len(shown)
                 else f'<p class="count">{len(shown)} '
                      f'match{"es" if len(shown) != 1 else ""}.</p>')

    return ('<section class="wrap rise rise-3">'
            f'<div class="section-head"><h2>{heading}</h2></div>'
            + c.filter_bar(players, names, {"player": player, "day": day},
                           groups=(c.DAY_GROUP,), iso=filters.get("iso", ""))
            + count
            + (f'<div class="matches">{cards}</div>' if recent else cards)
            + "</section>")


