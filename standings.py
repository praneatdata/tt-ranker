"""
The weekly standings post, and the sweep that ages unconfirmed matches in.

Both run from Vercel Cron (see vercel.json). Neither scans history: the weekly
movement numbers are incremented as matches are confirmed, the same trick
pr-raiser uses for its PR counts, because a scan grows every week and would
eventually outlive the serverless timeout.

Posting is idempotent per week — a retry, or a stray request to the endpoint,
can at worst re-run a week that was already announced, which is a no-op.
"""
import os
from datetime import datetime, timedelta

import bot
import kv
import store

CHANNEL = os.environ.get("TT_CHANNEL", "")
POSTED_KEY = "tt:standings:posted"
# Who last called the cron endpoint. Vercel has been known to silently skip a
# scheduled invocation; recording each hit means one request answers "did the
# scheduler actually fire?" without digging through the log UI.
CALLS_KEY = "tt:standings:calls"


def record_invocation(user_agent, authorized=True, now=None):
    """Note that a cron endpoint was called. Never raises — diagnostics must not
    break the run they measure."""
    ua = (user_agent or "unknown")[:120]
    kind = "cron" if "vercel-cron" in ua.lower() else "other"
    fields = {f"last_{kind}_at": store.stamp(now), f"last_{kind}_ua": ua}
    if not authorized:
        fields["last_denied_at"] = store.stamp(now)
    try:
        kv.hset_many(CALLS_KEY, fields)
        kv.hincrby(CALLS_KEY, f"{kind}_count", 1)
    except Exception:
        pass


def invocation_log():
    try:
        return kv.hgetall(CALLS_KEY) or {}
    except Exception:
        return {}


def previous_week(now=None):
    """(week_key, "1–7 Sep") for the week before `now` — what a Monday run reports."""
    now = (now or store.now_ist()).astimezone(store.IST)
    last = now - timedelta(days=7)
    year, week, _ = last.isocalendar()
    monday = datetime.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6)
    span = (f"{monday.day}–{sunday.day} {sunday:%b}" if monday.month == sunday.month
            else f"{monday.day} {monday:%b} – {sunday.day} {sunday:%b}")
    return store.week_key(last), span


def build_message(week_key, label):
    """The weekly post, or None if nothing happened that week."""
    delta, played = store.week_movement(week_key)
    if not played:
        return None

    players = store.all_players()
    lines = [bot.board_text(players, title=f"Table tennis ladder · week of {label}"), ""]

    matches = sum(played.values())
    # Each match is counted once per player, so 2 players (or 4) share one match.
    lines.append(f":bar_chart: *{matches}* player-match{'es' if matches != 1 else ''} "
                 f"across *{len(played)}* player{'s' if len(played) != 1 else ''} this week.")

    movers = sorted(delta.items(), key=lambda item: -item[1])
    risers = [(u, d) for u, d in movers if d > 0][:3]
    faller = next(((u, d) for u, d in reversed(movers) if d < 0), None)
    if risers:
        lines.append(":chart_with_upwards_trend: *Climbers* — "
                     + " · ".join(f"<@{u}> `{bot.fmt_delta(d)}`" for u, d in risers))
    if faller:
        lines.append(f":chart_with_downwards_trend: Toughest week — <@{faller[0]}> "
                     f"`{bot.fmt_delta(faller[1])}`. Rematch?")
    lines.append("\n_`/tt log @opponent 11-7 9-11 11-5` to add a result · `/tt help` for the rest._")
    return "\n".join(lines)


def post_weekly(client, now=None, channel=None, force=False, dry_run=False):
    """Post last week's standings. A week is announced once, so a cron retry
    can't repeat it. Returns a status dict.

    dry_run renders the message and reports what would happen without posting or
    consuming the week — for checking the endpoint is healthy.
    """
    week_key, label = previous_week(now)
    target = channel or CHANNEL
    if dry_run:
        text = build_message(week_key, label)
        return {"status": "dry_run", "week": week_key, "channel": target,
                "would_post": bool(text and target), "preview": text}
    if not target:
        return {"status": "no_channel", "detail": "set TT_CHANNEL to the channel id"}
    if not force and kv.sadd(POSTED_KEY, week_key) != 1:
        return {"status": "already_posted", "week": week_key}
    text = build_message(week_key, label)
    if not text:
        kv.srem(POSTED_KEY, week_key)  # nothing happened; let a later run try
        return {"status": "no_activity", "week": week_key}
    resp = client.chat_postMessage(channel=target, text=text)
    return {"status": "posted", "week": week_key, "ts": resp["ts"],
            "channel": resp["channel"]}


def pay_due_stipend(now=None, dry_run=False):
    """Hand out the week's spins.

    Deliberately not part of the weekly standings post, which is where this
    lived and never ran: that function returns early when the week was quiet,
    when TT_CHANNEL is unset and when the post already went out, so a week with
    no matches paid nobody — which is precisely the week people need spins to
    get playing again.

    Called from every cron instead. The per-week claim inside pay_stipend makes
    that safe: whichever scheduled job fires first that week pays, the rest are
    no-ops, and nobody is left unpaid because one job was skipped.
    """
    import betting
    week = store.week_key(now)
    if betting.WEEKLY_STIPEND <= 0:
        return {"status": "disabled", "week": week}
    if dry_run:
        paid = week in set(kv.smembers(betting.STIPEND_KEY) or [])
        return {"status": "already_paid" if paid else "would_pay", "week": week}
    return betting.pay_stipend(now=now)


def sweep_pending(client, now=None, dry_run=False, logger=None):
    """Apply matches nobody confirmed or disputed in time.

    Without this, one player forgetting to press a button quietly freezes a
    result forever. Silence past the window is taken as agreement — the losing
    side had a day and a button to say otherwise.

    Cron granularity means the real wait is between AUTO_CONFIRM_HOURS and that
    plus a day; the message says "auto-confirms in 24h", which is the promise
    that matters (it will never apply *sooner* than the window).
    """
    now = now or store.now_ist()
    applied, skipped = [], 0
    for record in store.list_pending():
        if not store.is_expired(record, now):
            skipped += 1
            continue
        if dry_run:
            applied.append(record["id"])
            continue
        if not store.claim_pending(record["id"]):
            continue  # someone confirmed it as we looked
        try:
            blob = store.apply_match(record, auto=True, now=now)
        except Exception:
            store.release_pending(record["id"])
            (logger or bot.log).exception("auto-confirm of %s failed", record["id"])
            continue
        applied.append(blob["id"])
        _update_original(client, blob, logger=logger)
        bot._pay_out(blob, client, logger=logger)
    return {"status": "dry_run" if dry_run else "swept",
            "applied": applied, "still_waiting": skipped}


def sweep_fixtures(client, now=None, dry_run=False, logger=None):
    """Shut betting on fixtures that have started, and refund ones whose result
    never arrived.

    Crons run daily, so this is the tidy-up, not the enforcement: place_bet
    closes an overdue window itself the moment anyone tries. Without the refund
    pass, a match nobody ever reports would hold people's stakes for good.
    """
    import betting
    now = now or store.now_ist()
    closed, voided = [], []
    for record in betting.live():
        if record.get("state") == "open" and betting.is_due(record, now):
            if not dry_run:
                betting.close_if_due(record, now)
                bot._refresh_fixture(record, client, now, logger=logger)
            closed.append(record["id"])
        # Not elif: one that is overdue *and* abandoned gets both in this pass.
        if betting.is_abandoned(record, now):
            if dry_run:
                voided.append(record["id"])
                continue
            if not betting.claim(record["id"]):
                continue
            refunded = betting.pool(record["id"])["total"]
            betting.void(record, "no result was ever logged", now)
            import shame
            shame.record_many(record["side_a"] + record["side_b"], "bailed")
            bot._refresh_with(record, client, [
                bot._section(f":no_entry_sign: ~{bot.fmt_side(record['side_a'])} vs "
                             f"{bot.fmt_side(record['side_b'])}~ — no result logged."),
                bot._context("Every stake refunded."
                             + (f" {bot.fmt_spins(refunded)} returned."
                                if refunded else "")),
            ], "Fixture abandoned.", logger=logger)
            voided.append(record["id"])
    return {"closed": closed, "refunded": voided}


def sweep_challenges(client, now=None, dry_run=False, logger=None):
    """Close challenges nobody answered.

    An invitation that stays open for a week isn't an invitation, it's clutter —
    and it blocks the same pair from issuing a fresh one, since only one can be
    open between two sides at a time.
    """
    import challenge
    now = now or store.now_ist()
    expired = []
    for record in challenge.live():
        if not challenge.is_expired(record, now):
            continue
        if dry_run:
            expired.append(record["id"])
            continue
        if not challenge.claim(record["id"]):
            continue
        challenge.expire(record, now)
        # Whoever was asked and never answered. An open call was addressed to
        # nobody in particular, so nobody ghosted it.
        if not challenge.is_open_call(record):
            import shame
            shame.record_many(record.get("side_b", ()), "ghosted")
        bot._close_challenge(record, client, now, logger=logger)
        expired.append(record["id"])
    return {"expired": expired}


def _update_original(client, blob, logger=None):
    """Replace every prompt with the outcome — the channel post and each verdict
    DM — so nothing keeps offering buttons for a session already rated."""
    if not client:
        return
    bot._settle_everywhere(client, blob, bot.applied_blocks(blob),
                           "Session auto-confirmed.", logger=logger)
