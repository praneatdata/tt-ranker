"""
HTTP Events API entry point — Vercel serverless function.

vercel.json rewrites every path to /api/index/<original-path>, so this one
function serves all routes. Vercel's platform may deliver the WSGI PATH_INFO as
the original path ('/slack/events') or as the rewrite destination with the
original appended ('/api/index/slack/events'); we route on the path *suffix* so
it works either way.

Requires SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET and the KV_REST_API_* pair in the
Vercel project's environment variables.
"""
import logging
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request

log = logging.getLogger("tt-ranker")
app = Flask(__name__)

# Initialize guarded, so a misconfiguration (missing env var, import problem)
# surfaces as a readable error instead of an opaque FUNCTION_INVOCATION_FAILED.
_init_error = None
try:
    # NB: must not be named `handler` — Vercel's Python runtime treats a
    # module-level `handler` as a BaseHTTPRequestHandler class.
    from slack_bolt.adapter.flask import SlackRequestHandler

    from bot import build_app

    bolt_app = build_app(process_before_response=True, token_verification=False)
    slack_request_handler = SlackRequestHandler(bolt_app)
except Exception:
    _init_error = traceback.format_exc()


def _debug_payload(observed_path):
    """Self-checks: what's configured and what broke. Never exposes secrets."""
    import kv
    import standings
    import store

    required = ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "KV_REST_API_URL",
                "KV_REST_API_TOKEN", "CRON_SECRET", "TT_CHANNEL", "TT_ADMINS")
    payload = {
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA", "unknown")[:7],
        # Which deployment answered, and which env's variables it was built with.
        # An env var only reaches a *new* deployment, so "I set it and it's still
        # false" is nearly always an old deployment still serving — without these
        # two fields that is indistinguishable from the variable being wrong.
        "deployment": os.environ.get("VERCEL_DEPLOYMENT_ID", "local"),
        "vercel_env": os.environ.get("VERCEL_ENV", "local"),
        "python": sys.version.split()[0],
        "observed_path": observed_path,  # what Vercel actually handed Flask
        "env": {name: bool(os.environ.get(name)) for name in required},
        "kv_configured": kv.kv_available(),
        "init_ok": _init_error is None,
        "init_error": _init_error,
    }
    if kv.kv_available() and request.args.get("ladder"):
        # Read-only snapshot: tells "the cron never ran" apart from "it ran and
        # the post failed", which look identical from outside.
        week_key, label = standings.previous_week()
        players = store.all_players()
        payload["ladder"] = {
            "players": len(players),
            "pending": len(store.list_pending()),
            "due_week": week_key,
            "label": label,
            "already_announced": week_key in set(kv.smembers(standings.POSTED_KEY) or []),
            "invocations": standings.invocation_log(),
        }
    return payload


def _authorized():
    """CRON_SECRET must match when it is set. Both cron endpoints are safe to
    call twice — the weekly post claims its week and the sweep claims each match
    — so an unauthenticated hit is at worst a no-op, never a duplicate."""
    secret = os.environ.get("CRON_SECRET")
    return not secret or request.headers.get("Authorization") == f"Bearer {secret}"


def _run_cron(fn):
    """Shared wrapper for /cron/*: record the call, check the secret, run."""
    if _init_error:
        return {"error": "app failed to initialize; see GET /"}, 500
    import standings
    authorized = _authorized()
    # Recorded before the auth check, so a scheduler call that was rejected is
    # still visible rather than looking like it never happened.
    standings.record_invocation(request.headers.get("User-Agent"), authorized)
    if not authorized:
        return {"error": "unauthorized"}, 401
    try:
        dry = request.args.get("dry") in ("1", "true", "yes")
        return fn(standings, bolt_app.client, dry)
    except Exception:
        log.exception("cron failed")
        return {"error": traceback.format_exc().splitlines()[-1]}, 500


# How far back the page reads to work out form, streaks and weekly movement.
# One pipelined round trip, and comfortably more than a week of an office
# ladder — the figures derived from it say "this week" and "last five", so a
# longer window would change nothing but the bill.
HISTORY_WINDOW = 120


def _filtered_matches(players, history=()):
    """The match list the query string asks for: `?player=<uid>&day=today`,
    either or both. Returns (matches, filters-for-the-page).

    Both parameters are validated before they go anywhere — the player has to
    be on the ladder and the day has to parse — so the page never echoes a
    stranger's input, and a bad link degrades to the unfiltered list.

    Unfiltered, the list is the head of the history window the page has already
    fetched, so the common case costs no extra round trip.
    """
    import page
    import parsing
    import store

    player = request.args.get("player", "")
    if player not in players:
        player = ""
    day = request.args.get("day", "")
    window = parsing.parse_day(day, store.now_ist()) if day else None
    if not window:
        day = ""

    if window:
        label, start, end = window
        recent = store.matches_in(start, end, uid=player or None)
        return recent, {"player": player, "day": day, "label": label,
                        "iso": parsing.iso_day(day, store.now_ist())}
    if player:
        return store.recent_matches(limit=page.FILTERED_SHOWN, uid=player), \
            {"player": player, "day": "", "label": ""}
    if history:
        return list(history[:page.RECENT_SHOWN]), {}
    return store.recent_matches(limit=page.RECENT_SHOWN), {}


HTML = {"Content-Type": "text/html; charset=utf-8"}
# Long enough that a channel-wide click isn't a thundering herd, short enough
# that the page still reads as live.
CACHE = dict(HTML, **{"Cache-Control": "public, max-age=15, stale-while-revalidate=60"})


def _view():
    """Which format tab is being asked for. ?view=singles predates singles
    becoming the default; it folds onto "" so links already pasted into the
    channel keep working and light the right tab."""
    import page
    view = request.args.get("view", "")
    return "" if view == "singles" or view not in dict(page.VIEWS) else view


def _placement(view):
    import bot
    return {"": bot.SINGLES_PLACEMENT_GAMES,
            "doubles": bot.DOUBLES_PLACEMENT_GAMES,
            "overall": bot.PLACEMENT_GAMES}[view]


def _for_view(players, view):
    """The record set a tab ranks on — singles views for singles, and so on."""
    import store
    return {"": store.singles_players,
            "doubles": store.doubles_players}.get(view, lambda p: p)(players)


def _common():
    """What every page wants: the players, the names, and how fresh this is."""
    import bot
    import store
    try:
        # Opportunistic and best-effort: if users:read isn't granted this is a
        # no-op and pages fall back to names slash commands have revealed.
        if _init_error is None:
            bot.refresh_names(bolt_app.client, logger=log)
    except Exception:
        log.exception("name refresh failed; rendering with what we have")
    return {"players": store.all_players(), "names": store.names(),
            "channel_hint": os.environ.get("TT_CHANNEL_NAME", ""),
            "updated": store.now_ist().strftime("%H:%M IST"),
            "log_href": _log_href()}


def _titles():
    """Who is wearing what — awards.by_player()'s map, off the cached table.

    Never fatal. A page without its chips is still the page, and a title is not
    worth a 500.
    """
    try:
        import awards
        return awards.by_player(awards.current())
    except Exception:
        log.exception("titles unavailable; rendering without them")
        return {}


def _log_href():
    """Where "Log match" goes. The page can't record a result — see
    web/pages/log.py — so it points at the page that explains how."""
    return "/log"


def _render_matches():
    """Every match, filtered by the query string and grouped by day."""
    import parsing
    import store
    from web.pages import matches as page_matches

    common = _common()
    players = common.pop("players")
    player = request.args.get("player", "")
    if player not in players:
        player = ""
    fmt = request.args.get("format", "")
    if fmt not in ("singles", "doubles"):
        fmt = ""
    # Free text, so it is length-capped here and escaped wherever it is echoed.
    # It never reaches the database — only the list on its way out.
    query = (request.args.get("q", "") or "").strip()[:40]
    day = request.args.get("day", "")
    window = parsing.parse_day(day, store.now_ist()) if day else None
    if not window:
        day = ""

    if window:
        label, start, end = window
        found = store.matches_in(start, end, uid=player or None)
    elif player:
        found = store.recent_matches(limit=HISTORY_WINDOW, uid=player)
    else:
        found = store.recent_matches(limit=HISTORY_WINDOW)
    if fmt:
        found = [b for b in found if bool(b.get("doubles")) == (fmt == "doubles")]
    if query:
        want, names = query.lower(), common["names"]
        found = [b for b in found
                 if any(want in page_matches.c.display_name(uid, names).lower()
                        for uid in tuple(b.get("side_a", ()))
                        + tuple(b.get("side_b", ())))]

    params = {"player": player, "day": day, "format": fmt, "q": query,
              "label": window[0] if window else ""}
    body = page_matches.render(
        found, players, params=params,
        iso=parsing.iso_day(day, store.now_ist()) if day else "",
        now=store.now_ist(),
        total=store.match_count() if not (player or day or fmt or query) else None,
        titles=_titles(), **common)
    return body, 200, CACHE


def _render_players():
    """The whole league as cards, ranked the way the board ranks them."""
    import store
    from web.pages import players as page_players

    common = _common()
    players = common.pop("players")
    view = _view()
    week_delta, week_played = store.week_movement()
    body = page_players.render(
        _for_view(players, view), history=store.recent_matches(limit=HISTORY_WINDOW),
        week=store.week_key(), view=view, placement_games=_placement(view),
        week_delta=week_delta, week_played=week_played,
        query=(request.args.get("q", "") or "").strip()[:40],
        comparing=request.args.get("compare") == "1",
        compare=_picked(_for_view(players, view)),
        slots=_slots(), titles=_titles(), **common)
    return body, 200, CACHE


def _slots():
    """How many pickers the compare tray opens with. Only ever grows the form,
    and only within the ceiling the components define."""
    from web import components
    try:
        asked = int(request.args.get("slots", 0))
    except ValueError:
        asked = 0
    return max(0, min(asked, components.COMPARE_MAX))


def _render_profile(uid):
    """One player. An unknown id is a 404 rather than an empty card."""
    import elo
    import store
    from web.pages import errors
    from web.pages import profile as page_profile

    common = _common()
    players = common.pop("players")
    if uid not in players:
        return errors.not_found("player"), 404, HTML

    view = _view()
    shown = _for_view(players, view)
    placement = _placement(view)
    ranked = sorted(((u, p) for u, p in shown.items()
                     if elo.games_played(p) >= placement),
                    key=lambda i: (-i[1]["rating"], -elo.games_played(i[1]), i[0]))
    rank = next((i for i, (u, _) in enumerate(ranked, 1) if u == uid), None)

    history = store.recent_matches(limit=HISTORY_WINDOW, uid=uid)
    week = store.week_key()
    if view == "overall":
        week_delta, week_played = store.week_movement()
        delta, played = week_delta.get(uid, 0), week_played.get(uid, 0)
        known = True
    else:
        from web import derive
        delta_map, played_map = derive.weekly(history, view, week)
        delta, played = delta_map.get(uid, 0), played_map.get(uid, 0)
        known = bool(history)

    versus = request.args.get("vs", "")
    if versus not in players:
        versus = ""
    body = page_profile.render(
        uid, shown[uid], shown, history=history, week=week, view=view,
        placement_games=placement, rank=rank, delta=delta, played=played,
        known=known, versus=versus, titles=_titles(), now=store.now_ist(),
        **common)
    return body, 200, CACHE


def _picked(known):
    """Which players a request is asking to compare, in the order given.

    `?p=` repeated is the form the pickers submit; `?a=&b=` is what the first
    version of this page used and what may already be pasted in the channel.
    Unknown ids and repeats drop out rather than being guessed at.
    """
    from web import components
    asked = request.args.getlist("p") or [request.args.get("a", ""),
                                          request.args.get("b", "")]
    out = []
    for uid in asked:
        if uid in known and uid not in out:
            out.append(uid)
    return out[:components.COMPARE_MAX]


def _render_compare():
    """Two to four players side by side. Fewer than two known ids leaves the
    pickers up rather than guessing who was meant."""
    import elo
    import store
    from web.pages import compare as page_compare

    common = _common()
    players = common.pop("players")
    view = _view()
    shown = _for_view(players, view)
    uids = _picked(shown)

    ranked = sorted(((u, p) for u, p in shown.items()
                     if elo.games_played(p) >= _placement(view)),
                    key=lambda i: (-i[1]["rating"], -elo.games_played(i[1]), i[0]))
    ranks = {uid: i for i, (uid, _) in enumerate(ranked, 1)}

    history = []
    if len(uids) > 1:
        # Every player's history, merged: a match between two of them appears in
        # both, and the rating lines need the matches only one of them played.
        seen = set()
        for uid in uids:
            for blob in store.recent_matches(limit=HISTORY_WINDOW, uid=uid):
                if blob["id"] not in seen:
                    seen.add(blob["id"])
                    history.append(blob)
        history.sort(key=lambda blob: blob.get("applied_at", ""), reverse=True)

    # `?bare=1` is the popup asking for the comparison without the page around
    # it; it is the same render either way, so the two can never disagree.
    bare = request.args.get("bare") == "1"
    body = page_compare.render(uids, shown, history=history, view=view,
                               ranks=ranks, bare=bare, titles=_titles(),
                               **common)
    return body, 200, (HTML if bare else CACHE)


def _render_shame():
    """The wall of shame. Reads two hashes and nothing else."""
    import shame
    from web.pages import shame as page_shame

    common = _common()
    common.pop("players")
    return page_shame.render(shame.board(limit=SHAME_SHOWN), view=_view(),
                             **common), 200, CACHE


SHAME_SHOWN = 15


def _render_titles():
    """Every title, and who is holding it."""
    import awards
    from web.pages import titles as page_titles

    common = _common()
    players = common.pop("players")
    return page_titles.render(awards.current(), players, view=_view(), **common), \
        200, CACHE


def _render_releases():
    """What's changed. Needs no database — the notes ship with the code."""
    from web.pages import releases as page_releases

    import store
    return page_releases.render(
        log_href=_log_href(),
        channel_hint=os.environ.get("TT_CHANNEL_NAME", ""),
        updated=store.now_ist().strftime("%H:%M IST")), 200, CACHE


def _render_stats():
    """The numbers, over as much history as the ladder keeps."""
    import store
    from web.pages import stats as page_stats

    common = _common()
    players = common.pop("players")
    body = page_stats.render(
        players, history=store.recent_matches(limit=HISTORY_WINDOW),
        week=store.week_key(), window=HISTORY_WINDOW, view=_view(), **common)
    return body, 200, CACHE


def _render_log():
    """How to log a match — the one page that needs no database at all."""
    from web.pages import log as page_log
    return page_log.render(channel_hint=os.environ.get("TT_CHANNEL_NAME", ""),
                           log_href=""), 200, HTML


def _render_ladder():
    """The public ladder page — the link that goes in the channel topic.

    Read-only and unauthenticated by design: it holds display names and ratings,
    nothing that isn't already visible to anyone in the Slack channel.
    """
    import betting
    import bot
    import page
    import store

    common = _common()
    players = common.pop("players")
    # The one extra read the redesign asks for: recent matches, which is where
    # form, streaks and per-format weekly movement come from. Read-only, and the
    # ratings in it are the ones already stored — nothing is re-rated here.
    history = store.recent_matches(limit=HISTORY_WINDOW)
    view = _view()
    # Spins are won on fixtures rather than on a ladder, so the board they sit
    # on is switched separately from the format tabs.
    board = "spins" if request.args.get("board") == "spins" else ""
    week_delta, week_played = store.week_movement()
    recent, filters = _filtered_matches(players, history)
    body = page.render(
        players=_for_view(players, view),
        recent=recent,
        week_delta=week_delta,
        week_played=week_played,
        filters=filters,
        placement_games=_placement(view),
        view=view,
        spins=betting.standings(players),
        start_spins=betting.START_SPINS,
        circulating=betting.circulating(players),
        history=history,
        match_count=store.match_count(),
        week=store.week_key(),
        board=board,
        titles=_titles(),
        **common,
    )
    return body, 200, CACHE


@app.route("/", defaults={"subpath": ""}, methods=["GET", "POST"])
@app.route("/<path:subpath>", methods=["GET", "POST"])
def route(subpath):
    tail = "/" + subpath  # e.g. "/slack/events" or "/api/index/slack/events"

    if request.method == "POST" and tail.endswith("/slack/events"):
        if _init_error:
            return {"error": "app failed to initialize; see GET /"}, 500
        # Slack retries an event when our first response misses its 3s ack
        # deadline (common on serverless cold starts). That first invocation
        # still runs to completion, so ack retried *event* deliveries without
        # reprocessing. Slash commands and button presses are not retried this
        # way, and url_verification is a setup handshake — never skip those.
        if request.headers.get("X-Slack-Retry-Num"):
            body = request.get_json(silent=True) or {}
            if body.get("type") == "event_callback":
                log.info("Skipping Slack retry #%s (reason: %s)",
                         request.headers.get("X-Slack-Retry-Num"),
                         request.headers.get("X-Slack-Retry-Reason"))
                return "", 200
        return slack_request_handler.handle(request)

    # Both cron jobs pay the stipend. It is claimed once per week, so whichever
    # fires first that week hands it out and the other is a no-op — nobody goes
    # unpaid because one scheduled job was skipped.
    if tail.endswith("/cron/standings"):
        return _run_cron(lambda s, client, dry: {
            **s.post_weekly(client, dry_run=dry),
            "stipend": s.pay_due_stipend(dry_run=dry)})

    if tail.endswith("/cron/sweep"):
        return _run_cron(lambda s, client, dry: {
            **s.sweep_pending(client, dry_run=dry),
            "fixtures": s.sweep_fixtures(client, dry_run=dry),
            "challenges": s.sweep_challenges(client, dry_run=dry),
            "stipend": s.pay_due_stipend(dry_run=dry)})

    if tail.endswith("/debug"):
        return _debug_payload(tail)

    # The mark, and the favicon browsers ask for without being told to. Served
    # before the page lookup and before any database check: an image has no
    # business 503-ing because the KV credentials are missing.
    from web import brand
    found = brand.asset(tail)
    if found:
        body, content_type = found
        return body, 200, {"Content-Type": content_type,
                           "Cache-Control": brand.CACHE}

    page_view = _page_for(tail)
    if page_view:
        import kv
        from web.pages import errors
        # Every page but /log needs the database; say so once, in words, rather
        # than letting each page render an empty shell.
        if page_view not in (_render_log, _render_releases) \
                and not kv.kv_available():
            return errors.no_database(), 503, HTML
        try:
            return page_view()
        except Exception:
            log.exception("page failed to render")
            detail = traceback.format_exc().splitlines()[-1] if _debug_on() else ""
            return errors.broken(detail), 500, HTML

    if _init_error:
        return f"<pre>init failed:\n\n{_init_error}</pre>", 500
    if tail.rstrip("/").endswith("/api/index") or tail in ("/", ""):
        return "TT Ranker is running."
    from web.pages import errors
    return errors.not_found(), 404, HTML


# Vercel may hand Flask the original path or the rewrite destination with the
# original appended, so every route is matched on the tail of the path.
# Mapped to the functions themselves, not to wrappers: the no-database check
# below asks whether this page is _render_log, and a lambda never is.
PAGES = {"ladder": _render_ladder, "matches": _render_matches,
         "players": _render_players, "stats": _render_stats, "log": _render_log,
         "compare": _render_compare, "titles": _render_titles,
         "shame": _render_shame,
         "releases": _render_releases}


def _page_for(tail):
    """Which page a path asks for, or None. `/player/<uid>` carries its id in
    the path, so it is matched on the segment before the last."""
    parts = [part for part in tail.split("/") if part]
    if not parts:
        return None
    if len(parts) >= 2 and parts[-2] == "player":
        uid = parts[-1]
        return lambda: _render_profile(uid)
    return PAGES.get(parts[-1])


def _debug_on():
    """Whether an error page may carry its exception line. On by default
    nowhere: a public page shows a reader what broke only when asked."""
    return os.environ.get("TT_SHOW_ERRORS") in ("1", "true", "yes")
