"""Two to four players, side by side.

Everything here is a comparison of records that already exist: their figures in
one table, the matches they have actually played against one another, and their
rating lines on one pair of axes. Nothing is averaged, projected or predicted —
where two of them have never met, the record says so instead of inventing one.

Four is the ceiling. Past that the columns stop being readable on a laptop, let
alone a phone, and a comparison nobody can read is not a comparison.
"""
import elo

from .. import components as c
from .. import derive, layout

MAX = c.COMPARE_MAX

ROWS = (
    ("Rating", lambda p: f'<span class="num">{p["rating"]}</span>', "high"),
    ("Record", lambda p: c.record(p), None),
    ("Matches", lambda p: f'<span class="num">{p["matches"]}</span>', "high"),
    ("Games won", lambda p: c.games_line(p), None),
    ("Win rate", lambda p: _rate(p), "high"),
    ("Peak", lambda p: f'<span class="num">{p["peak"]}</span>', "high"),
    ("Best run", lambda p: f'<span class="num">{p["best_streak"]}</span> wins', "high"),
)


def _rate(player):
    games = elo.games_played(player)
    return (f'<span class="num">{round(100 * player["games_won"] / games)}%</span>'
            if games else "&#8212;")


def _value(player, label):
    """The number a row is compared on, for deciding which column to mark.
    None where a row has nothing orderable in it."""
    games = elo.games_played(player)
    return {"Rating": player["rating"], "Matches": player["matches"],
            "Peak": player["peak"], "Best run": player["best_streak"],
            "Win rate": (player["games_won"] / games) if games else None}.get(label)


def render(uids, players, names, history=(), view="", ranks=None, log_href="",
           channel_hint="", updated="", bare=False, titles=None):
    """`bare` renders the comparison without the page around it — what the
    popup on the players page fetches and shows in place."""
    uids = [uid for uid in (uids or []) if uid in players][:MAX]
    ranks = ranks or {}
    if len(uids) < 2:
        return _pick(names, view, uids, log_href, channel_hint, updated, bare)

    body = [_header(uids, players, names, ranks, bare, titles)]
    body.append(c.section("Side by side", _table(uids, players, names),
                          classes="rise-1"))
    body.append(_versus(uids, history, names, view, titles))
    body.append(_lines(uids, history, names, view))
    if not bare:
        body.append('<section class="wrap rise">'
                    + c.compare_tray(names, uids, view) + "</section>")
    inner = "".join(part for part in body if part)
    if bare:
        return inner
    title = " v ".join(c.display_name(uid, names) for uid in uids)
    return layout.document(f"{title} — RALLY", inner, current="Players",
                           log_href=log_href, channel_hint=channel_hint,
                           updated=updated)


def _pick(names, view, chosen, log_href, channel_hint, updated, bare=False):
    """Fewer than two to compare — the pickers, and nothing pretending to be
    data."""
    empty = c.empty_state("Pick two players",
                          "Choose at least two and their records appear here.",
                          "" if bare else "Back to players",
                          "" if bare else "/players", cta_icon=False)
    if bare:
        return f'<section class="wrap rise">{empty}</section>'
    body = (c.page_header("Compare", eyebrow="Up to four players",
                          lead="Pick two or more and see the record between them.",
                          extra='<div class="find">'
                                + c.compare_tray(names, chosen, view) + "</div>")
            + f'<section class="wrap rise">{empty}</section>')
    return layout.document("Compare — RALLY", body, current="Players",
                           log_href=log_href, channel_hint=channel_hint,
                           updated=updated)


def _header(uids, players, names, ranks, bare, titles=None):
    cards = "".join(
        f'<div class="cmp-side">{c.avatar(uid, names, "avatar-lg")}'
        f'<a class="cmp-name" href="/player/{c.e(uid)}">'
        f'{c.e(c.display_name(uid, names))}</a>'
        + (f'<span class="cmp-titles">{c.titles_of(uid, titles)}</span>'
           if c.titles_of(uid, titles) else "")
        + f'<span class="cmp-rank">'
        f'{"#%02d" % ranks[uid] if ranks.get(uid) else "Still placing"}</span>'
        f'<span class="cmp-rating num">{players[uid]["rating"]}</span></div>'
        for uid in uids)
    head = (f'<div class="cmp-head cmp-of-{len(uids)}">{cards}</div>')
    if bare:
        return f'<section class="wrap cmp-bare-head">{head}</section>'
    return ('<section class="page-head rise"><div class="wrap">'
            '<p class="eyebrow">Head to head</p>' + head + "</div></section>")


def _table(uids, players, names):
    """One column per player, one row per figure, the leader of each marked."""
    heads = "".join(
        f'<th scope="col">{c.e(c.display_name(uid, names))}</th>' for uid in uids)
    rows = []
    for label, render_value, better in ROWS:
        values = [_value(players[uid], label) for uid in uids]
        known = [v for v in values if v is not None]
        best = max(known) if (better == "high" and known and len(set(known)) > 1) else None
        cells = "".join(
            f'<td class="cmp-cell{" leads" if best is not None and value == best else ""}">'
            f'{render_value(players[uid])}</td>'
            for uid, value in zip(uids, values))
        rows.append(f'<tr><th scope="row">{c.e(label)}</th>{cells}</tr>')
    return (f'<div class="cmp-scroll"><table class="cmp-table cmp-of-{len(uids)}">'
            f'<thead><tr><td></td>{heads}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _versus(uids, history, names, view, titles=None):
    """Two players get their head-to-head in full; three or more get the grid,
    because six separate blocks would be a wall rather than a comparison."""
    ladder = view or derive.OVERALL
    if len(uids) == 2:
        one, two = uids
        h2h = derive.head_to_head(history, one, two, ladder)
        if not h2h:
            return c.section("Between them", c.empty_state(
                "They haven't played",
                "No match on record has these two on opposite sides."),
                classes="rise-2")
        cards = "".join(c.match_card(blob, names, ladder, titles)
                        for blob in h2h["recent"])
        return c.section("Between them",
                         c.head_to_head(h2h, one, two, names, view)
                         + (f'<div class="matches cmp-matches">{cards}</div>'
                            if cards else ""),
                         eyebrow=f"{h2h['matches']} "
                                 f"meeting{'s' if h2h['matches'] != 1 else ''}",
                         classes="rise-2")

    grid = c.head_to_head_grid(uids, history, names, view)
    if not grid:
        return c.section("Between them", c.empty_state(
            "No meetings on record",
            "None of these players has faced another of them yet."),
            classes="rise-2")
    return c.section("Between them", grid,
                     eyebrow="Wins each way", classes="rise-2")


def _lines(uids, history, names, view):
    series = [(c.display_name(uid, names),
               derive.rating_series(history, uid, view or derive.OVERALL))
              for uid in uids]
    chart = c.rating_chart_pair(series)
    if not chart:
        return ""
    legend = "".join(
        f'<span class="legend-key l{i}">{c.e(label)}</span>'
        for i, (label, points) in enumerate(series) if len(points) > 1)
    return c.section("Rating", chart + f'<p class="legend">{legend}</p>',
                     eyebrow="Over the matches on record", classes="rise-3")
