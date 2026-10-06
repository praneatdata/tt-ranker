"""The pieces every RALLY page is built from.

Each function takes plain data and returns an HTML string, so a component can
be rendered and asserted on in a test with nothing else running. Two habits
hold throughout:

  Escape at the edge. Anything that came from a person — a name, a filter —
  goes through `e()` here, so a page never has to remember to.

  Never say it with colour alone. Every win, loss, rise and fall carries a
  glyph and a word for a screen reader as well as a tint, because a colour is
  the one signal a reader may not receive.
"""
import html

import awards

from . import derive, icons, tokens

UP, DOWN, LEVEL = "&#9650;", "&#9660;", "&#8212;"


def e(text):
    return html.escape(str(text), quote=True)


def player_href(uid, view=""):
    """Where a player's name points. One helper, used by every page that draws
    a person, so nobody's name is a dead end on one page and a link on the next
    — and so the format tab a reader is on travels with them rather than
    dumping them back on Singles."""
    return f"/player/{uid}" + (f"?view={view}" if view else "")


def player_link(uid, names, view="", classes="", extra=""):
    """A name that goes to the person it names."""
    css = f' class="{classes}"' if classes else ""
    return (f'<a{css} href="{e(player_href(uid, view))}"{extra}>'
            f'{e(display_name(uid, names))}</a>')


def display_name(uid, names):
    """What to call someone. Falls back to the tail of their Slack id, which is
    at least stable and short, rather than an empty row."""
    return names.get(uid) or f"@{uid[-4:]}"


def initials(name):
    """One or two letters for a monogram. `@E092` has no word in it, so the
    fallback takes the first character that is one."""
    words = [w for w in str(name).replace("@", " ").split() if w]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:1].upper()
    return (words[0][:1] + words[1][:1]).upper()


def avatar(uid, names, size=""):
    """A monogram tinted per player — identity without a photograph.

    Decorative: the name it stands for is always beside it, so it is hidden
    from screen readers rather than read out twice.
    """
    tint = tokens.avatar_tint(uid)
    classes = "avatar" + (f" {size}" if size else "")
    return (f'<span class="{classes}" style="color:{tint}" aria-hidden="true">'
            f'{e(initials(display_name(uid, names)))}</span>')


def movement(delta, played=0, suffix="this week", compact=False):
    """A rating change, said in a glyph, a number and a word.

    "Level" and "didn't play" are different facts that would otherwise look
    identical, so both are named rather than collapsing to the same dash. In a
    leaderboard row there is only room for the short form, and the full sentence
    goes to a screen reader instead.
    """
    said = "no games" if not played and not delta else "level"
    if not delta:
        short = f'<span>{e(said)}</span>' if compact else f'<span>{e(said)} {e(suffix)}</span>'
        extra = f'<span class="sr-only"> {e(suffix)}</span>' if compact else ""
        return f'<span class="move">{LEVEL} {short}{extra}</span>'
    if delta > 0:
        return (f'<span class="move up">{UP} <span class="num">+{delta}</span>'
                f'<span class="sr-only"> rating gained {e(suffix)}</span></span>')
    return (f'<span class="move down">{DOWN} <span class="num">{delta}</span>'
            f'<span class="sr-only"> rating lost {e(suffix)}</span></span>')


def rank_move(places):
    """Places climbed or lost this week, under the rank number."""
    if not places:
        return ""
    if places > 0:
        return (f'<span class="rank-move up">{UP}{places}'
                f'<span class="sr-only"> places up this week</span></span>')
    return (f'<span class="rank-move down">{DOWN}{abs(places)}'
            f'<span class="sr-only"> places down this week</span></span>')


WORDS = {"W": "won", "L": "lost", "D": "drew"}


def form_strip(results, label=True):
    """The last few results, oldest first — letters, not just colours."""
    if not results:
        return ""
    cells = "".join(f'<span class="form-cell {r.lower()}" aria-hidden="true">{r}</span>'
                    for r in results)
    said = ", ".join(WORDS[r] for r in results)
    head = '<span class="form-label">Form</span>' if label else ""
    return (f'<span class="form">{head}{cells}'
            f'<span class="sr-only">Recent form, oldest first: {e(said)}</span></span>')


def streak_badge(streak, long=False):
    """A run worth mentioning. Three is where a streak starts being one."""
    streak = int(streak or 0)
    if streak >= 3:
        text = f"{streak} win streak" if long else f"{streak}W streak"
        return f'<span class="streak hot">{icons.flame()}{e(text)}</span>'
    if streak <= -3:
        text = f"{abs(streak)} loss streak" if long else f"{abs(streak)}L streak"
        return f'<span class="streak cold">{icons.snow()}{e(text)}</span>'
    return ""


# --- titles -----------------------------------------------------------------

def title_chip(key, long=False):
    """One title, worn beside a name.

    Every chip carries its own glyph and its own word, so it never depends on
    the colour behind it — the rule the whole page is built on. `title` is the
    tooltip, because a badge reading "The Machine" should be able to say what
    it took to earn it without a trip to another page.
    """
    title = awards.BY_KEY.get(key)
    if not title:
        return ""
    glyph = getattr(icons, title.icon, None)
    return (f'<span class="title-chip {e(title.tone)}" title="{e(title.blurb)}">'
            + (glyph() if glyph else "")
            + f'<span>{e(title.name)}</span>'
            + (f'<span class="title-why">{e(title.blurb)}</span>' if long else "")
            + "</span>")


def titles_of(uid, titles, limit=None):
    """The chips one player wears. `titles` is awards.by_player()'s map, so a
    page that was handed no titles renders nothing rather than breaking."""
    held = (titles or {}).get(uid) or []
    if limit:
        held = held[:limit]
    return "".join(title_chip(key) for key in held)


def record(player):
    """4-0-1 — wins, losses, and draws only when there are any."""
    wins, losses, draws = player["wins"], player["losses"], player["draws"]
    return f"{wins}&#8211;{losses}" + (f"&#8211;{draws}" if draws else "")


def games_line(player):
    """10 / 12 wins — games, which is what ratings are actually made of."""
    won, lost = player["games_won"], player["games_lost"]
    return f"{won} / {won + lost} wins"


def stat(value, label, mono=True):
    """One figure in the hero's summary row."""
    cls = "stat-value num" if mono else "stat-value"
    return (f'<li><span class="{cls}">{value}</span>'
            f'<span class="stat-label">{e(label)}</span></li>')


def stat_tile(value, label):
    """The same figure, boxed — what a secondary page's header uses so the
    counts sit in the space beside the title rather than under it."""
    return (f'<li class="stat-tile"><span class="v num">{value}</span>'
            f'<span class="l">{e(label)}</span></li>')


def empty_state(title, body, cta_text="", cta_href="", cta_icon=True):
    """Says what is missing and what to do about it — never "no data found"."""
    button = ""
    if cta_text and cta_href:
        button = (f'<a class="btn btn-primary" href="{e(cta_href)}">'
                  f'{icons.plus() if cta_icon else ""}{e(cta_text)}</a>')
    elif cta_text:
        button = f'<span class="btn">{e(cta_text)}</span>'
    return (f'<div class="empty"><h3>{e(title)}</h3><p>{e(body)}</p>{button}</div>')


def match_card(blob, names, view=derive.OVERALL, titles=None):
    """One played session: who, the score in games, the rating it moved, and
    every individual game underneath.

    Built to serve doubles as readily as singles — a side is a list either way —
    and a draw as readily as a win, so pages never branch on match type.

    `view` is the ladder the reader is looking at, and it decides which rating
    change the card reports: on the singles board a match has to show what it
    did to the singles rating, or the card and the row above it would print
    two different numbers for the same result.
    """
    side_a, side_b = blob["side_a"], blob["side_b"]
    games_a, games_b = blob["games_a"], blob["games_b"]
    # A doubles match never touched the singles rating, so under the singles
    # ladder this card reports no change rather than the other ladder's number.
    deltas = derive.deltas_of(blob, view) if derive.in_view(blob, view) else {}

    def side(uids, won, extra=""):
        people = "".join(
            f'{avatar(uid, names, "avatar-sm")}'
            + player_link(uid, names, view if view != derive.OVERALL else "",
                          classes="side-name")
            + titles_of(uid, titles, limit=1)
            for uid in uids)
        moved = " · ".join(
            f'<span class="side-delta {_dir(deltas.get(uid, 0))}">'
            f'{_sign(deltas.get(uid, 0))}</span>' for uid in uids if uid in deltas)
        won_tag = '<span class="sr-only">winner. </span>' if won else ""
        classes = " ".join(part for part in ("side", extra, "won" if won else "") if part)
        return (f'<div class="{classes}">{won_tag}'
                f'<span class="side-names">{people}</span>'
                f'<span class="side-delta-row">{moved}</span></div>')

    tag = "Doubles" if blob.get("doubles") else "Singles"
    drawn = '<span class="tag">Drawn</span>' if games_a == games_b else ""
    when = _when(blob.get("applied_at", ""))
    games = "".join(f'<span class="num">{g[0]}&#8211;{g[1]}</span>'
                    for g in blob.get("games", []))
    everyone = " ".join(display_name(uid, names) for uid in side_a + side_b)
    return (
        f'<article class="match"{searchable(everyone + " " + tag)}>'
        f'<div class="match-top"><span class="tag">{tag}</span>{drawn}{when}</div>'
        '<div class="match-body">'
        + side(side_a, games_a > games_b)
        + f'<div class="match-score num" role="text">'
          f'<span>{games_a}</span><span class="sep">&#8211;</span><span>{games_b}</span>'
          f'<span class="sr-only"> games</span></div>'
        + side(side_b, games_b > games_a, "b")
        + "</div>"
        + (f'<div class="match-games">{games}</div>' if games else "")
        + "</article>")


def _dir(delta):
    return "up" if delta > 0 else "down" if delta < 0 else ""


def _sign(delta):
    return f"+{delta}" if delta > 0 else str(delta)


def _when(iso):
    """`17 Sep · 17:53` — enough to place a match without a full timestamp."""
    from datetime import datetime
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    # Day number written by hand: %-d is glibc-only and local dev may be anywhere.
    return (f'<time class="when num" datetime="{e(iso)}">{when.day} '
            f'{when.strftime("%b")} &middot; {when.strftime("%H:%M")}</time>')


# --- page furniture ---------------------------------------------------------

def page_header(title, eyebrow="", lead="", stats=(), extra=""):
    """The top of a secondary page — the ladder's hero, at working size."""
    # The counts sit beside the title, in the space a title leaves empty, and
    # the controls run underneath what they control.
    figures = f'<ul class="stat-tiles">{"".join(stats)}</ul>' if stats else ""
    return (
        '<section class="page-head rise"><div class="wrap">'
        '<div class="head-top"><div class="head-title">'
        + (f'<p class="eyebrow">{e(eyebrow)}</p>' if eyebrow else "")
        + f"<h1>{e(title)}</h1>"
        + (f'<p class="tagline">{lead}</p>' if lead else "")
        + "</div>" + figures + "</div>"
        + extra
        + "</div></section>")


def section(title, body, eyebrow="", note="", classes=""):
    """A titled block, the way every page divides itself up."""
    head = (f'<div class="section-head"><h2>{e(title)}</h2>'
            + (f'<p class="eyebrow">{eyebrow}</p>' if eyebrow else "")
            + "</div>")
    return (f'<section class="wrap rise {classes}">{head}'
            + (f'<p class="note">{note}</p>' if note else "")
            + body + "</section>")


# --- players ----------------------------------------------------------------

def player_card(uid, player, names, rank=None, movement="", form="", href="",
                pickable=False, picked=False, titles=None):
    """One player, as a card — the unit the players page is a grid of.

    While comparing, the card stops being a link and becomes something to
    choose: same card, one job swapped for another, so the grid never turns
    into a second set of controls.
    """
    worn = titles_of(uid, titles)
    place = f'<span class="pc-rank num">#{rank:02d}</span>' if rank else \
        '<span class="pc-rank pc-placing">Placing</span>'
    body = (
        f'<div class="pc-top">{place}{streak_badge(player["streak"])}</div>'
        f'<div class="pc-who">{avatar(uid, names, "avatar-lg")}'
        f'<span class="pc-name">{e(display_name(uid, names))}</span></div>'
        + (f'<div class="pc-titles">{worn}</div>' if worn else "")
        + f'<div class="pc-rating"><span class="num">{player["rating"]}</span>{movement}</div>'
        f'<div class="pc-meta"><span>{record(player)}</span>'
        f'<span>{games_line(player)}</span></div>'
        + (f'<div class="pc-form">{form_strip(form, label=False)}</div>' if form else ""))
    find = searchable(display_name(uid, names))
    if pickable:
        return (f'<button type="button" class="pc pc-pick{" is-picked" if picked else ""}" '
                f'data-uid="{e(uid)}" aria-pressed="{"true" if picked else "false"}"'
                f'{find}>{body}</button>')
    if href:
        return f'<a class="pc" href="{e(href)}"{find}>{body}</a>'
    return f'<div class="pc"{find}>{body}</div>'


def stat_card(label, value, detail=""):
    """One figure from the numbers — value loud, label quiet, source underneath."""
    return (f'<li class="sc"><span class="sc-value num">{value}</span>'
            f'<span class="sc-label">{e(label)}</span>'
            + (f'<span class="sc-detail">{detail}</span>' if detail else "")
            + "</li>")


# --- turning up --------------------------------------------------------------

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def heatmap(columns, counts, span, busiest=None):
    """A year of turning up, one square per day, drawn as a CSS grid.

    No chart library and no canvas: the page makes no external requests and a
    heatmap is a table of squares, which CSS already draws. Every square carries
    its own date and count in `title` and in text a screen reader can reach, so
    the graph is readable without seeing a single shade — colour is the summary
    here, never the information.
    """
    if not columns:
        return ""
    busiest = busiest or max(counts.values() or [0])
    cells = []
    for week in columns:
        column = []
        for cell in week:
            if cell is None:
                column.append('<span class="heat heat-off"></span>')
                continue
            day, count = cell
            level = derive.heat_level(count, busiest)
            said = (f"{count} match{'es' if count != 1 else ''} on "
                    f"{day.day} {MONTHS[day.month - 1]}" if count
                    else f"No matches on {day.day} {MONTHS[day.month - 1]}")
            column.append(f'<span class="heat heat-{level}" title="{e(said)}">'
                          f'<span class="sr-only">{e(said)}. </span></span>')
        cells.append(f'<div class="heat-col">{"".join(column)}</div>')

    days = "".join(f'<span class="heat-day">{WEEKDAYS[i] if i % 2 else ""}</span>'
                   for i in range(7))
    return (f'<div class="heat-wrap"><div class="heat-days">{days}</div>'
            f'<div class="heat-scroll"><div class="heat-grid" role="img" '
            f'aria-label="{e(_heat_summary(counts, span))}">'
            + "".join(cells) + "</div>"
            + _heat_months(columns) + "</div></div>"
            + _heat_key(busiest))


def _heat_summary(counts, span):
    played = sum(counts.values())
    days = len(counts)
    start, end = span
    return (f"{played} match{'es' if played != 1 else ''} on {days} "
            f"day{'s' if days != 1 else ''}, {start.day} {MONTHS[start.month - 1]} "
            f"to {end.day} {MONTHS[end.month - 1]}")


MONTH_GAP = 3   # columns a label needs before the next one, or they collide


def _heat_months(columns):
    """A month label over the column its first week falls in, the way every
    graph of this shape is read.

    A label is wider than the 11px column it sits over, so one is skipped when
    the month before it only got a week or two on screen — two month names
    printed on top of each other is worse than one of them missing.
    """
    labels, last, since = [], None, MONTH_GAP
    for week in columns:
        day = next((cell[0] for cell in week if cell), None)
        new_month = bool(day) and day.month != last
        if new_month and since >= MONTH_GAP:
            labels.append('<span class="heat-month">%s</span>' % MONTHS[day.month - 1])
            last, since = day.month, 0
        else:
            labels.append('<span class="heat-month"></span>')
            if new_month:
                last = day.month
            since += 1
    return '<div class="heat-months">%s</div>' % "".join(labels)


def _heat_key(busiest):
    swatches = "".join(f'<span class="heat heat-{level}"></span>'
                       for level in range(derive.HEAT_LEVELS + 1))
    return ('<p class="heat-key"><span>Quieter</span>'
            f'{swatches}<span>Busier</span>'
            f'<span class="heat-key-note">Busiest day: {busiest} '
            f"match{'es' if busiest != 1 else ''}</span></p>")


# --- rating history ---------------------------------------------------------

CHART_W, CHART_H, CHART_PAD = 640, 180, 18


def rating_chart(series, label="Rating"):
    """A rating over time, drawn from the stored before/after pair.

    Every point is a real rating that really applied; nothing is interpolated,
    and a single match is drawn as a single step rather than a trend. Two
    points are the minimum worth a line — below that the caller gets None and
    shows nothing.
    """
    if len(series) < 2:
        return ""
    values = [rating for _, rating in series]
    low, high = min(values), max(values)
    span = max(high - low, 1)
    inner_w, inner_h = CHART_W - CHART_PAD * 2, CHART_H - CHART_PAD * 2
    step = inner_w / float(len(values) - 1)

    def point(i, rating):
        x = CHART_PAD + i * step
        y = CHART_PAD + inner_h * (1 - (rating - low) / float(span))
        return x, y

    points = [point(i, v) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = (f"{CHART_PAD:.1f},{CHART_H - CHART_PAD:.1f} " + line +
            f" {points[-1][0]:.1f},{CHART_H - CHART_PAD:.1f}")
    last_x, last_y = points[-1]
    rise = values[-1] >= values[0]
    return (
        f'<figure class="chart {"up" if rise else "down"}">'
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" '
        f'role="img" aria-label="{e(label)} over the last {len(values) - 1} matches, '
        f'from {values[0]} to {values[-1]}">'
        f'<polygon class="chart-area" points="{area}"/>'
        f'<polyline class="chart-line" points="{line}"/>'
        f'<line class="chart-dot" x1="{last_x:.1f}" y1="{last_y:.1f}" '
        f'x2="{last_x:.1f}" y2="{last_y:.1f}"/>'
        "</svg>"
        f'<figcaption class="chart-scale"><span class="num">{high}</span>'
        f'<span class="num">{low}</span></figcaption>'
        f'<figcaption class="chart-foot">{e(label)} over the last '
        f'{len(values) - 1} {"match" if len(values) == 2 else "matches"}'
        f'</figcaption></figure>')


# --- head to head -----------------------------------------------------------

def head_to_head(h2h, one, two, names, view=""):
    """Two players, and what has actually happened between them."""
    wins, draws = h2h["wins"], h2h["draws"]
    total = max(wins[one] + wins[two] + draws, 1)
    # Three parts, not two: a draw belongs to neither of them, and colouring it
    # as the other player's win would overstate the record.
    bar = "".join(
        f'<span class="{cls}" style="width:{round(100 * count / total)}%"></span>'
        for cls, count in (("won", wins[one]), ("drew", draws), ("lost", wins[two]))
        if count)
    results = "".join(
        f'<span class="h2h-cell {_h2h_class(blob, one)}">'
        f'{_h2h_letter(blob, one)}</span>'
        for blob in reversed(h2h["recent"]))
    said = ", ".join(WORDS[_h2h_letter(blob, one)] for blob in reversed(h2h["recent"]))
    return (
        '<div class="h2h">'
        '<div class="h2h-sides">'
        f'<div class="h2h-side">{avatar(one, names)}'
        f'<span class="h2h-name">{e(display_name(one, names))}</span>'
        f'<span class="h2h-wins num">{wins[one]}</span></div>'
        f'<div class="h2h-side b">{avatar(two, names)}'
        f'<span class="h2h-name">{e(display_name(two, names))}</span>'
        f'<span class="h2h-wins num">{wins[two]}</span></div>'
        "</div>"
        f'<div class="h2h-bar">{bar}</div>'
        f'<p class="h2h-line">{h2h["matches"]} '
        f'{"meetings" if h2h["matches"] != 1 else "meeting"}'
        + (f' &middot; {draws} drawn' if draws else "")
        + f' &middot; {h2h["games"][one]}&#8211;{h2h["games"][two]} on games</p>'
        + (f'<div class="h2h-recent"><span class="form-label">Last</span>{results}'
           f'<span class="sr-only">, oldest first: {e(said)}</span></div>'
           if results else "")
        + "</div>")


def _h2h_letter(blob, uid):
    return result_of_for(blob, uid)


def _h2h_class(blob, uid):
    return {"W": "w", "L": "l", "D": "d"}[result_of_for(blob, uid)]


def result_of_for(blob, uid):
    """W, L or D for one player."""
    return derive.result_of(blob, uid)


# --- filters ----------------------------------------------------------------

# What may appear in a filter link. Anything else a page passes through
# `params` is display state, not query state.
QUERY_KEYS = ("player", "day", "format", "q", "view", "board")

DAY_CHIPS = (("", "All"), ("today", "Today"), ("yesterday", "Yesterday"),
             ("week", "This week"))
FORMAT_CHIPS = (("", "All"), ("singles", "Singles"), ("doubles", "Doubles"))
# (query key, chips, label). The label matters once there are two rows: two
# chips both reading "All", both lit, are ambiguous without one.
DAY_GROUP = ("day", DAY_CHIPS, "When")
FORMAT_GROUP = ("format", FORMAT_CHIPS, "Format")


def filter_bar(players, names, params, groups=(DAY_GROUP,), iso="",
               player_select=True, search=""):
    """The one filter bar, shared by the ladder and the matches page.

    `params` is the validated query state; `groups` is which chip rows to draw
    and what they set. Plain links and a GET form, so it works with no script —
    the one line of script only saves the tap on a Go button.

    `search` puts a search field in the bar itself, where it takes the width the
    row has spare; `player_select=False` then drops the picker it replaces,
    since naming a player and choosing one from a list are the same job.
    """
    player = params.get("player") or ""
    day = params.get("day") or ""
    carried = {k: v for k, v in params.items() if k in QUERY_KEYS and v}

    def href(**changes):
        from urllib.parse import urlencode
        merged = dict(carried)
        merged.update(changes)
        query = urlencode({k: v for k, v in merged.items() if v})
        return "?" + query if query else "?"

    picker = ""
    if player_select:
        options = ['<option value="">Everyone</option>']
        for uid, _ in sorted(players.items(),
                             key=lambda i: display_name(i[0], names).lower()):
            sel = " selected" if uid == player else ""
            options.append(f'<option value="{e(uid)}"{sel}>'
                           f'{e(display_name(uid, names))}</option>')
        picker = (f'<select name="player" aria-label="Player">'
                  + "".join(options) + "</select>")
    elif player:
        # Still filtering by a player, just without the list: keep it in the
        # query so the chips and the search don't silently drop it.
        picker = f'<input type="hidden" name="player" value="{e(player)}">"'[:-1]

    rows = []
    for group in groups:
        key, chips = group[0], group[1]
        title = group[2] if len(group) > 2 else ""
        current = params.get(key) or ""
        row = []
        for value, label in chips:
            on = ' class="on"' if current == value else ""
            row.append(f'<a{on} href="{e(href(**{key: value}))}" data-keep>'
                       f'{label}</a>')
        # The label and its chips are one unit, so a wrap never strands a
        # label at the end of the row above its own buttons.
        rows.append('<span class="sep"></span><span class="filter-group">'
                    + (f'<span class="filter-label">{e(title)}</span>' if title else "")
                    + "".join(row) + "</span>")

    # A specific date keeps the day chips honest: none lights up, the picker does.
    # `iso` is the normalised form, resolved by the caller — parse_day accepts
    # `16/9`, which <input type="date"> silently drops, leaving the picker blank
    # on a view that is in fact filtered.
    picked = iso if day and day not in dict(DAY_CHIPS) else ""
    # Whatever else is filtering rides along, so changing the player keeps it.
    hidden = "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">'
                     for k, v in carried.items() if k not in ("player", "day"))
    # The search takes the first row on its own; the date belongs with the
    # chips, because picking a day is the same job as pressing "Today".
    date = (f'<span class="filter-group filter-date">'
            f'<input type="date" name="day" aria-label="Day" value="{e(picked)}">'
            "</span>")
    top = f'<div class="filters-top">{search}{picker}</div>' if search or picker else ""
    return (
        '<form id="filters" class="filters" method="get" action="">'
        + top + hidden
        + f'<div class="filters-chips">{date}{"".join(rows)}</div>'
        + '<noscript><button type="submit">Go</button></noscript>'
        "</form>")


# --- search -----------------------------------------------------------------

def search_box(value="", placeholder="Search players", label="Search",
               target="", item="", name="q", empty_text="Nothing by that name.",
               standalone=True):
    """A search field that works twice.

    With no script it submits and the server does the filtering. With script,
    `target` and `item` turn it into an instant filter over what is already on
    the page — the rows carry their own searchable text, so nothing is fetched
    to answer a keystroke.

    `standalone=False` drops the surrounding form, for a field that lives inside
    another one: a form inside a form is invalid, and the browser quietly throws
    the inner one away along with everything after it.
    """
    data = ""
    if target and item:
        data = f' data-filter="{e(target)}" data-filter-item="{e(item)}"'
    # The magnifier is the button, not a decoration: it says what the field is
    # and it submits, which is what a reader expects it to do when they press it.
    inner = (
        f'<button class="search-icon" type="submit" aria-label="{e(label)}">'
        f'{icons.search()}</button>'
        f'<input type="search" name="{e(name)}" value="{e(value)}" '
        f'placeholder="{e(placeholder)}" aria-label="{e(label)}" '
        f'autocomplete="off" spellcheck="false"{data}>'
        + f'<p class="search-empty" hidden>{e(empty_text)}</p>')
    if standalone:
        return (f'<form class="search" method="get" action="" role="search">'
                + inner + "</form>")
    return f'<div class="search" role="search">{inner}</div>'


def searchable(text):
    """The attribute an instant-filtered row carries. Lowercased here so the
    script can compare without doing the work on every keystroke."""
    return f' data-search="{e(str(text).lower())}"'


def rating_chart_pair(series):
    """Two rating lines on one pair of axes.

    Scaled together, never separately: the point of putting them on the same
    chart is that the distance between the lines is the distance between the
    players. A player with fewer matches starts further along the axis rather
    than being stretched to fill it, so the two are read against the same run
    of matches.
    """
    drawable = [(label, points) for label, points in series if len(points) > 1]
    if not drawable:
        return ""
    values = [rating for _, points in drawable for _, rating in points]
    low, high = min(values), max(values)
    span = max(high - low, 1)
    longest = max(len(points) for _, points in drawable)
    inner_w, inner_h = CHART_W - CHART_PAD * 2, CHART_H - CHART_PAD * 2
    step = inner_w / float(max(longest - 1, 1))

    lines = []
    for index, (label, points) in enumerate(series):
        if len(points) < 2:
            continue
        # Right-aligned: both lines end at "now", which is the only moment the
        # two players actually share.
        offset = longest - len(points)
        drawn = []
        for i, (_, rating) in enumerate(points):
            x = CHART_PAD + (i + offset) * step
            y = CHART_PAD + inner_h * (1 - (rating - low) / float(span))
            drawn.append(f"{x:.1f},{y:.1f}")
        last = drawn[-1].split(",")
        lines.append(
            f'<polyline class="chart-line l{index}" points="{" ".join(drawn)}"/>'
            f'<line class="chart-dot l{index}" x1="{last[0]}" y1="{last[1]}" '
            f'x2="{last[0]}" y2="{last[1]}"/>')
    said = "; ".join(f"{label} from {points[0][1]} to {points[-1][1]}"
                     for label, points in drawable)
    return (
        '<figure class="chart chart-pair">'
        f'<svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none" '
        f'role="img" aria-label="Ratings over the matches on record: {e(said)}">'
        + "".join(lines) +
        "</svg>"
        f'<figcaption class="chart-scale"><span class="num">{high}</span>'
        f'<span class="num">{low}</span></figcaption></figure>')


# --- comparing --------------------------------------------------------------

# Four columns is what a laptop reads and a phone can still scroll. Past that
# the table stops being a comparison and becomes a spreadsheet.
COMPARE_MAX = 4


def compare_toggle(on, href):
    """The switch that turns the players grid into something you pick from."""
    label = "Done comparing" if on else "Compare players"
    return (f'<a class="btn compare-toggle{" on" if on else ""}" href="{e(href)}" '
            f'data-keep aria-pressed="{"true" if on else "false"}">'
            f'{icons.swap()}{e(label)}</a>')


def compare_tray(names, chosen=(), view="", slots=0):
    """Pick the players, then compare them.

    A plain GET form: with no script it lands on /compare, and with script the
    same submission is shown in a dialog without leaving the page. The pickers
    past the ones in use are rendered but hidden, so the + reveals one instantly
    rather than asking the server for a wider form.
    """
    chosen = [uid for uid in chosen if uid][:COMPARE_MAX]
    shown = max(len(chosen) + (1 if len(chosen) < COMPARE_MAX else 0), max(slots, 2))
    options = sorted(names.items(), key=lambda i: str(i[1]).lower())

    pickers = []
    for index in range(COMPARE_MAX):
        picked = chosen[index] if index < len(chosen) else ""
        live = index < shown
        marks = "" if live else " hidden disabled"
        choices = ['<option value="">Player</option>']
        for uid, _ in options:
            sel = " selected" if uid == picked else ""
            choices.append(f'<option value="{e(uid)}"{sel}>'
                           f'{e(display_name(uid, names))}</option>')
        pickers.append(f'<select class="cmp-pick" name="p" aria-label="Player '
                       f'{index + 1}"{marks}>' + "".join(choices) + "</select>")

    add = ('<button class="cmp-add" type="button" data-add-slot '
           f'aria-label="Add another player" title="Add another player">'
           f'{icons.plus()}</button>')
    view_field = f'<input type="hidden" name="view" value="{e(view)}">' if view else ""
    return ('<form class="compare-bar" method="get" action="/compare" '
            'data-dialog="#compare-dialog">'
            '<span class="filter-label">Compare</span>'
            + "".join(pickers) + add + view_field
            + '<button class="btn btn-primary" type="submit">Compare</button>'
            '<p class="cmp-hint">Pick players here or tap their cards. '
            f'Up to {COMPARE_MAX}.</p>'
            "</form>")


def compare_dialog():
    """Where a comparison appears without leaving the page. Empty until asked
    for, and a plain <dialog>, so Esc and the backdrop behave as people expect."""
    return ('<dialog id="compare-dialog" class="dialog" aria-label="Comparison">'
            '<div class="dialog-bar"><a class="dialog-open" href="/compare" '
            'data-dialog-open>Open full page</a>'
            '<button class="dialog-close" type="button" data-dialog-close '
            'aria-label="Close">&#10005;</button></div>'
            '<div class="dialog-body" tabindex="-1"></div></dialog>')


def head_to_head_grid(uids, history, names, view=""):
    """Who has beaten whom, for three or more players.

    Each cell is that row's record against that column — wins first, the way a
    record is read. A pair who have never met get a dash rather than 0-0, which
    would say they played and drew nothing.
    """
    ladder = view or derive.OVERALL
    met = False
    head = "".join(f'<th scope="col">{e(display_name(uid, names))}</th>'
                   for uid in uids)
    rows = []
    for one in uids:
        cells = []
        for two in uids:
            if one == two:
                cells.append('<td class="cmp-self" aria-hidden="true">&#183;</td>')
                continue
            h2h = derive.head_to_head(history, one, two, ladder)
            if not h2h:
                cells.append('<td class="cmp-none">&#8212;'
                             '<span class="sr-only">never met</span></td>')
                continue
            met = True
            wins, losses = h2h["wins"][one], h2h["wins"][two]
            lead = " leads" if wins > losses else ""
            cells.append(f'<td class="cmp-cell{lead}"><span class="num">{wins}'
                         f'&#8211;{losses}</span>'
                         + (f'<span class="cmp-drawn">{h2h["draws"]}D</span>'
                            if h2h["draws"] else "") + "</td>")
        rows.append(f'<tr><th scope="row">{e(display_name(one, names))}</th>'
                    + "".join(cells) + "</tr>")
    if not met:
        return ""
    return ('<div class="cmp-scroll"><table class="cmp-table cmp-grid">'
            '<caption class="sr-only">Wins each way, row against column</caption>'
            f'<thead><tr><td></td>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')
