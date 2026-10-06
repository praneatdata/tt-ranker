"""The wall of shame — results thrown out, challenges ducked, fixtures bailed on.

The counterpart to Titles. That page is what there is to win here besides a
number; this is what there is to lose. Both are read the same way — a list of
things with names against them — so this page is built from the same parts.

**It says it is a joke, on the page, in the same size as everything else.**
Pressing *That's wrong* on a wrong scoreline is the only thing standing between
the ladder and whatever anybody feels like typing, and a board that shames
people for it pushes them toward waving results through. If the board ever stops
reading as a joke, the fix is to drop that column — or the page — rather than to
keep the same score more quietly.
"""
import shame

from .. import components as c
from .. import layout


def render(board, names, log_href="", channel_hint="", updated="", view=""):
    """`board` is what shame.board() returns: [(uid, {kind: n}, score)]."""
    stats = [c.stat_tile(len(board), "On the wall"),
             c.stat_tile(sum(sum(row.values()) for _, row, _ in board), "In all")]
    body = [c.page_header(
        "Wall of shame", eyebrow="Beyond the rating",
        lead="Results thrown out, challenges ducked, and matches nobody ever "
             "got round to playing.",
        stats=stats)]

    if board:
        rows = "".join(_row(i, uid, row, points, names, view)
                       for i, (uid, row, points) in enumerate(board, start=1))
        body.append(f'<section class="wrap rise rise-1"><ol class="shame">{rows}</ol>'
                    "</section>")
    else:
        body.append('<section class="wrap rise rise-1">'
                    + c.empty_state(
                        "Nothing on it",
                        "Every result confirmed, every challenge answered, every "
                        "fixture played. Suspicious.")
                    + "</section>")

    body.append(f'<section class="wrap rise rise-2">{_key()}</section>')
    body.append(
        '<section class="wrap rise rise-3"><p class="note wide">'
        "Counted as it happens rather than worked out afterwards, because most "
        "of these destroy the record they happened to — throwing a result out "
        "deletes it, which is the point of throwing it out. Taking back "
        "<em>your own</em> logged result doesn't count, nor does withdrawing "
        "your own challenge, and an open call nobody takes shames nobody. "
        "<strong>This is a joke board.</strong> Rejecting a score that really is "
        "wrong is the ladder working — it is the only thing keeping the results "
        "honest, and nobody should ever wave one through to stay off a list."
        "</p></section>")
    return layout.document("Wall of shame — RALLY", "".join(body),
                           current="Shame", log_href=log_href,
                           channel_hint=channel_hint, updated=updated)


def _row(place, uid, row, points, names, view=""):
    tallies = "".join(
        f'<li class="shame-tally"><span class="n num">{row[kind]}</span>'
        f'<span class="k">{c.e(name)}</span></li>'
        for kind, name, _, _ in shame.KINDS if row.get(kind))
    return (f'<li class="shame-row{" is-worst" if place == 1 else ""}">'
            f'<span class="rank num">{place:02d}</span>'
            f'<span class="who">{c.avatar(uid, names, "avatar-sm")}'
            f'{c.player_link(uid, names, view, classes="shame-name")}</span>'
            f'<ul class="shame-tallies">{tallies}</ul>'
            f'<span class="shame-score num">{points}</span>'
            "</li>")


def _key():
    """What each column means, and what it costs on the total."""
    items = "".join(
        f'<li class="shame-key-item"><span class="k">{c.e(name)}</span>'
        f'<span class="d">{c.e(blurb)}</span>'
        f'<span class="w num">{shame.WEIGHTS.get(kind, 1)}</span></li>'
        for kind, name, blurb, _ in shame.KINDS)
    return ('<div class="shame-key"><p class="shame-key-head">What counts, and '
            'what each one is worth</p>'
            f'<ul>{items}</ul></div>')
