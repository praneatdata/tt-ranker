"""One player: where they stand, how they got there, and against whom.

Everything here is read off records that already exist — the rating line is the
stored before/after pair of each match, the head-to-head is the matches the two
actually played. Where a figure can't be known for this format, the block that
would hold it isn't drawn.
"""
import elo

from .. import components as c
from .. import derive, icons, layout

FORM_SHOWN = 10        # a longer strip than the board's five; there is room
MATCHES_SHOWN = 8
RIVALS_SHOWN = 6


def render(uid, player, players, names, history=(), week="", view="",
           placement_games=4, rank=None, delta=0, played=0, known=True,
           versus="", log_href="", channel_hint="", updated="", titles=None,
           now=None):
    name = c.display_name(uid, names)
    games = elo.games_played(player)
    form = derive.form(history, view, limit=FORM_SHOWN).get(uid, "")
    mine = [b for b in history
            if uid in tuple(b.get("side_a", ())) + tuple(b.get("side_b", ()))
            and derive.in_view(b, view)]

    body = [_header(uid, player, names, rank, delta, played, known, view,
                    placement_games, games, titles)]
    body.append(_figures(player, games, form))
    body.append(_chart(history, uid, view))
    body.append(_turnout(history, uid, view, now))
    body.append(_versus(uid, mine, names, view, versus))
    body.append(_matches(mine, names, view, titles))
    return layout.document(f"{name} — RALLY", "".join(part for part in body if part),
                           current="Players", log_href=log_href,
                           channel_hint=channel_hint, updated=updated)


def _header(uid, player, names, rank, delta, played, known, view,
            placement_games, games, titles=None):
    worn = "".join(c.title_chip(key, long=True)
                   for key in (titles or {}).get(uid, []))
    place = (f'<span class="hash num">#{rank:02d}</span>' if rank
             else '<span class="hash num is-placing">&mdash;</span>')
    standing = (f"#{rank} on the {_format_name(view).lower()} ladder" if rank
                else f"{max(placement_games - games, 0)} games from the "
                     f"{_format_name(view).lower()} board")
    return (
        '<section class="profile rise"><div class="wrap profile-in">'
        f'<div class="profile-rank">{place}</div>'
        '<div class="profile-who">'
        f'<p class="eyebrow bright">{c.e(standing)}</p>'
        f'<div class="featured-who">{c.avatar(uid, names, "avatar-lg")}'
        f'<h1 class="featured-name">{c.e(c.display_name(uid, names))}</h1></div>'
        + (f'<div class="profile-titles">{worn}</div>' if worn else "")
        + f'{_tabs(uid, view)}'
        f'<p class="profile-actions"><a class="btn" href="{c.e(_compare_href(uid, view))}">'
        f'{icons.swap()}Compare</a></p>'
        "</div>"
        '<div class="featured-rating">'
        f'<span class="value num">{player["rating"]}</span>'
        f'{c.movement(delta, played) if known else ""}</div>'
        "</div></section>")


def _compare_href(uid, view):
    from urllib.parse import urlencode
    query = {"a": uid}
    if view:
        query["view"] = view
    return "/compare?" + urlencode(query)


def _figures(player, games, form):
    won, lost = player["games_won"], player["games_lost"]
    rate = round(100 * won / games) if games else None
    pairs = [("Record", c.record(player)),
             ("Matches", f'<span class="num">{player["matches"]}</span>'),
             ("Games", c.games_line(player))]
    if rate is not None:
        pairs.append(("Win rate", f'<span class="num">{rate}%</span>'))
    pairs.append(("Peak", f'<span class="num">{player["peak"]}</span>'))
    if player["best_streak"] >= 2:
        pairs.append(("Best run", f'<span class="num">{player["best_streak"]}</span> wins'))
    figures = "".join(f'<div class="pair"><span class="pair-value">{value}</span>'
                      f'<span class="pair-label">{c.e(label)}</span></div>'
                      for label, value in pairs)
    streak = c.streak_badge(player["streak"], long=True)
    strip = (f'<div class="profile-form">{c.form_strip(form)}</div>' if form else "")
    return ('<section class="wrap rise rise-1">'
            f'<div class="profile-figures">{figures}</div>'
            + (f'<div class="profile-tags">{streak}{strip}</div>'
               if streak or strip else "")
            + "</section>")


def _chart(history, uid, view):
    series = derive.rating_series(history, uid, view)
    if len(series) < 2:
        return c.section(
            "Rating", c.empty_state(
                "Not enough matches yet",
                "The line needs two results to draw. Play another and it appears."),
            eyebrow="History", classes="rise-2")
    first, last = series[0][1], series[-1][1]
    move = c.movement(last - first, len(series) - 1, suffix="over this run")
    return c.section("Rating", c.rating_chart(series) + f'<p class="chart-move">{move}</p>',
                     eyebrow=f"{len(series) - 1} matches", classes="rise-2")


def _turnout(history, uid, view, now):
    """Who actually turns up, as a square per day.

    Drawn from the oldest session still on record rather than from a fixed year
    ago, because a player's history is trimmed to the last
    `store.PLAYER_HISTORY_LIMIT` matches. Every square on the graph is then a
    day we genuinely know about — an empty one means nobody played, never "that
    was thrown away".
    """
    if not now:
        return ""
    columns, counts, span = derive.contributions(history, uid, now, view)
    if not columns:
        return ""
    played = sum(counts.values())
    start, end = span
    return c.section(
        "Turning up", c.heatmap(columns, counts, span),
        eyebrow=f"{played} match{'es' if played != 1 else ''} on {len(counts)} "
                f"day{'s' if len(counts) != 1 else ''}",
        note=f"Every session on record, from {start.day} "
             f"{c.MONTHS[start.month - 1]} {start.year} onwards — as far back as "
             "the ladder keeps this player's matches.",
        classes="rise-2")


def _versus(uid, mine, names, view, versus):
    """Head to head — against whoever was asked for, else the oldest rivalry."""
    rivals = derive.opponents(mine, uid, view)
    if not rivals:
        return ""
    chosen = versus if versus in dict(rivals) else rivals[0][0]
    h2h = derive.head_to_head(mine, uid, chosen, view)
    if not h2h:
        return ""
    picker = "".join(
        f'<a class="rival{" on" if other == chosen else ""}" '
        f'href="{c.e(_href(uid, view, other))}" data-keep>'
        f'{c.avatar(other, names, "avatar-sm")}'
        f'<span>{c.e(c.display_name(other, names))}</span>'
        f'<span class="rival-count num">{count}</span></a>'
        for other, count in rivals[:RIVALS_SHOWN])
    return c.section("Head to head",
                     f'<div class="rivals">{picker}</div>'
                     + c.head_to_head(h2h, uid, chosen, names, view),
                     eyebrow=f"{len(rivals)} opponent{'s' if len(rivals) != 1 else ''}",
                     classes="rise-3")


def _matches(mine, names, view=derive.OVERALL, titles=None):
    if not mine:
        return c.section("Matches", c.empty_state(
            "No matches yet", "Their first rally is waiting."))
    return c.section("Matches",
                     '<div class="matches">'
                     + "".join(c.match_card(b, names, view, titles)
                                for b in mine[:MATCHES_SHOWN])
                     + "</div>",
                     eyebrow=f"last {min(len(mine), MATCHES_SHOWN)}")


def _href(uid, view, versus=""):
    from urllib.parse import urlencode
    query = urlencode({k: v for k, v in (("view", view), ("vs", versus)) if v})
    return f"/player/{uid}" + (f"?{query}" if query else "")


def _format_name(view):
    return {"": "Singles", "doubles": "Doubles", "overall": "Overall"}.get(view, "Singles")


def _tabs(uid, view):
    links = []
    for value, label in (("", "Singles"), ("doubles", "Doubles"), ("overall", "Overall")):
        on = ' class="on" aria-current="page"' if (view or "") == value else ""
        links.append(f'<a{on} href="{c.e(_href(uid, value))}" data-keep>{label}</a>')
    return '<nav class="tabs" aria-label="Format">' + "".join(links) + "</nav>"
