"""
TT Ranker — shared bot logic, host-agnostic.

Entry points:
  socket_mode.py — Socket Mode (local dev / Docker), no public URL needed.
  api/index.py   — HTTP Events API (Vercel serverless).

One slash command, `/tt`, with subcommands. Several slash commands would each
need their own manifest entry and their own Slack re-install every time one is
added; a single verb keeps the app definition stable and the help in one place.

A logged match does not move anybody's rating on its own — it waits for someone
on the other side to press Confirm (or for the daily sweep to age it in). See
store.py for why the rating maths happens at confirmation time rather than here.
"""
import json
import logging
import os
import ssl
from datetime import datetime, timedelta

from slack_bolt import App
from slack_sdk import WebClient

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("tt-ranker")

import awards
import betting
import elo
import kv
import challenge
import parsing
import rerate
import store

CONFIRM_ACTION = "tt_confirm"
DISPUTE_ACTION = "tt_dispute"

# The ladder's home channel: the weekly standings post lands here, and joining it
# puts you on the ladder. standings.py reads the same variable for its own copy.
HOME_CHANNEL = os.environ.get("TT_CHANNEL", "")

# Below this many *games* a rating says more about luck than about the player,
# so they sit in a "still placing" line instead of the ladder proper. Counted in
# games rather than sessions, because one session can be 2 games or 20.
#
# Set low on purpose. A 6-game rating is noisy, but an empty leaderboard in the
# first week is worse than a rough one — nobody keeps playing for a board that
# never shows them. Raise it once there is volume.
PLACEMENT_GAMES = 6
# Singles games are a subset of all games, so the same bar leaves the singles
# board empty while the overall one is full — the emptiest possible version of
# the leaderboard problem. Its own, lower, for the same reason: a rough board
# beats no board. Raise it once singles volume catches up.
SINGLES_PLACEMENT_GAMES = 4
DOUBLES_PLACEMENT_GAMES = 4
BOARD_LIMIT = 20
# Guard on /tt sync: a ladder is a room of people who play each other, and
# anything past this is someone running it in the wrong channel.
SYNC_LIMIT = 500
MEDALS = (":first_place_medal:", ":second_place_medal:", ":third_place_medal:")

NO_KV = (":warning: No database is configured, so I can't track ratings. "
         "Set `KV_REST_API_URL` and `KV_REST_API_TOKEN` and redeploy.")


# --- formatting ------------------------------------------------------------

def fmt_side(uids):
    return " & ".join(f"<@{u}>" for u in uids)


def fmt_side_rated(uids, players):
    """`@bob (1042)` — the names with what each of them is actually rated.

    A challenge is a claim about who is better, so the numbers being claimed
    about belong on it. Anyone with no record yet reads as the opening rating
    rather than being left blank: that *is* what they are rated.
    """
    parts = []
    for uid in uids:
        rating = (players.get(uid) or {}).get("rating", elo.START_RATING)
        parts.append(f"<@{uid}> `{rating}`")
    return " & ".join(parts)


def favourite_line(side_a, side_b, players):
    """One line on who the maths favours, from the ratings alone.

    The same expectation `/tt odds` reports, said at the moment people care
    about it most — when someone has just been called out.
    """
    entries = lambda side: [{"uid": u, "rating": (players.get(u) or {}).get(
        "rating", elo.START_RATING)} for u in side]
    a, b = elo.team_rating(entries(side_a)), elo.team_rating(entries(side_b))
    chance = elo.expected(a, b)
    if abs(a - b) < 15:
        return "Too close to call."
    favoured, pct = (side_a, chance) if chance > 0.5 else (side_b, 1 - chance)
    return f"{fmt_side(favoured)} favoured — {round(pct * 100)}% on the ratings."


def fmt_games(games):
    return "  ".join(f"`{a}-{b}`" for a, b in games)


def fmt_delta(d):
    return f"+{d}" if d > 0 else (str(d) if d < 0 else "±0")


def fmt_ago(iso, now=None):
    """"3h ago" — vague on purpose; nobody needs the seconds."""
    if not iso:
        return "never"
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return "a while ago"
    seconds = ((now or store.now_ist()) - then).total_seconds()
    for limit, div, unit in ((90, 1, "s"), (5400, 60, "m"), (172800, 3600, "h")):
        if seconds < limit:
            return f"{max(0, int(seconds // div))}{unit} ago"
    return f"{int(seconds // 86400)}d ago"


def fmt_streak(streak):
    if streak >= 3:
        return f":fire: {streak} wins"
    if streak > 0:
        return f"{streak} win{'s' if streak > 1 else ''}"
    if streak <= -3:
        return f":snowflake: {-streak} losses"
    if streak < 0:
        return f"{-streak} loss{'es' if streak < -1 else ''}"
    return "—"


def _section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def scoreline(record, games_a, games_b, settled):
    """"*<@a>* beat *<@b>* — *2–1*", or the neutral form while it's a claim."""
    a, b = fmt_side(record["side_a"]), fmt_side(record["side_b"])
    if not settled:
        return f":table_tennis_paddle_and_ball: *{a}*  {games_a}–{games_b}  *{b}*"
    if games_a == games_b:
        return f":table_tennis_paddle_and_ball: *{a}* drew with *{b}* — *{games_a}–{games_b}*"
    winner, loser = (a, b) if games_a > games_b else (b, a)
    high, low = max(games_a, games_b), min(games_a, games_b)
    return f":table_tennis_paddle_and_ball: *{winner}* beat *{loser}* — *{high}–{low}*"


def _button(action_id, text, mid, style=None):
    button = {"type": "button", "action_id": action_id, "value": mid,
              "text": {"type": "plain_text", "text": text}}
    if style:
        button["style"] = style
    return button


def pending_blocks(record):
    """What the *channel* sees while a session waits — the claim and who owes a
    verdict, with no buttons on it.

    The verdict itself goes out as a DM (see verdict_blocks). Buttons sitting in
    a channel invite everyone who can see them to press, and the ones who
    shouldn't only find out they can't after clicking; the people whose rating is
    actually at stake are the only ones who should be holding them at all.
    """
    games_a, games_b, _, _ = elo.tally(record["games"])
    who = confirmers(record)
    ask = (f"Sent to {fmt_side(who)} to confirm." if who else "Waiting on confirmation.")
    return [
        _section(f"{scoreline(record, games_a, games_b, settled=False)}\n"
                 f"{fmt_games(record['games'])}"),
        _context(f"Logged by <@{record['logged_by']}> · {ask} "
                 f"Applies on its own in {store.AUTO_CONFIRM_HOURS}h."),
    ]


def verdict_blocks(record, role):
    """The DM that actually carries the buttons, cut to what this person may do.

    role "confirm" is someone the result costs; "cancel" is the person who
    logged it, for whom the only useful action is taking it back.
    """
    games_a, games_b, _, _ = elo.tally(record["games"])
    mid = record["id"]
    if role == "confirm":
        head = (f"{scoreline(record, games_a, games_b, settled=False)}\n"
                f"{fmt_games(record['games'])}")
        note = (f"<@{record['logged_by']}> logged this. Is it right? "
                f"Nothing moves until you say so — or on its own in "
                f"{store.AUTO_CONFIRM_HOURS}h.")
        buttons = [_button(CONFIRM_ACTION, "✅  Confirm", mid, style="primary"),
                   _button(DISPUTE_ACTION, "❌  That's wrong", mid)]
    else:
        head = (f"{scoreline(record, games_a, games_b, settled=False)}\n"
                f"{fmt_games(record['games'])}")
        note = (f"Sent to {fmt_side(confirmers(record))} to confirm. "
                "Logged it by mistake? Take it back before they get to it.")
        buttons = [_button(DISPUTE_ACTION, "🗑  Cancel this", mid)]
    return [_section(head), _context(note),
            {"type": "actions", "block_id": f"tt_actions_{mid}", "elements": buttons}]


def verdict_audience(record):
    """{uid: role} — who gets a DM, and which buttons it carries.

    Kept deliberately small: every entry is one more API call inside Slack's
    3-second window. A partner of whoever logged it isn't messaged; they can see
    the channel post and ask.
    """
    who = {uid: "confirm" for uid in confirmers(record)}
    reporter = record.get("logged_by")
    if reporter and reporter not in who:
        who[reporter] = "cancel"
    return who


def applied_blocks(blob):
    """The settled match: who won, and what it cost everyone."""
    lines = [scoreline(blob, blob["games_a"], blob["games_b"], settled=True),
             fmt_games(blob["games"]), ""]
    for uid in blob["side_a"] + blob["side_b"]:
        before, after = blob["before"][uid], blob["after"][uid]
        lines.append(f"<@{uid}>  {before} → *{after}*  `{fmt_delta(blob['deltas'][uid])}`")

    if blob.get("admin"):
        how = f"recorded by <@{blob['confirmed_by']}> :shield:"
    elif blob.get("auto_confirmed"):
        how = "auto-confirmed — nobody objected"
    elif blob.get("confirmed_by"):
        how = f"confirmed by <@{blob['confirmed_by']}>"
    else:
        how = "confirmed"
    tail = f"Match `#{blob['id']}` · {how}"
    if blob.get("doubles"):
        tail += " · doubles"
    return [_section("\n".join(lines)), _context(tail)]


# --- who may confirm -------------------------------------------------------

def admins():
    """Slack ids allowed to record a result without anyone confirming it.

    Read from TT_ADMINS at call time rather than captured at import, so adding
    someone is an environment change instead of a code change. Comma- or
    space-separated: "U08V0KSE092, U02LJ0Z08KZ".
    """
    raw = os.environ.get("TT_ADMINS", "")
    return {u.strip() for u in raw.replace(",", " ").split() if u.strip()}


def is_admin(uid):
    return bool(uid) and uid in admins()


def confirmers(record):
    """Who can confirm: the side the reporter is *not* on.

    Confirmation is only worth anything if it comes from someone the result
    costs. A bystander logging someone else's match has no side, so then anyone
    who actually played can settle it.
    """
    a, b, logged_by = record["side_a"], record["side_b"], record["logged_by"]
    if logged_by in a:
        return list(b)
    if logged_by in b:
        return list(a)
    return list(a) + list(b)


def disputers(record):
    """Anyone involved can say it's wrong — including the reporter, for whom the
    button is really a cancel."""
    return list(dict.fromkeys(record["side_a"] + record["side_b"] + [record["logged_by"]]))


def may_confirm(record, uid):
    """Admins can settle anyone else's session — the only way to clear one whose
    players have gone quiet before the sweep gets to it.

    Not their own, though. "Nobody waves through a result they logged
    themselves" is the rule the whole thing rests on, and an admin is exactly
    who it would be least defensible to exempt. (Admin sessions skip the queue
    entirely anyway, so this only bites if someone was granted admin *after*
    logging something.)
    """
    if uid in confirmers(record):
        return True
    return is_admin(uid) and record.get("logged_by") != uid


def may_dispute(record, uid):
    """Throwing a result out costs nobody anything, so an admin may always."""
    return is_admin(uid) or uid in disputers(record)


# --- /tt log ---------------------------------------------------------------

def post_failure(e, channel="", bot_id=None):
    """Say what Slack actually refused, not what we assume it refused.

    This used to report "invite me there" for every exception, which is a guess
    dressed as a diagnosis — and useless when the real cause is a private
    channel, an archived one, or a malformed message. Slack names the reason;
    pass it on.
    """
    code = ""
    response = getattr(e, "response", None)
    if response is not None:
        try:
            code = response.get("error") or ""
        except Exception:
            code = ""
    where = f"<#{channel}>" if str(channel).startswith("C") else "that channel"
    invite = f" with `/invite <@{bot_id}>`" if bot_id else ""
    known = {
        "not_in_channel": f"I'm not in {where} — invite me there{invite}.",
        # Slack says "not found" rather than "forbidden" for a private channel
        # the bot isn't in, which is the single most confusing case here:
        # chat:write.public covers public channels only.
        "channel_not_found": (f"I can't see {where}. If it's a private channel I "
                              f"have to be invited{invite} — posting without an "
                              "invite only works in public ones."),
        "is_archived": f"{where} is archived.",
        "restricted_action": f"This workspace doesn't allow me to post in {where}.",
        "msg_too_long": "That message came out too long for Slack.",
        "invalid_blocks": "I built a message Slack rejected — that's my bug, not yours.",
    }
    if code in known:
        return f":warning: {known[code]}"
    if code:
        return f":warning: Slack wouldn't let me post in {where} — it said `{code}`."
    return f":warning: I couldn't post in {where}: {e}."


def submit_match(side_a, side_b, games, logged_by, channel, client, bot_id=None, logger=None):
    """Park a match and post its confirmation prompt. Returns None on success, or
    a message to relay to whoever logged it.

    Shared by the typed command and the guided form, so the two can't drift on
    what happens after a valid match is entered.
    """
    record = store.create_pending(side_a, side_b, games, logged_by=logged_by, channel=channel)
    if is_admin(logged_by):
        return _record_as_admin(record, logged_by, channel, client, bot_id, logger)
    try:
        # Posted rather than `respond`ed so a settlement hours later can still
        # edit it: a slash command's response_url expires after 30 minutes.
        resp = client.chat_postMessage(
            channel=channel, blocks=pending_blocks(record),
            text=f"Session logged by <@{logged_by}> — waiting on a verdict.")
    except Exception as e:
        # Almost always not_in_channel. Drop the pending rather than leave one
        # nobody can see, let alone settle.
        store.drop_pending(record["id"])
        (logger or log).warning("could not post pending session: %s", e)
        return post_failure(e, channel, bot_id) + " Then log it again."

    dms = _send_verdict_dms(record, client, logger=logger)
    store.attach_messages(record["id"], resp["channel"], resp["ts"], dms)
    if not any(role == "confirm" for uid, role in verdict_audience(record).items()
               if uid in dms):
        # Nobody who could confirm actually received the buttons. Say so rather
        # than let it look logged and then quietly sit there until the sweep.
        return (":warning: Logged, but I couldn't DM anyone to confirm it — they "
                f"may have DMs from apps turned off. It'll apply on its own in "
                f"{store.AUTO_CONFIRM_HOURS}h.")
    return None


def _send_verdict_dms(record, client, logger=None):
    """DM each person a verdict prompt. Returns {uid: [channel, ts]} for those
    that landed, so they can all be updated when the session settles."""
    dms = {}
    for uid, role in verdict_audience(record).items():
        try:
            resp = client.chat_postMessage(
                channel=uid, blocks=verdict_blocks(record, role),
                text=f"Table tennis session #{record['id']} needs your verdict.")
            dms[uid] = [resp["channel"], resp["ts"]]
        except Exception as e:
            # One unreachable person must not stop the others being asked.
            (logger or log).warning("verdict DM to %s failed: %s", uid, e)
    return dms


def _record_as_admin(record, admin, channel, client, bot_id=None, logger=None):
    """Rate an admin's session straight away, with no confirmation step.

    Rated before posting, not after: if the post fails the rating has still
    moved, which is recoverable and visible in `/tt history`. The other order
    would put a message in the channel announcing a change that never happened.

    The result still names who recorded it, so skipping the confirmation is
    visible to the channel rather than silent.
    """
    store.claim_pending(record["id"])
    try:
        blob = store.apply_match(record, confirmed_by=admin, admin=True)
    except Exception:
        store.drop_pending(record["id"])
        (logger or log).exception("admin apply of %s failed", record["id"])
        return ":x: Something went wrong rating that session — try again in a moment."
    _settle_bets(blob, client, logger=logger)
    try:
        client.chat_postMessage(channel=channel, blocks=applied_blocks(blob),
                                text=f"Session recorded by <@{admin}>.")
    except Exception as e:
        (logger or log).warning("could not post admin result: %s", e)
        invite = f" with `/invite <@{bot_id}>`" if bot_id else ""
        return (f":warning: Ratings updated, but I couldn't post the result in that "
                f"channel — invite me there{invite}. See `/tt history`.")
    return None


def handle_log(command, respond, client, bot_id, logger=None):
    caller = command.get("user_id")
    _, rest = parsing.split_subcommand(command.get("text", ""))

    if not rest.strip():
        # A bare `/tt log` (or `/tt form`) opens the guided form instead of
        # printing usage — clicking people beats getting the @mentions right.
        try:
            client.views_open(trigger_id=command["trigger_id"],
                              view=build_log_modal(caller, command.get("channel_id", "")))
        except Exception as e:
            (logger or log).warning("views_open failed: %s", e)
            respond(":warning: Couldn't open the form — type it instead: "
                    "`/tt log @opponent 11-7 9-11 11-5`")
        return

    try:
        parsed = parsing.parse_match(rest, caller=caller, bot_id=bot_id)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return

    error = submit_match(parsed["side_a"], parsed["side_b"], parsed["games"], caller,
                         command["channel_id"], client, bot_id=bot_id, logger=logger)
    if error:
        respond(error)


# --- the guided form -------------------------------------------------------

LOG_MODAL = "tt_log_modal"
LOG_SHORTCUT = "tt_log_shortcut"


def _users_block(block_id, label, hint=None, initial=None):
    element = {"type": "multi_users_select", "action_id": "v", "max_selected_items": 2,
               "placeholder": {"type": "plain_text", "text": "Pick one, or two for doubles"}}
    if initial:
        element["initial_users"] = initial
    block = {"type": "input", "block_id": block_id, "element": element,
             "label": {"type": "plain_text", "text": label}}
    if hint:
        block["hint"] = {"type": "plain_text", "text": hint}
    return block


def _channel_block(label="Post the result in", hint="Your opponent confirms it there."):
    """Which channel this form's message belongs in.

    Only shown when the form was opened from the shortcuts menu, which carries
    no channel context at all — a slash command already knows where it was run.
    The wording is per-form: a result goes somewhere to be confirmed, a fixture
    goes somewhere to be bet on.
    """
    element = {"type": "conversations_select", "action_id": "v",
               "default_to_current_conversation": True,
               "filter": {"include": ["public", "private"],
                          "exclude_bot_users": True},
               "placeholder": {"type": "plain_text", "text": "Pick a channel"}}
    if HOME_CHANNEL:
        element["initial_conversation"] = HOME_CHANNEL
    return {"type": "input", "block_id": "channel", "element": element,
            "label": {"type": "plain_text", "text": label},
            "hint": {"type": "plain_text", "text": hint}}


def build_log_modal(caller="", channel_id="", pick_channel=False):
    """The form behind a bare `/tt log` and the shortcuts-menu entry.

    No singles/doubles switch: one name a side is singles, two is doubles, and
    the pickers already say which. channel_id rides in private_metadata so the
    submission knows where the result belongs; pick_channel asks instead, for
    the shortcut path where there is nothing to inherit.
    """
    blocks = [
        _users_block("side_a", "Your side", initial=[caller] if caller else None,
                     hint="Add a partner for doubles."),
        _users_block("side_b", "Opponents"),
        {"type": "input", "block_id": "games",
         "label": {"type": "plain_text", "text": "Game scores"},
         "hint": {"type": "plain_text",
                  "text": "The points in each game, your side first. "
                          "Log as many as you played."},
         "element": {"type": "plain_text_input", "action_id": "v",
                     "placeholder": {"type": "plain_text",
                                     "text": "11-7  9-11  11-5"}}},
    ]
    if pick_channel:
        blocks.append(_channel_block())
    return {
        "type": "modal",
        "callback_id": LOG_MODAL,
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": "Log a session"},
        "submit": {"type": "plain_text", "text": "Log it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def handle_log_shortcut(ack, shortcut, client=None, logger=None):
    """The shortcuts-menu (⚡ / +) entry — the same form, opened from anywhere.

    A global shortcut has no channel, so the form carries a channel picker.
    There's no response_url either, so a failure has to be delivered by DM.
    """
    ack()
    user = shortcut["user"]["id"]
    try:
        client.views_open(trigger_id=shortcut["trigger_id"],
                          view=build_log_modal(user, pick_channel=True))
    except Exception as e:
        (logger or log).warning("shortcut views_open failed: %s", e)
        _dm(client, user, ":warning: Couldn't open the form. Log it with "
                          "`/tt log @opponent 11-7 9-11 11-5` instead.", logger=logger)


def _modal_value(state, block, key="value"):
    """One field's value from a modal's state, whatever its action_id."""
    inner = next(iter(state.get(block, {}).values()), {})
    return inner.get(key)


def handle_log_modal(ack, body, view, client=None, context=None, logger=None):
    """Validate the form in place, then hand off to the same path as the typed
    command. Errors come back attached to their field rather than as a message
    after the modal has closed, so a typo is one correction, not a retype."""
    state = view["state"]["values"]
    side_a = _modal_value(state, "side_a", "selected_users") or []
    side_b = _modal_value(state, "side_b", "selected_users") or []
    caller = body["user"]["id"]

    # The picker is only present on the shortcut path; a slash command inherits
    # the channel it was run in via private_metadata.
    channel = (_modal_value(state, "channel", "selected_conversation")
               or view.get("private_metadata") or "")

    errors = {}
    try:
        games = parsing.parse_games(_modal_value(state, "games") or "")
    except parsing.ParseError as e:
        errors["games"] = str(e)
        games = []
    try:
        parsing.validate_sides(side_a, side_b)
    except parsing.ParseError as e:
        # Side errors are about the pair of pickers; pin them to the second one,
        # which is the one being filled in when the mistake is usually made.
        errors["side_b"] = str(e)
    if not channel and "channel" in state:
        errors["channel"] = "Pick where the result should be posted."
    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()  # close the form
    error = submit_match(side_a, side_b, games, caller, channel or caller, client,
                         bot_id=(context or {}).get("bot_user_id"), logger=logger)
    if error:
        # The modal is gone by now, so there is nothing to attach this to.
        _dm(client, caller, error, logger=logger)


def _only_you(respond, text):
    """Reply to a button press with a note only the presser sees.

    replace_original=False is not optional: a reply to an interactive
    component's response_url *replaces the message it came from* by default. Left
    off, a bystander pressing Confirm would swap the whole channel's view of the
    match for their own "you can't do that" notice — wiping the buttons for the
    people who actually can, and stranding the session in pending forever.
    """
    respond(response_type="ephemeral", replace_original=False, text=text)


def handle_confirm(body, client, respond, logger=None):
    mid = _action_value(body)
    user = body["user"]["id"]
    record = store.get_pending(mid)
    if not record:
        _only_you(respond, ":information_source: That match has already been settled.")
        return
    if not may_confirm(record, user):
        allowed = confirmers(record)
        _only_you(respond, f":lock: Only {fmt_side(allowed)} can confirm this one.")
        return
    if not store.claim_pending(mid):
        _only_you(respond, ":information_source: Someone just confirmed that one.")
        return
    try:
        blob = store.apply_match(record, confirmed_by=user)
    except Exception:
        store.release_pending(mid)  # leave it confirmable rather than stuck
        (logger or log).exception("applying match %s failed", mid)
        _only_you(respond, ":x: Something went wrong rating that match — try again in a moment.")
        return
    _settle_everywhere(client, blob, applied_blocks(blob), "Session confirmed.",
                       body=body, respond=respond, logger=logger)
    _settle_bets(blob, client, logger=logger)
    _note_if_ephemeral(body, respond, f":white_check_mark: Settled `#{mid}`.")


def handle_dispute(body, client, respond, logger=None):
    mid = _action_value(body)
    user = body["user"]["id"]
    record = store.get_pending(mid)
    if not record:
        _only_you(respond, ":information_source: That match has already been settled.")
        return
    if not may_dispute(record, user):
        _only_you(respond, ":lock: Only the players in this match can dispute it.")
        return
    store.drop_pending(mid)
    games_a, games_b, _, _ = elo.tally(record["games"])
    blocks = [
        _section(f":no_entry_sign: ~{scoreline(record, games_a, games_b, settled=False)}~\n"
                 f"~{fmt_games(record['games'])}~"),
        _context(f"Thrown out by <@{user}> — no ratings changed. "
                 "Log it again with the right scores."),
    ]
    _settle_everywhere(client, record, blocks, "Session discarded.",
                       body=body, respond=respond, logger=logger)
    _note_if_ephemeral(body, respond, f":wastebasket: Threw out `#{mid}`.")


def _note_if_ephemeral(body, respond, text):
    """Acknowledge a press that came from an ephemeral list.

    Pressing from a DM edits that DM, so the result is obvious. Pressing from
    `/tt pending` edits messages elsewhere and would otherwise look like nothing
    happened — the stale list is still sitting there with its buttons.
    """
    if (body or {}).get("container", {}).get("is_ephemeral"):
        _only_you(respond, text)


def _action_value(body):
    return (body.get("actions") or [{}])[0].get("value", "")


def _action_id(body):
    return (body.get("actions") or [{}])[0].get("action_id", "")


def _settle_everywhere(client, record, blocks, fallback, body=None, respond=None,
                       logger=None):
    """Show the outcome in every place this session was announced.

    A session now lives in several messages — the channel post plus one DM per
    person who could act — so updating only the one that was clicked would leave
    live buttons in the others for something already decided. Each is updated
    independently; one failure must not stop the rest.
    """
    seen = set()
    targets = []
    if record.get("channel") and record.get("ts"):
        targets.append((record["channel"], record["ts"]))
    for loc in (record.get("dms") or {}).values():
        if isinstance(loc, (list, tuple)) and len(loc) == 2:
            targets.append((loc[0], loc[1]))

    updated = 0
    for channel, ts in targets:
        if (channel, ts) in seen:
            continue
        seen.add((channel, ts))
        try:
            client.chat_update(channel=channel, ts=ts, blocks=blocks, text=fallback)
            updated += 1
        except Exception as e:
            (logger or log).warning("chat_update %s/%s failed: %s", channel, ts, e)

    if updated:
        return
    # Nothing on record (an older session, or every update failed) — fall back to
    # editing whichever message the press came from.
    container = (body or {}).get("container") or {}
    channel, ts = container.get("channel_id"), container.get("message_ts")
    if client is not None and channel and ts:
        try:
            client.chat_update(channel=channel, ts=ts, blocks=blocks, text=fallback)
            return
        except Exception as e:
            (logger or log).warning("chat_update failed, falling back to respond: %s", e)
    if respond is not None:
        respond(replace_original=True, blocks=blocks, text=fallback)


# --- read-only subcommands -------------------------------------------------

NAME_ASK = ("*What should the ladder call you?* Set it once with "
            "`/tt name Your Name` — it's what shows on the web ladder, which "
            "can't render Slack mentions.")


CLEAR_WORDS = ("clear", "reset", "none", "remove")


def handle_name(command, respond, client=None, context=None, logger=None):
    """`/tt name [@someone] [what to call them]` — how a player appears on the
    web ladder, which can't render a Slack mention.

    Naming someone else is admin-only, and they're told it happened. Most people
    will never set their own, so somebody has to be able to do it for them —
    but a name is how you're shown to the whole office, and having it changed
    without knowing is not something to discover from a leaderboard.
    """
    caller = command["user_id"]
    _, rest = parsing.split_subcommand(command.get("text", ""))
    bot_id = (context or {}).get("bot_user_id")
    mentioned = parsing.mentions_in(rest, exclude=bot_id)

    target = caller
    if mentioned:
        if not is_admin(caller):
            respond(":lock: Only an admin can name someone else. "
                    "`/tt name Your Name` sets your own.")
            return
        target = mentioned[0]
    theirs = target != caller
    # "<@bob> is" / "You're" — read the replies aloud before changing this.
    who = f"<@{target}> is" if theirs else "You're"
    wanted = " ".join(parsing.MENTION_RE.sub(" ", rest).split())

    if not wanted:
        current = store.chosen_names().get(target)
        if current:
            respond(f":label: {who} *{current}* on the ladder. "
                    f"`/tt name {'@them ' if theirs else ''}Something Else` "
                    "to change it.")
        elif theirs:
            respond(f":label: <@{target}> hasn't set a name. "
                    f"`/tt name <@{target}> Their Name` sets one for them.")
        else:
            respond(f":label: You haven't set a name yet. {NAME_ASK}")
        return

    if wanted.lower() in CLEAR_WORDS:
        store.clear_name(target)
        respond(f":label: Cleared. The ladder falls back to "
                f"{'their' if theirs else 'your'} Slack name.")
        if theirs:
            _dm(client, target, ":label: An admin cleared your ladder name — it's "
                               "back to your Slack one. `/tt name Your Name` to pick.",
                logger=logger)
        return

    saved = store.set_name(target, wanted)
    url = ladder_url()
    where = f" — <{url}|see it>." if url else "."
    respond(f":label: {who} *{saved}* on the ladder now{where}")
    if theirs:
        _dm(client, target, f":label: An admin set your name on the table tennis "
                            f"ladder to *{saved}*. Not right? "
                            "`/tt name Your Name` changes it.", logger=logger)


def ladder_url():
    """Where the public ladder lives, if the deployment knows its own address.

    Order matters. VERCEL_URL is the *deployment* address — a fresh
    tt-ranker-8ypc8rubm-… host on every push — so a link built from it is dead
    the next time anyone deploys, and it may sit behind deployment protection.
    VERCEL_PROJECT_PRODUCTION_URL is the stable one people should be sent to.
    TT_PUBLIC_URL overrides both, for a custom domain.
    """
    base = (os.environ.get("TT_PUBLIC_URL")
            or os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
            or os.environ.get("VERCEL_URL", ""))
    if not base:
        return ""
    if not base.startswith("http"):
        base = f"https://{base}"
    return f"{base.rstrip('/')}/ladder"


def unnamed_players():
    """Registered players who haven't chosen a name — who `/tt nudge` asks."""
    chosen = store.chosen_names()
    return sorted(uid for uid in store.all_players() if uid not in chosen)


def handle_nudge(command, respond, client, logger=None):
    """`/tt nudge` — ask everyone still unnamed to set one. Admins only: it DMs
    a lot of people at once, which is not something any player should be able to
    trigger on the rest of the office."""
    if not is_admin(command.get("user_id")):
        respond(":lock: Only an admin can send that to everyone. "
                "You can set your own with `/tt name Your Name`.")
        return
    missing = unnamed_players()
    if not missing:
        respond(":white_check_mark: Everyone on the ladder has chosen a name.")
        return
    sent = 0
    for uid in missing:
        try:
            client.chat_postMessage(channel=uid, text=NAME_ASK)
            sent += 1
        except Exception as e:
            (logger or log).warning("name nudge to %s failed: %s", uid, e)
    respond(f":wave: Asked *{sent}* of {len(missing)} to set a name."
            + ("" if sent == len(missing) else " The rest have app DMs turned off."))


def find_by_name(query, names, known=()):
    """uids whose ladder name matches `query`.

    Tiered — exact, then prefix, then substring — and the first tier with any
    hits wins. Without that, someone called Ram loses to Ramesh whenever both
    are on the ladder, which is exactly when you need the lookup.
    """
    query = " ".join((query or "").split()).lower()
    if not query:
        return []
    pool = {uid: (names.get(uid) or f"@{uid[-4:]}") for uid in known}
    pool.update({uid: name for uid, name in names.items() if name})
    exact, prefix, anywhere = [], [], []
    for uid, name in pool.items():
        low = name.lower()
        if low == query:
            exact.append(uid)
        elif low.startswith(query):
            prefix.append(uid)
        elif query in low:
            anywhere.append(uid)
    return sorted(exact) or sorted(prefix) or sorted(anywhere)


def handle_who(command, respond, bot_id=None):
    """`/tt who ChumChum` — who is that in Slack? `/tt who @someone` — what are
    they called on the ladder? Bare, the whole list.

    The ladder page can't render a Slack mention, so it shows chosen names and
    people have no way back from one to a person. This is that way back.
    """
    _, rest = parsing.split_subcommand(command.get("text", ""))
    names = store.names()
    known = list(store.all_players())

    mentioned = parsing.mentions_in(rest, exclude=bot_id)
    if mentioned:
        lines = []
        for uid in mentioned:
            chosen = store.chosen_names().get(uid)
            fallback = names.get(uid)
            if chosen:
                lines.append(f"<@{uid}> is *{chosen}* on the ladder.")
            elif fallback:
                lines.append(f"<@{uid}> shows as *{fallback}* — their Slack name, "
                             "since they haven't set one. `/tt name` changes it.")
            else:
                lines.append(f"<@{uid}> hasn't got a ladder name yet — they show "
                             f"as `@{uid[-4:]}`. `/tt name Their Name` sets one.")
        respond("\n".join(lines))
        return

    query = rest.strip()
    if not query:
        respond(who_list(names, known))
        return

    found = find_by_name(query, names, known)
    if not found:
        respond(f":grey_question: Nobody on the ladder is called *{query}*. "
                "`/tt who` lists everyone.")
        return
    if len(found) == 1:
        uid = found[0]
        respond(f":bust_in_silhouette: *{names.get(uid) or query}* is <@{uid}>.")
        return
    who = " · ".join(f"*{names.get(u) or u}* <@{u}>" for u in found)
    respond(f":bust_in_silhouette: {len(found)} match *{query}*: {who}")


def who_list(names, known):
    """Every ladder name against its Slack mention.

    People with a name come first and unnamed ones collapse to a single line at
    the end. Listed together they sort by their `@abcd` stub, which puts twenty
    placeholders above the names — burying the only rows the command exists to
    show.
    """
    named, unnamed = [], []
    for uid in known:
        name = names.get(uid)
        (named.append((name, uid)) if name else unnamed.append(uid))
    if not named and not unnamed:
        return ":grey_question: Nobody is on the ladder yet."

    lines = [":bust_in_silhouette: *Who's who*"]
    lines += [f"*{name}* — <@{uid}>"
              for name, uid in sorted(named, key=lambda i: i[0].lower())]
    if unnamed:
        lines.append(f"\n_{len(unnamed)} haven't set a name and show as `@abcd` "
                     "on the ladder: " + " ".join(f"<@{u}>" for u in sorted(unnamed))
                     + "_")
    lines.append("\n_`/tt who <name>` for one · `/tt name Your Name` to set yours._")
    return "\n".join(lines)


def handle_register(command, respond):
    uid = command["user_id"]
    fresh = store.ensure_players([uid])
    if fresh:
        respond(f":table_tennis_paddle_and_ball: You're on the ladder at *{elo.START_RATING}*, "
                f"<@{uid}>. Log a match with `/tt log @opponent 11-7 9-11 11-5`.")
        return
    player = store.get_player(uid) or store.new_player()
    respond(f":information_source: You're already on the ladder at *{player['rating']}*. "
            "`/tt me` for the full card.")


WELCOME = (
    ":table_tennis_paddle_and_ball: Welcome to the table tennis ladder, <@{uid}> — "
    f"you're in at *{elo.START_RATING}*.\n\n"
    "Log a match with `/tt log @opponent 11-7 9-11 11-5` — that's the points in "
    "each game. Your opponent confirms it, and both ratings move.\n\n"
    "One thing first: `/tt name Your Name` sets how you appear on the ladder "
    "page. Slack mentions don't render there.\n\n"
    "`/tt board` for the ladder  ·  `/tt me` for your card  ·  `/tt help` for the rest."
)


INTRO = f""":table_tennis_paddle_and_ball: *Welcome to the table tennis ladder*

Everyone here has an Elo rating. Play some games, log them, and the ladder \
sorts itself out. You start at *{elo.START_RATING}*.

*1 · Play as many games as you have time for*
No fixed match length. Two games at lunch, fifteen on a Friday — both count, \
and the longer one counts for more.

*2 · Log it*
Easiest way: type `/tt log` and fill in the form — nothing to memorise. \
(It's also in the shortcuts menu: the `/` button at the right of the message \
toolbar, or just type `/` and search *table tennis*.)

Or type the whole thing:
```
/tt log @opponent 11-7 9-11 11-5
```
That's the points in each game, one per game. Games to 11 or 21 both work, and \
a skunk is just `11-0` — log it as `21-0` and I'll record the 11-0 it stopped \
at, since the rule ends the game there. \
Doubles: `/tt log @partner vs @dan @eve 11-7 11-9`

*3 · The other side confirms*
I DM your opponent the buttons — the channel just sees the claim, so nobody \
who wasn't playing can rule on it. Nothing moves until they press \
:white_check_mark:; you can't wave through your own result. Wrong scores? They \
press :x: and you log it again. Ignored for {store.AUTO_CONFIRM_HOURS}h, it \
applies on its own.

*What moves your rating*
• Beating someone above you is worth a lot. Beating someone below you, very little.
• Losing to someone below you hurts; losing to someone above you barely registers.
• Winning *convincingly* counts more than scraping through — the points matter, \
not just who won.
• More games = more movement, because it's more evidence.

You can't climb by farming one weak opponent: each win against them earns less \
than the last, and it drags their rating down to meet yours.

*Fancy a flutter?*
`/tt schedule @opponent 6pm` puts a fixture up and the channel bets on it with {betting.CURRENCY} — play money, {betting.START_SPINS} to start and {betting.WEEKLY_STIPEND} more every Monday. Everyone who backed the winner splits the pot, so backing the obvious favourite pays least. Betting shuts the moment the match is due.

*The commands*
`/tt board` the ladder · `/tt me` your card · `/tt history` recent results
`/tt book` open fixtures · `/tt wallet` your {betting.CURRENCY} · `/tt help` the rest

_Anyone who joins this channel is added automatically. \
{PLACEMENT_GAMES} games to appear on the board._
_Full scoring detail: <https://github.com/praneatdata/tt-ranker#how-your-rating-is-calculated|how the rating is calculated>._"""

CHANNEL_TOPIC = (":table_tennis_paddle_and_ball: Office table tennis ladder — "
                 "`/tt log @opponent 11-7 9-11 11-5` · `/tt board` for standings")

CHANNEL_DESCRIPTION = (
    "Where the office table tennis ladder lives. Play however many games you "
    "have time for, log them with /tt log, your opponent confirms, ratings "
    "move. Everyone who joins is added automatically. /tt help to get started."
)


def remove_intro(client, channel, logger=None):
    """Take down the intro this bot last posted here. True if there was one."""
    ts = store.last_intro(channel)
    if not ts:
        return False
    try:
        client.chat_delete(channel=channel, ts=ts)
    except Exception as e:
        # Already gone by hand, most likely. Forget it either way rather than
        # keep pointing at a message that isn't there.
        (logger or log).info("intro delete in %s failed: %s", channel, e)
    store.forget_intro(channel)
    return True


def handle_intro(command, respond, client, logger=None):
    """`/tt intro` — post the how-it-works message, for pinning to the channel.
    `/tt intro clear` takes it down again.

    A command rather than a wiki page so it can never drift from what the bot
    actually does: the thresholds in it are the constants the code runs on.
    Which also means it gets re-run after every change, so posting *replaces*
    the last one instead of leaving a trail of stale intros behind.
    """
    channel = command["channel_id"]
    _, rest = parsing.split_subcommand(command.get("text", ""))
    if rest.strip().lower() in ("clear", "delete", "remove", "off", "unpin"):
        if remove_intro(client, channel, logger):
            respond(":wastebasket: Intro taken down.")
        else:
            respond(":information_source: I haven't got an intro posted here. "
                    "If one is pinned from before I started keeping track, "
                    "delete it by hand: hover it → ⋯ → *Delete message*.")
        return

    replaced = remove_intro(client, channel, logger)
    url = ladder_url()
    text = INTRO + (f"\n\n:link: *Live ladder:* {url}" if url else "")
    try:
        resp = client.chat_postMessage(channel=channel, text=text)
    except Exception as e:
        (logger or log).warning("intro post failed: %s", e)
        respond(text)  # at least show the caller
        return
    store.remember_intro(resp["channel"], resp["ts"])
    respond((":arrows_counterclockwise: Replaced the old intro. " if replaced
             else ":pushpin: Posted. ")
            + "Pin it so new players find it (hover the message → ⋯ → "
              "*Pin to channel*). `/tt intro clear` takes it down.")


def handle_member_joined(event, client=None, context=None, logger=None):
    """Put anyone who joins the ladder's home channel on the ladder.

    Scoped to HOME_CHANNEL rather than every channel the bot sits in: being
    invited somewhere busy for a single match shouldn't enrol that channel's
    entire membership. `/tt sync` covers any other channel, explicitly.

    Safe against Slack's event retries — ensure_players only reports genuinely
    new uids, so a redelivery can't produce a second welcome DM.
    """
    if not HOME_CHANNEL or event.get("channel") != HOME_CHANNEL:
        return
    uid = event.get("user")
    if not uid or uid == (context or {}).get("bot_user_id"):
        return  # the bot being invited is not a new player
    if not kv.kv_available():
        (logger or log).warning("member_joined_channel with no KV configured")
        return
    if not store.ensure_players([uid]):
        return  # already on the ladder; someone re-joining is not news
    _dm(client, uid, WELCOME.format(uid=uid), logger=logger)


def _dm(client, uid, text, logger=None):
    """A DM is the quiet way to welcome someone — the channel doesn't need to
    watch every join, but the new player does need to know how to log a match."""
    if client is None:
        return
    try:
        client.chat_postMessage(channel=uid, text=text)
    except Exception as e:
        (logger or log).warning("welcome DM to %s failed: %s", uid, e)


def channel_members(client, channel, limit=SYNC_LIMIT):
    """Every member of a channel, following Slack's cursor pagination."""
    members, cursor = [], None
    while len(members) < limit:
        resp = client.conversations_members(channel=channel, limit=200, cursor=cursor)
        members += resp.get("members") or []
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return members[:limit]


def handle_sync(command, respond, client, context=None, logger=None):
    """`/tt sync` — put everyone already in *this* channel on the ladder.

    Auto-registration only catches people who join from now on, so without this
    the ladder starts empty in a channel that's been running for months. Acts on
    the channel it was run in rather than HOME_CHANNEL, so the one command that
    enrols people in bulk always names its target explicitly.
    """
    channel = command.get("channel_id")
    try:
        members = channel_members(client, channel)
    except Exception as e:
        (logger or log).warning("conversations.members failed: %s", e)
        respond(":warning: I couldn't read this channel's members. Invite me here "
                f"with `/invite <@{(context or {}).get('bot_user_id', 'tt-ranker')}>`, "
                "and check the app has the `channels:read` scope (it needs a reinstall "
                f"after adding one).\n_Slack said: `{e}`_")
        return

    bot_id = (context or {}).get("bot_user_id")
    fresh = store.ensure_players([u for u in members if u != bot_id])
    if not fresh:
        respond(f":information_source: Everyone here is already on the ladder "
                f"({len(members) - (1 if bot_id in members else 0)} players).")
        return
    named = " ".join(f"<@{u}>" for u in fresh[:15])
    more = f" _…and {len(fresh) - 15} more._" if len(fresh) > 15 else ""
    lines = [f":table_tennis_paddle_and_ball: Added *{len(fresh)}* "
             f"player{'s' if len(fresh) != 1 else ''} to the ladder at "
             f"*{elo.START_RATING}*.", f"{named}{more}"]
    if channel == HOME_CHANNEL:
        lines.append("\n_Anyone who joins this channel from now on is added automatically._")
    respond("\n".join(lines))


def handle_me(command, respond, bot_id=None):
    _, rest = parsing.split_subcommand(command.get("text", ""))
    mentioned = parsing.mentions_in(rest, exclude=bot_id)
    uid = mentioned[0] if mentioned else command["user_id"]
    player = store.get_player(uid)
    if not player:
        respond(f":grey_question: <@{uid}> isn't on the ladder yet — "
                "`/tt register`, or just play a match and I'll add them.")
        return

    played = elo.games_played(player)
    decided = player["wins"] + player["losses"]
    rate = f" ({round(100 * player['wins'] / decided)}%)" if decided else ""
    rank, total = _rank_of(uid)
    singles = store.singles_view(player)
    singles_games = elo.games_played(singles)
    doubles = store.doubles_view(player)
    doubles_games = elo.games_played(doubles)
    lines = [
        f":table_tennis_paddle_and_ball: *<@{uid}>* — *{player['rating']}*"
        + (f"   ·   #{rank} of {total}" if rank else "   ·   _still placing_"),
        f"*Record*  {player['wins']}-{player['losses']}"
        + (f"-{player['draws']}" if player["draws"] else "") + rate
        + f"   ·   *Games*  {player['games_won']}-{player['games_lost']}"
        + f"   ·   *Points*  {player['points_won']}-{player['points_lost']}",
        f"*Peak*  {player['peak']}   ·   *Streak*  {fmt_streak(player['streak'])}"
        + (f"   ·   *Best*  {player['best_streak']}" if player["best_streak"] > 1 else ""),
    ]
    if singles_games:
        lines.append(f"*Singles*  {singles['rating']}  ·  "
                     f"{singles['wins']}-{singles['losses']}  ·  "
                     f"{singles_games} game{'s' if singles_games != 1 else ''}"
                     + ("" if singles_games >= SINGLES_PLACEMENT_GAMES
                        else "  _(not yet on the singles board)_"))
    if doubles_games:
        lines.append(f"*Doubles*  {doubles['rating']}  ·  "
                     f"{doubles['wins']}-{doubles['losses']}  ·  "
                     f"{doubles_games} game{'s' if doubles_games != 1 else ''}"
                     + ("" if doubles_games >= DOUBLES_PLACEMENT_GAMES
                        else "  _(not yet on the doubles board)_"))
    worn = [awards.BY_KEY[key].name
            for key in awards.by_player(awards.current()).get(uid, [])]
    if worn:
        lines.append(":military_medal:  *" + "*  ·  *".join(worn) + "*")
    if played < PLACEMENT_GAMES:
        left = PLACEMENT_GAMES - played
        lines.append(f"_{left} more game{'s' if left > 1 else ''} to join the ladder._")
    else:
        lines.append(f"_{played} games over {player['matches']} session"
                     f"{'s' if player['matches'] != 1 else ''} · "
                     f"last played {fmt_ago(player['last_played'])}._")
    respond("\n".join(lines))


def _rank_of(uid):
    """(rank, ladder size) for a placed player, else (None, size)."""
    ranked = ranked_players(store.all_players())
    for i, (u, _) in enumerate(ranked, start=1):
        if u == uid:
            return i, len(ranked)
    return None, len(ranked)


def ranked_players(players, placement=None):
    """[(uid, record)] for everyone past placement, strongest first. Ties break
    on matches played, so the person who has actually shown up ranks higher."""
    placement = PLACEMENT_GAMES if placement is None else placement
    placed = [(u, p) for u, p in players.items() if elo.games_played(p) >= placement]
    return sorted(placed, key=lambda item: (-item[1]["rating"],
                                            -elo.games_played(item[1]), item[0]))


def board_text(players, limit=BOARD_LIMIT, title="Table tennis ladder", view="",
               placement=None):
    """The leaderboard, shared by `/tt board`, the singles board and the weekly
    post. `players` is already the right record set — pass singles views in for a
    singles board."""
    placement = PLACEMENT_GAMES if placement is None else placement
    if not players:
        return (f":table_tennis_paddle_and_ball: *{title}*\n"
                "_Nobody has registered yet — `/tt register` to start it off._")
    ranked = ranked_players(players, placement)
    lines = [f":table_tennis_paddle_and_ball: *{title}*"]
    for i, (uid, p) in enumerate(ranked[:limit]):
        badge = MEDALS[i] if i < 3 else f"`{i + 1:>2}.`"
        row = f"{badge}  <@{uid}> — *{p['rating']}*  ·  {p['wins']}-{p['losses']}"
        if abs(p["streak"]) >= 3:
            row += f"  ·  {fmt_streak(p['streak'])}"
        lines.append(row)
    if not ranked:
        lines.append(f"_No one has played {placement} games yet._")
    if len(ranked) > limit:
        lines.append(f"_…and {len(ranked) - limit} more._")

    placing = sorted(((u, p) for u, p in players.items()
                      if elo.games_played(p) < placement),
                     key=lambda item: (-elo.games_played(item[1]), item[0]))
    if placing:
        what = f"{view} games" if view in ("singles", "doubles") else "games"
        who = ", ".join(f"<@{u}> ({elo.games_played(p)})" for u, p in placing[:10])
        lines.append(f"\n_Still placing ({placement} {what} to qualify): {who}_")
    if view == "singles":
        lines.append("_Singles only — its own rating, untouched by doubles. "
                     "`/tt board` for everything._")
    elif view == "doubles":
        lines.append("_Doubles only, on its own rating — how your teams do, not "
                     "how you do: both partners move by the same amount, so the "
                     "pair is what's really measured. `/tt board singles` is the "
                     "one that can tell you apart._")
    elif view == "overall":
        lines.append("_Singles and doubles together. `/tt board singles` or "
                     "`/tt board doubles` for one format._")
    return "\n".join(lines)


SINGLES_WORDS = ("singles", "single", "solo", "1v1")
DOUBLES_WORDS = ("doubles", "double", "2v2", "pairs")


def handle_board(command, respond):
    """`/tt board` — everything. `/tt board singles|doubles` — one format.

    Separate ladders rather than filtered views: each format is fed by its own
    Elo, so nothing from the other format has touched the numbers on it.
    """
    _, rest = parsing.split_subcommand(command.get("text", ""))
    wanted = rest.strip().lower()
    players = store.all_players()
    if wanted in SINGLES_WORDS:
        text = board_text(store.singles_players(players), title="Singles ladder",
                          view="singles", placement=SINGLES_PLACEMENT_GAMES)
    elif wanted in DOUBLES_WORDS:
        text = board_text(store.doubles_players(players), title="Doubles ladder",
                          view="doubles", placement=DOUBLES_PLACEMENT_GAMES)
    else:
        text = board_text(players, view="overall")
    url = ladder_url()
    respond(text + (f"\n_Live ladder: {url}_" if url else ""))


HISTORY_SHOWN = 10        # unfiltered: the last few, like before
HISTORY_DAY_SHOWN = 30    # a day or a week: show the lot, within reason


def handle_history(command, respond, bot_id=None):
    """`/tt history [@player] [today|yesterday|week|2026-09-16]` — in any order."""
    _, rest = parsing.split_subcommand(command.get("text", ""))
    day_word, rest = parsing.split_day(rest)
    mentioned = parsing.mentions_in(rest, exclude=bot_id)
    uid = mentioned[0] if mentioned else None
    who = f" for <@{uid}>" if uid else ""

    window = parsing.parse_day(day_word, store.now_ist()) if day_word else None
    if day_word and not window:
        respond(f":grey_question: I don't know which day `{day_word}` is. Try `today`, "
                "`yesterday`, `week`, or a date like `2026-09-16`.")
        return

    if window:
        label, start, end = window
        matches = store.matches_in(start, end, uid=uid)
        when = f" {label}"
    else:
        matches = store.recent_matches(limit=HISTORY_SHOWN, uid=uid)
        when = ""

    if not matches:
        respond(f":grey_question: No matches recorded{who}{when}.")
        return
    shown = matches[:HISTORY_DAY_SHOWN if window else HISTORY_SHOWN]
    head = (f":scroll: *Matches{who}{when}* — {len(matches)}" if window
            else f":scroll: *Recent matches{who}*")
    lines = [head]
    for blob in shown:
        deltas = "  ".join(f"<@{u}> `{fmt_delta(blob['deltas'][u])}`"
                           for u in blob["side_a"] + blob["side_b"])
        lines.append(f"`#{blob['id']}`  {fmt_side(blob['side_a'])} "
                     f"*{blob['games_a']}–{blob['games_b']}* {fmt_side(blob['side_b'])}"
                     f"   {deltas}   ·  _{fmt_ago(blob.get('applied_at'))}_")
    if len(matches) > len(shown):
        lines.append(f"_…and {len(matches) - len(shown)} more. The ladder page has the "
                     "full list._" if ladder_url() else
                     f"_…and {len(matches) - len(shown)} more._")
    respond("\n".join(lines))


ADMIN_PENDING_LIMIT = 12  # 3 blocks each, well inside Slack's 50-block ceiling


def _pending_line(record):
    games_a, games_b, _, _ = elo.tally(record["games"])
    who = confirmers(record)
    return (f"`#{record['id']}`  {fmt_side(record['side_a'])} *{games_a}–{games_b}* "
            f"{fmt_side(record['side_b'])}",
            f"logged by <@{record['logged_by']}> {fmt_ago(record['logged_at'])}  ·  "
            f"needs {fmt_side(who) or 'anyone'}")


def admin_pending_blocks(records, admin):
    """The pending queue with buttons on it, for an admin.

    Only ever rendered into an ephemeral reply, so the buttons exist solely for
    the one person entitled to press them and never sit in a channel for
    everyone else to try.
    """
    blocks = [_section(":hourglass_flowing_sand: *Waiting on confirmation*")]
    for record in records[:ADMIN_PENDING_LIMIT]:
        head, tail = _pending_line(record)
        mid = record["id"]
        buttons = []
        if may_confirm(record, admin):
            buttons.append(_button(CONFIRM_ACTION, "✅  Confirm", mid, style="primary"))
        buttons.append(_button(DISPUTE_ACTION, "❌  Throw out", mid))
        blocks += [
            _section(f"{head}\n{fmt_games(record['games'])}"),
            _context(tail + ("" if may_confirm(record, admin)
                             else "  ·  _yours to cancel, not to confirm_")),
            {"type": "actions", "block_id": f"tt_admin_{mid}", "elements": buttons},
        ]
    if len(records) > ADMIN_PENDING_LIMIT:
        blocks.append(_context(f"_…and {len(records) - ADMIN_PENDING_LIMIT} more._"))
    return blocks


def handle_pending(command, respond):
    records = store.list_pending()
    if not records:
        respond(":white_check_mark: Nothing waiting — every session is confirmed.")
        return

    caller = command.get("user_id")
    if is_admin(caller):
        # Admins get the buttons here because the verdict DMs go to the players,
        # not to them — without this they hold the permission and no way to use it.
        respond(blocks=admin_pending_blocks(records, caller),
                text="Sessions waiting on confirmation.")
        return

    lines = [":hourglass_flowing_sand: *Waiting on confirmation*"]
    for record in records:
        head, tail = _pending_line(record)
        lines.append(f"{head}  ·  {tail}")
    lines.append("\n_Check your DMs to settle one, or leave it — unconfirmed "
                 f"sessions apply themselves after {store.AUTO_CONFIRM_HOURS}h._")
    respond("\n".join(lines))


def handle_undo(command, respond):
    uid = command["user_id"]
    blob = store.last_match_by(uid)
    if not blob:
        respond(":grey_question: You haven't logged any confirmed matches to undo. "
                "(A match still waiting on confirmation can be thrown out with the "
                "*That's wrong* button on its message.)")
        return
    ok, reason = store.can_undo(blob)
    if not ok:
        respond(f":warning: {reason}")
        return
    store.undo_match(blob)
    restored = "  ".join(f"<@{u}> back to *{blob['before'][u]}*"
                         for u in blob["side_a"] + blob["side_b"])
    respond(f":leftwards_arrow_with_hook: Undid match `#{blob['id']}` "
            f"({fmt_side(blob['side_a'])} {blob['games_a']}–{blob['games_b']} "
            f"{fmt_side(blob['side_b'])}).\n{restored}")


# --- correcting a match that was logged wrong ------------------------------

EDIT_ACTION = "tt_edit_apply"
EDIT_MOVED_SHOWN = 12


def _edit_summary(plan):
    """The before/after of the match itself, as the admin will read it."""
    was = plan["before"]
    lines = [f"*Was*  {fmt_side(was['side_a'])} vs {fmt_side(was['side_b'])}"
             f"\n{fmt_games(was['games'])}"]
    if plan["void"]:
        lines.append("*Now*  _voided — the match is removed from the ladder._")
    else:
        now = plan["after"]
        lines.append(f"*Now*  {fmt_side(now['side_a'])} vs {fmt_side(now['side_b'])}"
                     f"\n{fmt_games(now['games'])}")
    return "\n".join(lines)


def _edit_effect(plan):
    """Who moves, and the warnings that go with it."""
    lines = []
    if plan["replayed"]:
        lines.append(f"_Re-rates the {plan['replayed']} match"
                     f"{'es' if plan['replayed'] != 1 else ''} logged after it — "
                     "those were rated against ratings this one produced._")
    moved = sorted(plan["moved"].items(), key=lambda i: -abs(i[1][1] - i[1][0]))
    if not moved:
        lines.append("_No rating changes._")
    for uid, (was, now) in moved[:EDIT_MOVED_SHOWN]:
        lines.append(f"<@{uid}>  {was} → *{now}*  `{fmt_delta(now - was)}`")
    if len(moved) > EDIT_MOVED_SHOWN:
        lines.append(f"_…and {len(moved) - EDIT_MOVED_SHOWN} more._")
    if plan["winner_flipped"]:
        lines.append(":warning: *This flips who won.* Any bets on it were already "
                     "paid out on the old result — spins are not touched by a "
                     "correction, so settle those by hand if it matters.")
    return "\n".join(lines)


def handle_edit(command, respond, bot_id=None):
    """`/tt edit #33 21-19 …` · `swap` · `void` — admin only.

    A correction to an old match re-rates every match after it, because those
    were rated against the ratings it produced. So it never writes on the first
    press: it shows exactly what would change and waits to be told yes.
    """
    caller = command["user_id"]
    if not is_admin(caller):
        respond(":lock: Only an admin can edit a logged match. Ask one of them, "
                "or `/tt undo` if it's the last one you logged yourself.")
        return

    _, rest = parsing.split_subcommand(command.get("text", ""))
    try:
        mid, games, swap, void = parsing.parse_edit(rest, bot_id=bot_id)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return

    try:
        plan, state, rewritten, weekly = rerate.plan_edit(
            mid, games=None if void else games, swap=swap)
    except rerate.EditError as e:
        respond(f":warning: {e}")
        return

    respond(blocks=[
        {"type": "section", "text": {"type": "mrkdwn",
         "text": f":pencil2: *Edit match `#{plan['id']}`*\n\n{_edit_summary(plan)}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _edit_effect(plan)}},
        {"type": "actions", "elements": [
            {"type": "button", "action_id": EDIT_ACTION,
             "style": "danger" if plan["void"] else "primary",
             "text": {"type": "plain_text", "text": "Apply the correction"},
             "value": json.dumps({"id": plan["id"], "swap": swap, "void": void,
                                  "games": None if void else games})},
        ]},
        {"type": "context", "elements": [{"type": "mrkdwn",
         "text": "Nothing has changed yet. The channel is told what was corrected."}]},
    ], text=f"Edit match #{plan['id']}")


def handle_edit_apply(body, client, respond, logger=None):
    """The button. Re-plans from scratch rather than trusting the preview: the
    ladder may have moved on since it was drawn, and the numbers that get written
    have to be the numbers computed against what is actually stored now."""
    user = body["user"]["id"]
    if not is_admin(user):
        _only_you(respond, ":lock: Only an admin can apply a correction.")
        return
    try:
        spec = json.loads(_action_value(body))
    except (TypeError, ValueError):
        _only_you(respond, ":x: I've lost track of that edit — run `/tt edit` again.")
        return

    try:
        plan, state, rewritten, weekly = rerate.plan_edit(
            spec["id"], games=None if spec["void"] else
            [tuple(g) for g in (spec["games"] or [])] or None,
            swap=spec["swap"])
    except rerate.EditError as e:
        _only_you(respond, f":warning: {e}")
        return

    rerate.commit_edit(plan, state, rewritten, weekly)
    respond(replace_original=True,
            text=f":white_check_mark: Match `#{plan['id']}` corrected.")

    note = (f":pencil2: <@{user}> corrected match `#{plan['id']}`.\n\n"
            f"{_edit_summary(plan)}\n\n{_edit_effect(plan)}")
    channel = HOME_CHANNEL
    if channel:
        try:
            client.chat_postMessage(channel=channel, text=note)
        except Exception as e:
            (logger or log).warning("could not announce edit: %s", e)


def handle_odds(command, respond, bot_id=None):
    _, rest = parsing.split_subcommand(command.get("text", ""))
    try:
        side_a, side_b = parsing.parse_odds(rest, caller=command.get("user_id"), bot_id=bot_id)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return
    players = store.load_for_match(side_a + side_b)
    entries = lambda side: [{"uid": u, "rating": players[u]["rating"],
                             "games": elo.games_played(players[u])} for u in side]
    chance = elo.win_probability(entries(side_a), entries(side_b))
    ra, rb = elo.team_rating(entries(side_a)), elo.team_rating(entries(side_b))
    respond(f":crystal_ball: {fmt_side(side_a)} *{round(100 * chance)}%*  ·  "
            f"*{round(100 * (1 - chance))}%* {fmt_side(side_b)}"
            f"\n_{round(ra)} vs {round(rb)} — per game, on current ratings._")


# --- the quick list -------------------------------------------------------
# The middle of /tt help: what are the words, one line each. It sits between
# how-to-log and how-the-rating-works rather than in a command of its own,
# because "what can I type?" is the question people bring to help.
#
# Grouped by what you are trying to do rather than alphabetically, because
# nobody scans a leaderboard command list for the letter B. Every canonical name
# in parsing.SUBCOMMANDS has to appear here exactly once — there is a test, so
# this cannot quietly fall behind the parser.

# Gated in the handlers, so listing them to everyone else only produces a
# padlock. `name` is the odd one: naming yourself is open to all, naming someone
# else is not, which the line says rather than hiding the command.
ADMIN_ONLY = frozenset({"edit", "transfer", "nudge"})

QUICK = (
    ("Play", (
        # The forms are spelled out above this list, so the entry is a
        # signpost rather than a fourth copy of the same example.
        ("log", "", "record a session — forms above"),
        ("challenge", "@bob best of 5", "call someone out"),
        ("accept", "4", "take a challenge"),
        ("decline", "4", "turn one down"),
        ("challenges", "", "what's outstanding"),
        ("schedule", "@bob 6pm", "put a fixture up for the channel to back"),
        ("reschedule", "6 7pm", "running late — move it, stakes intact"),
        ("undo", "", "revert the last match you logged"),
    )),
    ("Look", (
        ("board", "singles", "the ladder — or `doubles`, or bare for overall"),
        ("me", "@bob", "one player's card"),
        ("history", "@bob today", "results, by player and by day"),
        ("titles", "", "who holds what"),
        ("odds", "@bob", "who's favoured"),
        ("pending", "", "results still waiting on a confirmation"),
        ("who", "ChumChum", "a ladder name to a person, or back again"),
    )),
    ("Spins", (
        ("wallet", "", "what you hold"),
        ("rich", "", "the spins table"),
        ("bet", "12 a 50", "back a side — the buttons are the usual way"),
        ("book", "", "fixtures open to bet on"),
    )),
    ("You", (
        ("register", "", "join the ladder before your first match"),
        ("name", "Your Name", "how you appear on the web ladder"),
        ("sync", "", "put everyone in this channel on the ladder"),
        ("intro", "", "post the how-it-works message, for pinning"),
        ("help", "", "this list, and how the rating works"),
    )),
    ("Admins", (
        ("edit", "33 21-19 11-9", "correct a logged match — also `swap`, `void`"),
        ("transfer", "@bob 500", "move spins between wallets"),
        ("nudge", "", "DM everyone who hasn't set a name"),
    )),
)


def quick_lines(admin=False):
    """The quick list as lines. `admin` decides whether the padlocked group is
    in it — a list of things you cannot do is a worse list."""
    out = []
    for group, entries in QUICK:
        if group == "Admins" and not admin:
            continue
        out.append(f"*{group}*")
        for name, usage, blurb in entries:
            said = f"`/tt {name}{' ' + usage if usage else ''}`"
            out.append(f"• {said} — {blurb}")
    return out


def did_you_mean(typed):
    """What to say when nothing matches what somebody typed.

    The old answer was the whole of HELP, which buries the one useful sentence —
    that they typed it wrong — under forty lines about Elo.
    """
    guesses = parsing.suggest(typed)
    said = f":grey_question: I don't know `{typed}`."
    if guesses:
        offered = " or ".join(f"`/tt {g}`" for g in guesses)
        said += f" Did you mean {offered}?"
    return said + "\n_`/tt help` lists everything._"


HELP_HEAD = f""":table_tennis_paddle_and_ball: *TT Ranker* — the office table tennis ladder.

*Log a session*
• `/tt log` — opens a form: pick the players, type the scores
   (also under the `/` shortcuts button next to the message box)
• `/tt log @bob 11-7 9-11 11-5` — singles, you vs Bob
• `/tt log @partner vs @dan @eve 11-7 11-9` — doubles
• `/tt log @ann @bob vs @cal @dee 11-7 11-9` — record someone else's match

Scores are the points in each game — log as many games as you played, there's \
no fixed length. The other side confirms it, then ratings move. Unconfirmed \
results apply on their own after {store.AUTO_CONFIRM_HOURS}h.

*Everything else*
• `/tt board` — the ladder    • `/tt board singles` / `doubles` — one format
• `/tt me [@player]` — one player's card
• `/tt history [@player] [today|yesterday|week|date]` — results, filtered
• `/tt pending` — awaiting confirmation
• `/tt odds @bob` — who's favoured    • `/tt undo` — revert the last match you logged
• `/tt register` — join early    • `/tt sync` — add everyone in this channel
• `/tt name Your Name` — how you appear on the web ladder
• `/tt who ChumChum` — who is that? · `/tt who @someone` — what are they called?\n• `/tt intro` — post the how-it-works message, for pinning
• `/tt wallet` — your spins    • `/tt rich` — the spins leaderboard
• `/tt titles` — who holds what
• `/tt reschedule 6 7pm` — running late? move a fixture and keep every stake \
_(or press *Move it* on it)_
• `/tt challenge` — opens a form. Or type it: `/tt challenge @bob best of 5` \
— also `bo7`, `first to 3`, `5 games`, and `at 6pm` if you want a time. \
They accept, it goes up as a fixture.
• `/tt challenge open ±100 bo5` — call out anyone near your level; first to \
take it gets the fixture. Name your own partner for doubles and they bring theirs.
• `/tt accept 4` · `/tt decline 4` · `/tt withdraw 4` · `/tt challenges` \
— answer one, take yours back, or see what's open
• `/tt edit 33 21-19 …` — correct a logged match _(admins; `swap` if the sides \
went in backwards, `void` to throw it out)_

*How the rating works*
results apply on their own after {store.AUTO_CONFIRM_HOURS}h."""


HELP_TAIL = f"""*How the rating works*
Everyone starts at *{elo.START_RATING}*. *Every game is rated on its own and \
they add up* — so 10 games count for more than 3, and a session that splits \
evenly moves nobody. Each game is worth more when you beat someone above you, \
more when you win it decisively, and less when a big favourite wins it. \
Doubles counts {int(elo.DOUBLES_K_FACTOR * 100)}% as hard as singles \
— half of it is your partner.

Your first games move you hardest — you bring about {int(round(elo.K_NEW / elo.K_SETTLED))}x as much to \
game one as to game one hundred, easing off over your first {elo.CALIBRATION_GAMES} or so, \
because everyone's opening {elo.START_RATING} is a guess and the job of those games is to \
replace it. *Every point you gain is a point somebody else lost* — a match is played \
for one stake you and your opponent share, so nothing here mints rating. \
You join the ladder proper after {PLACEMENT_GAMES}. Full details: \
<https://github.com/praneatdata/tt-ranker#how-your-rating-is-calculated|the README>."""


def help_text(uid=None):
    """`/tt help` — how it works, and every word that makes it work.

    One command, not two. An earlier pass at this had a separate `/tt commands`
    for the list, which is one command too many for one job: somebody who wants
    to know what they can type reaches for help, and help should answer.

    So the middle of it is the generated list — every canonical command in
    parsing.SUBCOMMANDS, grouped by what you are trying to do — with the
    padlocked group appended only for the people who can use it. The hand-kept
    bullet list this replaces covered about two thirds of the commands and had
    no way of telling.
    """
    return "\n".join([HELP_HEAD, ""] + quick_lines(admin=is_admin(uid))
                      + ["", HELP_TAIL])


# --- routing ---------------------------------------------------------------

def refresh_names(client, logger=None):
    """Top up the uid → display name map the web ladder reads from.

    Needs `users:read`. Without it this is a no-op and the page falls back to
    whatever names slash commands have happened to reveal, so the scope is worth
    having but never required.
    """
    if not store.names_are_stale():
        return 0
    found, cursor = {}, None
    try:
        for _ in range(10):  # ~10k users; far past any workspace using this
            resp = client.users_list(limit=1000, cursor=cursor)
            for user in resp.get("members") or []:
                if user.get("deleted") or user.get("is_bot"):
                    continue
                profile = user.get("profile") or {}
                name = (profile.get("display_name") or profile.get("real_name")
                        or user.get("name"))
                if user.get("id") and name:
                    found[user["id"]] = name
            cursor = (resp.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    except Exception as e:
        (logger or log).info("users.list unavailable (%s) — names stay partial", e)
        return 0
    store.remember_names(found)
    store.mark_names_fetched()
    return len(found)


def handle_tt_command(ack, command, respond, client=None, context=None, logger=None):
    ack()
    sub, _ = parsing.split_subcommand(command.get("text", ""))
    bot_id = (context or {}).get("bot_user_id")
    # Slash commands carry the caller's Slack handle for free. Kept as a
    # fallback only — whatever they set with /tt name always wins.
    store.remember_handle(command.get("user_id"), command.get("user_name"))

    if sub == "help":
        # An unrecognised verb also lands on "help" (see split_subcommand), and
        # answering a typo with the manual is how a typo stays a typo.
        typed = parsing.unknown_verb(command.get("text", ""))
        respond(did_you_mean(typed) if typed
                else help_text(command.get("user_id")))
        return
    if not kv.kv_available():
        respond(NO_KV)
        return

    try:
        if sub == "log":
            handle_log(command, respond, client, bot_id, logger=logger)
        elif sub == "register":
            handle_register(command, respond)
        elif sub == "me":
            handle_me(command, respond, bot_id)
        elif sub == "board":
            handle_board(command, respond)
        elif sub == "history":
            handle_history(command, respond, bot_id)
        elif sub == "pending":
            handle_pending(command, respond)
        elif sub == "undo":
            handle_undo(command, respond)
        elif sub == "edit":
            handle_edit(command, respond, bot_id)
        elif sub == "odds":
            handle_odds(command, respond, bot_id)
        elif sub == "sync":
            handle_sync(command, respond, client, context, logger=logger)
        elif sub == "intro":
            handle_intro(command, respond, client, logger=logger)
        elif sub == "name":
            handle_name(command, respond, client, context, logger=logger)
        elif sub == "who":
            handle_who(command, respond, bot_id)
        elif sub == "nudge":
            handle_nudge(command, respond, client, logger=logger)
        elif sub == "schedule":
            handle_schedule(command, respond, client, bot_id, logger=logger)
        elif sub == "reschedule":
            handle_reschedule(command, respond, client, logger=logger)
        elif sub == "challenge":
            handle_challenge(command, respond, client, bot_id, logger=logger)
        elif sub in ("accept", "decline"):
            handle_answer_command(command, respond, client, logger=logger)
        elif sub == "challenges":
            handle_challenges(command, respond)
        elif sub == "bet":
            handle_bet(command, respond, client, bot_id, logger=logger)
        elif sub == "wallet":
            handle_wallet(command, respond)
        elif sub == "rich":
            handle_rich(respond)
        elif sub == "withdraw":
            handle_answer_command(command, respond, client, logger=logger)
        elif sub == "titles":
            handle_titles(respond)
        elif sub == "book":
            handle_book(command, respond)
        elif sub == "transfer":
            handle_transfer(command, respond, client, bot_id, logger=logger)
        else:
            respond(help_text(command.get("user_id")))
    except Exception:
        (logger or log).exception("/tt %s failed", sub)
        respond(":x: Something went wrong on my side — try again in a moment.")


def build_app(process_before_response=False, token_verification=True):
    """Build a Bolt App wired with the `/tt` command and the match buttons.

    process_before_response=True is required on serverless hosts (Vercel):
    listeners must finish before the HTTP response is returned, because the
    process is frozen the moment it responds.
    """
    # The corporate TLS proxy (VMock CA) re-signs certificates without the
    # Authority Key Identifier extension, which Python 3.13+'s strict
    # verification rejects. Keep full verification but drop the strict flag.
    ssl_context = ssl.create_default_context()
    ssl_context.verify_flags &= ~ssl.VERIFY_X509_STRICT

    app = App(
        client=WebClient(token=os.environ["SLACK_BOT_TOKEN"], ssl=ssl_context),
        signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
        process_before_response=process_before_response,
        token_verification_enabled=token_verification,
    )
    app.command("/tt")(handle_tt_command)
    app.action(CONFIRM_ACTION)(_wrap_action(handle_confirm))
    app.action(DISPUTE_ACTION)(_wrap_action(handle_dispute))
    app.action(EDIT_ACTION)(_wrap_action(handle_edit_apply))
    app.view(LOG_MODAL)(handle_log_modal)
    app.shortcut(LOG_SHORTCUT)(handle_log_shortcut)
    app.shortcut(SCHEDULE_SHORTCUT)(handle_schedule_shortcut)
    app.view(SCHEDULE_MODAL)(handle_schedule_modal)
    for action in BET_ACTIONS:
        app.action(action)(_wrap_action(handle_bet_button))
    app.action(CANCEL_FIXTURE_ACTION)(_wrap_action(handle_cancel_fixture))
    app.action(RESCHEDULE_ACTION)(_wrap_action(handle_reschedule_button))
    for action in (ACCEPT_ACTION, DECLINE_ACTION, WITHDRAW_ACTION):
        app.action(action)(_wrap_action(handle_challenge_button))
    app.view(RESCHEDULE_MODAL)(handle_reschedule_modal)
    app.shortcut(CHALLENGE_SHORTCUT)(handle_challenge_shortcut)
    app.view(CHALLENGE_MODAL)(handle_challenge_modal)
    app.view(BET_MODAL)(handle_bet_modal)
    app.event("member_joined_channel")(handle_member_joined)
    return app


def _wrap_action(fn):
    """Ack the button press first — Slack greys it out after 3s regardless of how
    the rating maths is going."""
    def listener(ack, body, respond, client=None, logger=None):
        ack()
        if not kv.kv_available():
            _only_you(respond, NO_KV)
            return
        try:
            fn(body, client, respond, logger=logger)
        except Exception:
            (logger or log).exception("action %s failed", fn.__name__)
            _only_you(respond, ":x: Something went wrong — try again in a moment.")
    return listener


# --- betting ---------------------------------------------------------------

# One per side: an action_id has to be unique within its containing block, and
# both Back buttons live in the same one. Sharing "tt_bet" between them made
# Slack reject the whole message as invalid_blocks.
BET_ACTION_A = "tt_bet_a"
BET_ACTION_B = "tt_bet_b"
BET_ACTIONS = (BET_ACTION_A, BET_ACTION_B)
BET_MODAL = "tt_bet_modal"
CANCEL_FIXTURE_ACTION = "tt_fixture_cancel"
RESCHEDULE_ACTION = "tt_fixture_move"
RESCHEDULE_MODAL = "tt_reschedule_modal"
# One per verb: an action_id must be unique inside its actions block, and all
# three of these sit in the same one on the challenged side's DM.
ACCEPT_ACTION = "tt_chal_accept"
DECLINE_ACTION = "tt_chal_decline"
WITHDRAW_ACTION = "tt_chal_withdraw"
CHALLENGE_MODAL = "tt_challenge_modal"
CHALLENGE_SHORTCUT = "tt_challenge_shortcut"


def fmt_spins(n):
    return f"{n:,} {betting.CURRENCY}"


def fmt_when(record, now=None):
    """"today 18:00" / "Thu 18:00" — the resolved time, always echoed back so a
    misread "9am" is visible rather than a surprise."""
    when = betting.starts_at(record)
    if not when:
        return "soon"
    now = (now or store.now_ist()).astimezone(store.IST)
    when = when.astimezone(store.IST)
    if when.date() == now.date():
        return f"today {when:%H:%M}"
    if (when.date() - now.date()).days == 1:
        return f"tomorrow {when:%H:%M}"
    return f"{when:%a %-d %b, %H:%M}"


def fixture_blocks(record, now=None):
    """The channel post for a scheduled match: who's playing, the pot, and — while
    the window is open — the buttons to stake on either side.

    Betting buttons *do* belong in the channel, unlike a match verdict: anyone
    may back a fixture, and only the people in it may rule on a result.
    """
    sid = record["id"]
    pot = betting.pool(sid)
    a, b = fmt_side(record["side_a"]), fmt_side(record["side_b"])
    state = record.get("state")

    head = f":table_tennis_paddle_and_ball: *{a}*  vs  *{b}*"
    if state == "open":
        head += f"\n{fmt_when(record, now)} · betting closes at the first serve"
    elif state == "closed":
        head += f"\n{fmt_when(record, now)} · *betting closed* — waiting on the result"
    blocks = [_section(head)]
    if record.get("note"):
        blocks.append(_context(record["note"]))
    if record.get("moves"):
        # Said on the message rather than only in the channel note: somebody
        # who staked on Tuesday and comes back to it should see that the time
        # changed without having to scroll for the announcement.
        times = "" if int(record["moves"]) == 1 else f" ({record['moves']} times)"
        by = f" by <@{record['moved_by']}>" if record.get("moved_by") else ""
        blocks.append(_context(f":clock3: Moved{by}{times}. Stakes stand."))

    if state in ("open", "closed"):
        blocks.append(_section(pool_line(record, pot)))
        against = betting.backing_against_self(record)
        if against:
            # Allowed by house rule. The guard is that everyone can see it.
            who = ", ".join(f"<@{u}> ({fmt_spins(n)})" for u, n in against)
            blocks.append(_context(f":eyes: Backing the other side of their own "
                                   f"match: {who}"))
    if state in ("open", "closed"):
        elements = []
        if state == "open":
            elements += [
                _button(BET_ACTION_A, f"Back {plain_side(record['side_a'])}",
                        f"{sid}:a", style="primary"),
                _button(BET_ACTION_B, f"Back {plain_side(record['side_b'])}",
                        f"{sid}:b"),
            ]
        # Offered on a closed fixture as well: "we're running late" happens
        # exactly when the window has already shut, and calling it off to put
        # the same match up again hands every stake back.
        elements.append(_button(RESCHEDULE_ACTION, "Move it", sid))
        elements.append(_button(CANCEL_FIXTURE_ACTION, "Call it off", sid))
        blocks.append({"type": "actions", "block_id": f"tt_fixture_{sid}",
                       "elements": elements})
    blocks.append(_context(f"Fixture `#{sid}` · set up by <@{record['created_by']}> · "
                           f"`/tt bet {sid} a 50` also works"))
    return blocks


def plain_side(uids):
    """A button label can't render a mention, so use whatever name we have."""
    names = store.names()
    return " & ".join(names.get(u) or f"@{u[-4:]}" for u in uids)[:70]


BACKERS_SHOWN = 8


def backers_line(pot, side, limit=BACKERS_SHOWN):
    """Who is on a side and for how much, biggest first.

    Named rather than counted: on a small ladder *who* backed you is most of the
    fun, and it's also what makes an odd-looking bet something the room can
    notice rather than something only the database knows.
    """
    rows = sorted(((uid, amount) for uid, (s, amount) in pot["bets"].items()
                   if s == side), key=lambda item: (-item[1], item[0]))
    if not rows:
        return ""
    shown = " · ".join(f"<@{uid}> {amount:,}" for uid, amount in rows[:limit])
    if len(rows) > limit:
        shown += f"  _+{len(rows) - limit} more_"
    return shown


def pool_line(record, pot=None):
    """The pot, each side's share, who's on it, and what a stake returns if it
    settled as it stands."""
    pot = pot or betting.pool(record["id"])
    if not pot["total"]:
        chance_a, chance_b = betting.elo_odds(record)
        return (f"_Nothing staked yet. The ladder makes it "
                f"{round(100 * chance_a)}% / {round(100 * chance_b)}% — "
                f"first in takes the lot._")
    rows = []
    for side, uids in (("a", record["side_a"]), ("b", record["side_b"])):
        staked = pot[side]
        ret = betting.projected(pot, side)
        pays = f"pays *{ret:.2f}×*" if ret else "_no takers — pays the lot_"
        rows.append(f"*{fmt_side(uids)}* — {fmt_spins(staked)} · {pays}")
        backers = backers_line(pot, side)
        if backers:
            rows.append(f"　{backers}")
    return (f":moneybag: *{fmt_spins(pot['total'])}* in the pot\n" + "\n".join(rows))


SCHEDULE_MODAL = "tt_schedule_modal"
SCHEDULE_SHORTCUT = "tt_schedule_shortcut"


def open_fixture(side_a, side_b, when, caller, channel, client, now=None,
                 logger=None, bot_id=None):
    """Create a fixture and post it. Returns None, or a message for the caller.

    Shared by the typed command, the form and the shortcut, so none of them can
    drift on what happens once a valid fixture is entered.
    """
    now = now or store.now_ist()
    record = betting.schedule(side_a, side_b, when, created_by=caller,
                              channel=channel, now=now)
    try:
        resp = client.chat_postMessage(
            channel=channel, blocks=fixture_blocks(record, now),
            text=f"{plain_side(side_a)} vs {plain_side(side_b)}, {fmt_when(record, now)}.")
    except Exception as e:
        # No message means nobody can bet on it, so don't leave one standing.
        betting.claim(record["id"])
        betting.void(record, "could not be posted", now)
        (logger or log).warning("could not post fixture in %s: %s", channel, e)
        return post_failure(e, channel, bot_id) + " Nothing was staked."
    record["ts"], record["channel"] = resp["ts"], resp["channel"]
    betting.save(record)
    return None


def _default_start(now=None):
    """An hour out, rounded up to the next quarter — near enough to be plausible,
    round enough to look deliberate."""
    when = ((now or store.now_ist()) + timedelta(hours=1)).replace(second=0, microsecond=0)
    return when + timedelta(minutes=(15 - when.minute % 15) % 15)


def build_schedule_modal(caller="", channel_id="", pick_channel=False, now=None):
    """The form behind a bare `/tt schedule`.

    A native date-and-time picker rather than a text box: "6pm" has to be parsed,
    guessed at across midnight and echoed back to be checked, while a picker is
    unambiguous the moment it's set.
    """
    blocks = [
        _users_block("side_a", "Your side", initial=[caller] if caller else None,
                     hint="Add a partner for doubles."),
        _users_block("side_b", "Opponents"),
        {"type": "input", "block_id": "when",
         "label": {"type": "plain_text", "text": "First serve"},
         "hint": {"type": "plain_text",
                  "text": "Betting shuts at this moment — until then anyone "
                          "in the channel can back either side."},
         "element": {"type": "datetimepicker", "action_id": "v",
                     "initial_date_time": int(_default_start(now).timestamp())}},
    ]
    if pick_channel:
        blocks.append(_channel_block("Put the fixture in",
                                     "Where people will see it and bet on it."))
    return {
        "type": "modal",
        "callback_id": SCHEDULE_MODAL,
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": "Schedule a match"},
        "submit": {"type": "plain_text", "text": "Put it up"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def handle_schedule(command, respond, client, bot_id=None, logger=None):
    """`/tt schedule @bob 6pm` — a fixture, and a betting window that shuts when
    it starts. Bare, it opens the form."""
    caller = command["user_id"]
    _, rest = parsing.split_subcommand(command.get("text", ""))
    now = store.now_ist()

    if not rest.strip():
        try:
            client.views_open(trigger_id=command["trigger_id"],
                              view=build_schedule_modal(caller,
                                                        command.get("channel_id", ""),
                                                        now=now))
        except Exception as e:
            (logger or log).warning("schedule modal failed: %s", e)
            respond(":warning: Couldn't open the form — type it instead: "
                    "`/tt schedule @opponent 6pm`")
        return

    try:
        side_a, side_b, when = parsing.parse_schedule(rest, caller=caller,
                                                      bot_id=bot_id, now=now)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return
    error = open_fixture(side_a, side_b, when, caller, command["channel_id"],
                         client, now, logger, bot_id=bot_id)
    if error:
        respond(error)


def handle_schedule_shortcut(ack, shortcut, client=None, logger=None):
    """The shortcuts-menu entry. No channel context, so the form asks."""
    ack()
    user = shortcut["user"]["id"]
    try:
        client.views_open(trigger_id=shortcut["trigger_id"],
                          view=build_schedule_modal(user, pick_channel=True))
    except Exception as e:
        (logger or log).warning("schedule shortcut failed: %s", e)
        _dm(client, user, ":warning: Couldn't open the form. Put a fixture up "
                          "with `/tt schedule @opponent 6pm` instead.", logger=logger)


def handle_schedule_modal(ack, body, view, client=None, context=None, logger=None):
    """Validate in place, then hand off to the same path as the typed command."""
    state = view["state"]["values"]
    side_a = _modal_value(state, "side_a", "selected_users") or []
    side_b = _modal_value(state, "side_b", "selected_users") or []
    epoch = _modal_value(state, "when", "selected_date_time")
    channel = (_modal_value(state, "channel", "selected_conversation")
               or view.get("private_metadata") or "")
    now = store.now_ist()

    errors, when = {}, None
    try:
        parsing.validate_sides(side_a, side_b)
    except parsing.ParseError as e:
        errors["side_b"] = str(e)
    if not epoch:
        errors["when"] = "Pick when it starts."
    else:
        when = datetime.fromtimestamp(int(epoch), tz=store.IST)
        if when <= now:
            errors["when"] = "That's already past — betting would shut immediately."
        elif when - now > timedelta(days=parsing.MAX_LEAD_DAYS):
            errors["when"] = (f"More than {parsing.MAX_LEAD_DAYS} days out. "
                              "Put it up nearer the time.")
    if not channel and "channel" in state:
        errors["channel"] = "Pick where to post it."
    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()
    caller = body["user"]["id"]
    error = open_fixture(side_a, side_b, when, caller, channel or caller,
                         client, now, logger, bot_id=(context or {}).get("bot_user_id"))
    if error:
        _dm(client, caller, error, logger=logger)


def handle_bet(command, respond, client=None, bot_id=None, logger=None):
    """`/tt bet 12 a 50` — the typed route; the buttons are the usual one."""
    _, rest = parsing.split_subcommand(command.get("text", ""))
    parts = rest.split()
    if len(parts) < 3:
        respond(":warning: `/tt bet <fixture> <side> <amount>` — e.g. `/tt bet 12 a 50`. "
                "`/tt book` lists what's open.")
        return
    sid, side, amount = parts[0].lstrip("#"), parts[1].lower(), parts[2]
    record = betting.get(sid)
    if not record:
        respond(f":grey_question: No fixture `#{sid}`. `/tt book` lists what's open.")
        return
    if side in ("1", "a", "left", "first"):
        side = "a"
    elif side in ("2", "b", "right", "second"):
        side = "b"
    else:
        respond(":warning: Which side — `a` or `b`? `/tt book` shows who's who.")
        return
    _take_bet(record, command["user_id"], side, amount, respond, client, logger)


def _take_bet(record, uid, side, amount, respond, client=None, logger=None):
    ok, message = betting.place_bet(record, uid, side, amount)
    if not ok:
        _refresh_fixture(record, client, logger=logger)  # it may have just closed
        respond(f":warning: {message}")
        return
    respond(f":moneybag: {message}  Balance: *{fmt_spins(betting.balance(uid))}*.")
    _refresh_fixture(record, client, logger=logger)


def _refresh_fixture(record, client, now=None, logger=None):
    """Repaint the fixture message so the pot on screen is the pot in the pool."""
    if not (client and record.get("channel") and record.get("ts")):
        return
    try:
        client.chat_update(channel=record["channel"], ts=record["ts"],
                           blocks=fixture_blocks(record, now),
                           text="Table tennis fixture.")
    except Exception as e:
        (logger or log).warning("fixture %s refresh failed: %s", record["id"], e)


def handle_bet_button(body, client, respond, logger=None):
    """Opens the stake modal. The side rides in the button value."""
    sid, _, side = _action_value(body).partition(":")
    record = betting.get(sid)
    if not record:
        _only_you(respond, ":information_source: That fixture has gone.")
        return
    if betting.close_if_due(record):
        _refresh_fixture(record, client, logger=logger)
    if record["state"] != "open":
        _only_you(respond, ":lock: Betting on that one has closed.")
        return
    uid = body["user"]["id"]
    betting.ensure_wallets([uid])
    try:
        client.views_open(trigger_id=body["trigger_id"],
                          view=bet_modal(record, side, betting.balance(uid)))
    except Exception as e:
        (logger or log).warning("bet modal failed: %s", e)
        _only_you(respond, f":warning: Couldn't open the form — "
                           f"`/tt bet {sid} {side} 50` works too.")


def bet_modal(record, side, held):
    uids = record["side_a"] if side == "a" else record["side_b"]
    pot = betting.pool(record["id"])
    ret = betting.projected(pot, side)
    hint = (f"Pays {ret:.2f}× if it settled now. You have {held} {betting.CURRENCY}."
            if ret else
            f"Nobody's on this side yet — you'd take the lot. "
            f"You have {held} {betting.CURRENCY}.")
    return {
        "type": "modal",
        "callback_id": BET_MODAL,
        "private_metadata": f"{record['id']}:{side}",
        "title": {"type": "plain_text", "text": "Place a bet"},
        "submit": {"type": "plain_text", "text": "Stake it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _section(f"Backing *{plain_side(uids)}* in fixture `#{record['id']}`."),
            {"type": "input", "block_id": "amount",
             "label": {"type": "plain_text", "text": f"How many {betting.CURRENCY}?"},
             "hint": {"type": "plain_text", "text": hint},
             "element": {"type": "plain_text_input", "action_id": "v",
                         "placeholder": {"type": "plain_text", "text": "50"}}},
        ],
    }


def handle_bet_modal(ack, body, view, client=None, logger=None):
    sid, _, side = (view.get("private_metadata") or "").partition(":")
    record = betting.get(sid)
    if not record:
        ack(response_action="errors", errors={"amount": "That fixture has gone."})
        return
    raw = (_modal_value(view["state"]["values"], "amount") or "").strip()
    try:
        amount = int(raw.replace(",", ""))
    except ValueError:
        ack(response_action="errors",
            errors={"amount": f"A whole number of {betting.CURRENCY}, like 50."})
        return
    uid = body["user"]["id"]
    ok, message = betting.place_bet(record, uid, side, amount)
    if not ok:
        ack(response_action="errors", errors={"amount": message})
        return
    ack()
    _refresh_fixture(record, client, logger=logger)
    _dm(client, uid, f":moneybag: {message}  "
                     f"Balance: *{fmt_spins(betting.balance(uid))}*.", logger=logger)


def handle_cancel_fixture(body, client, respond, logger=None):
    """Call a fixture off and hand every stake back."""
    sid = _action_value(body)
    record = betting.get(sid)
    if not record:
        _only_you(respond, ":information_source: That fixture has gone.")
        return
    user = body["user"]["id"]
    allowed = set(record["side_a"] + record["side_b"] + [record["created_by"]])
    if user not in allowed and not is_admin(user):
        _only_you(respond, ":lock: Only the players or whoever set it up can call it off.")
        return
    if not betting.claim(sid):
        _only_you(respond, ":information_source: That one is already settled.")
        return
    refunded = betting.pool(sid)["total"]
    betting.void(record, f"called off by <@{user}>")
    blocks = [
        _section(f":no_entry_sign: ~{fmt_side(record['side_a'])} vs "
                 f"{fmt_side(record['side_b'])}~ — called off."),
        _context(f"Called off by <@{user}>."
                 + (f" {fmt_spins(refunded)} refunded." if refunded else "")),
    ]
    _refresh_with(record, client, blocks, "Fixture called off.", logger=logger)


# --- challenges ------------------------------------------------------------

def challenge_line(record, now=None, players=None):
    """The headline. Carries both ratings, because a challenge is a claim about
    which of two numbers is the better one."""
    if players is None:
        players = store.get_players(record["side_a"] + record["side_b"])
    a = fmt_side_rated(record["side_a"], players)
    when = challenge.starts_at(record)
    at = f" · {fmt_when({'starts_at': store.stamp(when)}, now)}" if when else ""
    if challenge.is_open_call(record):
        # No opponent to name and no favourite to work out, so the band does the
        # job the other side's rating does on a directed challenge.
        return (f":crossed_swords: {a}\n"
                f"*is calling anyone out*\n"
                f"_{challenge.band_note(record)}"
                f" · {challenge.length_note(record)}{at}_")
    b = fmt_side_rated(record["side_b"], players)
    return (f":crossed_swords: {a}\n"
            f"*challenges*\n"
            f"{b}\n"
            f"_{challenge.length_note(record)}{at}_")


def challenge_blocks(record, now=None):
    """What the channel sees. Read-only, like a pending result: the buttons go
    to the people who get to answer, not to everyone who can see the post."""
    open_call = challenge.is_open_call(record)
    who = "whoever takes it" if open_call else fmt_side(record["side_b"])
    state = record.get("state")
    if state == "open":
        tail = ((f"Open to {challenge.band_note(record)}"
                 + (", in pairs" if challenge.side_size(record) > 1 else "")
                 + f". Expires in {challenge.EXPIRE_HOURS}h if nobody takes it.")
                if open_call else
                f"Waiting on {who}. Expires in {challenge.EXPIRE_HOURS}h "
                "if nobody answers.")
    elif state == "accepted":
        tail = f"Accepted by <@{record['answered_by']}> — fixture `#{record['fixture']}` is up."
    elif state == "declined":
        tail = f"Declined by <@{record['answered_by']}>."
    elif state == "withdrawn":
        tail = f"Withdrawn by <@{record['answered_by']}>."
    else:
        tail = f"Nobody answered in {challenge.EXPIRE_HOURS}h."
    players = store.get_players(record["side_a"] + record["side_b"])
    blocks = [_section(challenge_line(record, now, players))]
    if state == "open" and not open_call:
        blocks.append(_context(favourite_line(record["side_a"], record["side_b"],
                                              players)))
    blocks.append(_context(f"Challenge `#{record['id']}` · {tail}"))
    # An open call has no named audience to DM, so the one button that matters
    # goes in the channel where the people who could answer it are.
    if state == "open" and open_call:
        if challenge.side_size(record) > 1:
            blocks.append(_context(
                f"_Bring a partner: `/tt accept {record['id']} @them`._"))
        else:
            blocks.append({
                "type": "actions", "block_id": f"tt_chal_{record['id']}",
                "elements": [_button(ACCEPT_ACTION, "⚔️  I'll take it",
                                     record["id"], style="primary")]})
    return blocks


def challenge_dm_blocks(record, role, now=None):
    """The DM carrying the buttons, cut to what this person may do."""
    cid = record["id"]
    players = store.get_players(record["side_a"] + record["side_b"])
    head = (challenge_line(record, now, players) + "\n"
            + favourite_line(record["side_a"], record["side_b"], players))
    if role == "answer":
        note = (f"<@{record['from']}> wants a game. "
                f"{challenge.length_note(record)}. "
                f"Say yes and it goes up as a fixture the channel can bet on.")
        buttons = [_button(ACCEPT_ACTION, "⚔️  Accept", cid, style="primary"),
                   _button(DECLINE_ACTION, "Not today", cid)]
    else:
        note = (f"Sent to {fmt_side(record['side_b'])}. "
                f"Expires in {challenge.EXPIRE_HOURS}h if they don't answer.")
        buttons = [_button(WITHDRAW_ACTION, "🗑  Take it back", cid)]
    return [_section(head), _context(note),
            {"type": "actions", "block_id": f"tt_chal_{cid}", "elements": buttons}]


def challenge_audience(record):
    """{uid: role} — everyone being challenged gets buttons; the challenger gets
    the one useful action, which is taking it back."""
    who = {uid: "answer" for uid in record["side_b"]}
    if record.get("from") and record["from"] not in who:
        who[record["from"]] = "withdraw"
    return who


def build_challenge_modal(caller="", channel_id="", pick_channel=False):
    """The form behind a bare `/tt challenge`.

    The length is a menu rather than a text box: it is the one field with a
    small, known set of right answers, and picking from them means nobody has to
    learn that `bo5` is a thing the bot understands.

    The time is genuinely optional here, unlike the schedule form. "Play me some
    time today" is a real invitation, and a form that insisted on a start time
    would turn every challenge into a commitment nobody made.
    """
    options = [{"text": {"type": "plain_text", "text": challenge.choice_label(key)},
                "value": key} for key, _, _ in challenge.LENGTH_CHOICES]
    initial = next(o for o in options if o["value"] == challenge.DEFAULT_CHOICE)
    blocks = [
        _users_block("side_a", "Your side", initial=[caller] if caller else None,
                     hint="Add a partner for doubles."),
        _users_block("side_b", "Who you're calling out"),
        {"type": "input", "block_id": "length",
         "label": {"type": "plain_text", "text": "How long"},
         "hint": {"type": "plain_text",
                  "text": "Agreed up front, so it isn't an argument afterwards."},
         "element": {"type": "static_select", "action_id": "v",
                     "options": options, "initial_option": initial}},
        {"type": "input", "block_id": "when", "optional": True,
         "label": {"type": "plain_text", "text": "Start time (optional)"},
         "hint": {"type": "plain_text",
                  "text": "Leave it out and it starts shortly after they accept."},
         "element": {"type": "datetimepicker", "action_id": "v"}},
    ]
    if pick_channel:
        blocks.append(_channel_block("Put the challenge in",
                                     "Where they'll see it, and where the "
                                     "fixture goes if they accept."))
    return {
        "type": "modal",
        "callback_id": CHALLENGE_MODAL,
        "private_metadata": channel_id or "",
        "title": {"type": "plain_text", "text": "Challenge someone"},
        "submit": {"type": "plain_text", "text": "Call them out"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def handle_challenge_shortcut(ack, shortcut, client=None, logger=None):
    """The shortcuts-menu entry. No channel context, so the form asks."""
    ack()
    user = shortcut["user"]["id"]
    try:
        client.views_open(trigger_id=shortcut["trigger_id"],
                          view=build_challenge_modal(user, pick_channel=True))
    except Exception as e:
        (logger or log).warning("challenge shortcut failed: %s", e)
        _dm(client, user, ":warning: Couldn't open the form. Call someone out "
                          "with `/tt challenge @bob best of 5` instead.",
            logger=logger)


def handle_challenge_modal(ack, body, view, client=None, context=None, logger=None):
    """Validate in place, then hand off to the same path as the typed command."""
    state = view["state"]["values"]
    side_a = _modal_value(state, "side_a", "selected_users") or []
    side_b = _modal_value(state, "side_b", "selected_users") or []
    choice = _modal_value(state, "length", "selected_option") or {}
    epoch = _modal_value(state, "when", "selected_date_time")
    channel = (_modal_value(state, "channel", "selected_conversation")
               or view.get("private_metadata") or "")
    now = store.now_ist()

    errors, when = {}, None
    try:
        parsing.validate_sides(side_a, side_b)
    except parsing.ParseError as e:
        errors["side_b"] = str(e)
    if set(side_a) & set(side_b):
        errors["side_b"] = "Somebody is on both sides."
    if epoch:
        when = datetime.fromtimestamp(int(epoch), tz=store.IST)
        if when <= now:
            errors["when"] = "That's already past — leave it blank or pick a later time."
        elif when - now > timedelta(days=parsing.MAX_LEAD_DAYS):
            errors["when"] = (f"More than {parsing.MAX_LEAD_DAYS} days out. "
                              "Challenge them nearer the time.")
    if not channel and "channel" in state:
        errors["channel"] = "Pick where to put it."
    if not errors and challenge.open_between(side_a, side_b):
        errors["side_b"] = "There's already an open challenge between you two."
    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()
    caller = body["user"]["id"]
    games, first_to = challenge.length_of(choice.get("value"))
    error = open_challenge(side_a, side_b, games, first_to, when, caller,
                           channel or caller, client, now, logger,
                           bot_id=(context or {}).get("bot_user_id"))
    if error:
        _dm(client, caller, error, logger=logger)


def handle_challenge(command, respond, client=None, bot_id=None, logger=None):
    """`/tt challenge @bob best of 5` — an invitation with a length on it.
    Bare, it opens the form."""
    caller = command["user_id"]
    _, rest = parsing.split_subcommand(command.get("text", ""))
    now = store.now_ist()
    is_open, rest = parsing.split_open(rest)
    if is_open:
        handle_open_challenge(rest, caller, command.get("channel_id", ""),
                              respond, client, now, logger, bot_id)
        return
    if not rest.strip():
        try:
            client.views_open(
                trigger_id=command["trigger_id"],
                view=build_challenge_modal(caller, command.get("channel_id", "")))
        except Exception as e:
            (logger or log).warning("challenge modal failed: %s", e)
            respond(":warning: Couldn't open the form — type it instead: "
                    "`/tt challenge @bob best of 5`")
        return
    try:
        side_a, side_b, games, first_to, when = parsing.parse_challenge(
            rest, caller=caller, bot_id=bot_id, now=now,
            default_games=challenge.DEFAULT_GAMES)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return

    standing = challenge.open_between(side_a, side_b)
    if standing:
        respond(f":information_source: There's already an open challenge between "
                f"you two — `#{standing['id']}`, {challenge.length_note(standing)}. "
                "Answer that one first.")
        return
    error = open_challenge(side_a, side_b, games, first_to, when, caller,
                           command.get("channel_id", ""), client, now, logger,
                           bot_id=bot_id)
    if error:
        respond(error)


def band_rating(uids, doubles):
    """The rating an open call's band is tested against.

    The format's own: a doubles call is about how you play in pairs, and the
    doubles board is the one that knows. For a pair it is the mean, which is
    what elo.team_rating() already treats a team as being worth.
    """
    players = store.load_for_match(list(uids))
    view = store.doubles_view if doubles else store.singles_view
    ratings = [view(players[uid])["rating"] for uid in uids]
    return int(round(sum(ratings) / len(ratings))) if ratings else elo.START_RATING


def handle_open_challenge(rest, caller, channel, respond, client, now,
                          logger=None, bot_id=None):
    """`/tt challenge open ±100 best of 5` — an invitation to the channel.

    Nobody is named, so there is nobody to DM and nothing to work out a
    favourite from. What stands in for the opponent is a rating band, tested
    against whoever presses rather than promised to anyone in particular.
    """
    store.ensure_players([caller], now)
    mine = store.get_player(caller) or store.new_player(now)
    standing = challenge.open_call_by(caller)
    if standing:
        respond(":information_source: You already have one out — "
                f"`#{standing['id']}`, {challenge.band_note(standing)}. "
                f"`/tt withdraw {standing['id']}` to replace it.")
        return
    try:
        side_a, band, games, first_to, when = parsing.parse_open_challenge(
            rest, caller=caller, bot_id=bot_id, now=now,
            default_games=challenge.DEFAULT_GAMES,
            rating=band_rating([caller], doubles=False))
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return
    if len(side_a) > 1:
        # A doubles call is tested on the doubles board, so re-read a relative
        # band against that rating rather than the singles one.
        try:
            side_a, band, games, first_to, when = parsing.parse_open_challenge(
                rest, caller=caller, bot_id=bot_id, now=now,
                default_games=challenge.DEFAULT_GAMES,
                rating=band_rating(side_a, doubles=True))
        except parsing.ParseError as e:
            respond(f":warning: {e}")
            return
    error = open_challenge(side_a, [], games, first_to, when, caller, channel,
                           client, now, logger, bot_id=bot_id, band=band)
    if error:
        respond(error)
    elif elo.games_played(mine) < PLACEMENT_GAMES:
        respond(":information_source: Put it up. Your rating is still settling, "
                "so the range around it is a rough guide for now.")


def open_challenge(side_a, side_b, games, first_to, when, caller, channel,
                   client, now=None, logger=None, bot_id=None, band=None):
    """Create a challenge, post it, and DM the buttons. Returns None, or a
    message for the caller.

    Shared by the typed command, the form and the shortcut, so none of them can
    drift on what happens once a valid challenge is entered.
    """
    now = now or store.now_ist()
    store.ensure_players(side_a + side_b, now)
    record = challenge.issue(side_a, side_b, games, by=caller, first_to=first_to,
                             starts_at=when, channel=channel, now=now, band=band)
    try:
        resp = client.chat_postMessage(
            channel=channel, blocks=challenge_blocks(record, now),
            text=f"{plain_side(side_a)} challenges {plain_side(side_b)}.")
        record["ts"], record["channel"] = resp["ts"], resp["channel"]
        challenge.save(record)
    except Exception as e:
        # Nowhere to see it means nobody can answer it, so don't leave one open.
        challenge.claim(record["id"])
        challenge.withdraw(record, caller, now)
        (logger or log).warning("could not post challenge: %s", e)
        return post_failure(e, channel, bot_id)

    # An open call has nobody to DM buttons to — the button is in the channel,
    # which is where the people who could answer it are.
    if challenge.is_open_call(record):
        return None

    delivered = 0
    for uid, role in challenge_audience(record).items():
        try:
            client.chat_postMessage(
                channel=uid, blocks=challenge_dm_blocks(record, role, now),
                text=f"{plain_side(side_a)} vs {plain_side(side_b)}.")
            delivered += 1
        except Exception as e:
            (logger or log).warning("challenge DM to %s failed: %s", uid, e)
    if not delivered:
        return (":warning: Posted it, but I couldn't DM anyone the buttons — "
                f"they can answer with `/tt accept {record['id']}`.")
    return None


def _close_challenge(record, client, now=None, logger=None):
    """Rewrite the channel post so no live button is left anywhere."""
    if client and record.get("channel") and record.get("ts"):
        try:
            client.chat_update(channel=record["channel"], ts=record["ts"],
                               blocks=challenge_blocks(record, now),
                               text="Challenge settled.")
        except Exception as e:
            (logger or log).warning("challenge %s update failed: %s",
                                    record["id"], e)


def answer_challenge(cid, user, verb, client, now=None, logger=None,
                     partner=None):
    """Accept, decline or withdraw. Returns a message for the caller, or None.

    The claim is the SREM, so two people pressing Accept at the same moment
    cannot both put a fixture up for the same match. On an open call that is the
    whole channel rather than one named person, which is exactly when it earns
    its keep.

    `partner` is who the accepter is bringing, on an open doubles call.
    """
    now = now or store.now_ist()
    record = challenge.get(cid)
    if not record:
        return ":information_source: There's no challenge by that number."
    if record.get("state") != "open":
        return f":information_source: That one was already {record['state']}."
    allowed = (challenge.may_withdraw(record, user) if verb == "withdraw"
               else challenge.may_answer(record, user))
    if not allowed:
        if verb == "withdraw":
            return ":lock: Only whoever threw it down can take it back."
        if challenge.is_open_call(record):
            return ":person_shrugging: That's your own challenge — somebody else has to take it."
        return f":lock: Only {fmt_side(record['side_b'])} can answer that one."

    taking = None
    if verb == "accept" and challenge.is_open_call(record):
        taking, refusal = open_call_side(record, user, partner)
        if refusal:
            return refusal
    if not challenge.claim(cid):
        return ":information_source: Someone just answered that one."

    try:
        if verb == "accept":
            fixture = challenge.accept(record, user, now=now, side_b=taking)
        elif verb == "decline":
            challenge.decline(record, user, now)
        else:
            challenge.withdraw(record, user, now)
    except Exception:
        challenge.release(cid)
        (logger or log).exception("answering challenge %s failed", cid)
        return ":x: Something went wrong there — try again in a moment."

    _close_challenge(record, client, now, logger)
    if verb != "accept":
        return None
    try:
        resp = client.chat_postMessage(
            channel=fixture["channel"] or record.get("channel", ""),
            blocks=fixture_blocks(fixture, now),
            text=f"{plain_side(fixture['side_a'])} vs {plain_side(fixture['side_b'])}, "
                 f"{fmt_when(fixture, now)}.")
        fixture["ts"], fixture["channel"] = resp["ts"], resp["channel"]
        betting.save(fixture)
    except Exception as e:
        (logger or log).warning("could not post accepted fixture: %s", e)
        return (":warning: Challenge accepted, but I couldn't put the fixture up "
                "where people can bet on it.")
    return None


def open_call_side(record, user, partner=None):
    """(the accepting side, a refusal) for an open call — one or the other.

    Checked before the claim, so a refusal leaves the challenge open for
    somebody who does qualify rather than burning it.
    """
    want = challenge.side_size(record)
    side = [user] + ([partner] if partner and partner != user else [])
    if len(side) != want:
        if want > 1:
            return None, (":busts_in_silhouette: That one's doubles — bring "
                          f"someone: `/tt accept {record['id']} @partner`.")
        return None, (":bust_in_silhouette: That one's singles, so it's just "
                      f"you: `/tt accept {record['id']}`.")
    clash = set(side) & set(record.get("side_a", ()))
    if clash:
        return None, (":person_shrugging: "
                      f"{fmt_side(sorted(clash))} is already in that one.")
    doubles = want > 1
    rating = band_rating(side, doubles)
    if not challenge.admits(record, rating):
        band = challenge.band_of(record)
        whose = "you're" if want == 1 else "you two are"
        return None, (f":no_entry_sign: That one's for {challenge.band_note(record)}"
                      f" — {whose} {rating}."
                      + ("" if want == 1 else
                         " A pair is taken at the average of the two.")
                      + f" Bands run {band[0]}–{band[1]}.")
    return side, None


def handle_challenge_button(body, client, respond, logger=None):
    verb = {ACCEPT_ACTION: "accept", DECLINE_ACTION: "decline",
            WITHDRAW_ACTION: "withdraw"}[_action_id(body)]
    error = answer_challenge(_action_value(body), body["user"]["id"], verb,
                             client, logger=logger)
    if error:
        _only_you(respond, error)
        return
    said = {"accept": ":crossed_swords: You're on. Fixture's up.",
            "decline": ":wave: Turned it down.",
            "withdraw": ":wastebasket: Taken back."}[verb]
    _only_you(respond, said)


def handle_answer_command(command, respond, client=None, logger=None):
    """`/tt accept 4` · `/tt decline 4` — for when the DM never arrived."""
    sub, rest = parsing.split_subcommand(command.get("text", ""))
    verb = {"accept": "accept", "decline": "decline",
            "withdraw": "withdraw"}[sub]
    partner = next(iter(parsing.mentions_in(rest)), None)
    if partner:
        rest = parsing.MENTION_RE.sub(" ", rest)
    cid = rest.strip().lstrip("#")
    if not cid.isdigit():
        user = command["user_id"]
        mine = [r for r in challenge.live()
                if (challenge.may_withdraw(r, user) if verb == "withdraw"
                    else challenge.may_answer(r, user))]
        if not mine:
            respond(":grey_question: No challenges of yours to take back."
                    if verb == "withdraw" else
                    ":grey_question: No open challenges waiting on you.")
            return
        lines = [f"`#{r['id']}`  {fmt_side(r['side_a'])} — "
                 f"{challenge.length_note(r)}" for r in mine]
        respond(f":crossed_swords: *Which one?*  `/tt {verb} {mine[0]['id']}`\n"
                + "\n".join(lines))
        return
    error = answer_challenge(cid, command["user_id"], verb, client,
                             logger=logger, partner=partner)
    respond(error or {"accept": ":crossed_swords: You're on.",
                      "decline": ":wave: Turned it down.",
                      "withdraw": ":wastebasket: Taken back."}[verb])


def handle_challenges(command, respond):
    """`/tt challenges` — what's outstanding, and who owes an answer."""
    now = store.now_ist()
    records = challenge.live()
    if not records:
        respond(":crossed_swords: No open challenges. "
                "`/tt challenge @bob best of 5` starts one.")
        return
    lines = [":crossed_swords: *Open challenges*"]
    for r in records:
        facing = ("*anyone*" if challenge.is_open_call(r)
                  else fmt_side(r["side_b"]))
        waiting = (f"_{challenge.band_note(r)}"
                   + (", in pairs" if challenge.side_size(r) > 1 else "")
                   + f" · `/tt accept {r['id']}`_"
                   if challenge.is_open_call(r)
                   else f"_waiting on {fmt_side(r['side_b'])}_")
        lines.append(f"`#{r['id']}`  {fmt_side(r['side_a'])} vs {facing} — "
                     f"{challenge.length_note(r)}"
                     + (f" · {fmt_when(r, now)}" if challenge.starts_at(r) else "")
                     + f"  {waiting}")
    respond("\n".join(lines))


def may_move(record, user):
    """The players, whoever set it up, or an admin — the same people who may
    call it off. Moving a match is the smaller version of that decision."""
    allowed = set(record["side_a"] + record["side_b"] + [record["created_by"]])
    return user in allowed or is_admin(user)


def apply_reschedule(sid, when, user, client, now=None, logger=None):
    """Move a fixture and tell everyone. Returns a message for the caller, or
    None if it worked. Shared by the typed command and the modal."""
    now = now or store.now_ist()
    record = betting.get(sid)
    if not record:
        return ":information_source: There's no fixture by that number."
    if not may_move(record, user):
        return (":lock: Only the players or whoever set it up can move that one.")
    was = betting.starts_at(record)
    ok, why = betting.reschedule(record, when, by=user, now=now)
    if not ok:
        return f":warning: {why}"

    _refresh_with(record, client, fixture_blocks(record, now),
                  f"{plain_side(record['side_a'])} vs {plain_side(record['side_b'])}, "
                  f"{fmt_when(record, now)}.", logger=logger)
    # Also said out loud. Editing a message people scrolled past days ago is not
    # telling them — and they have money on it.
    note = (f":clock3: <@{user}> moved *{fmt_side(record['side_a'])} vs "
            f"{fmt_side(record['side_b'])}* to *{fmt_when(record, now)}*"
            + (f" (was {fmt_when({'starts_at': store.stamp(was)}, now)})" if was else "")
            + ".")
    pot = betting.pool(sid)["total"]
    if pot:
        note += (f" {fmt_spins(pot)} already staked — stakes stand, nobody is "
                 "refunded.")
    if record.get("state") == "closed":
        note += (" Betting stays shut: the window closed when it was first due, "
                 "and a postponement shouldn't reopen it.")
    _announce_fixture(record, client, note, logger=logger)
    return None


def _announce_fixture(record, client, text, logger=None):
    """A short note in the fixture's own channel, threaded under it when we know
    where it lives so it doesn't shout twice."""
    channel = record.get("channel")
    if not (client and channel):
        return
    try:
        client.chat_postMessage(channel=channel, text=text,
                                thread_ts=record.get("ts") or None,
                                reply_broadcast=bool(record.get("ts")))
    except Exception as e:
        (logger or log).warning("could not announce fixture %s: %s",
                                record.get("id"), e)


def handle_reschedule(command, respond, client=None, logger=None):
    """`/tt reschedule 6 7pm`. Bare, it says which fixtures you could move."""
    caller = command["user_id"]
    _, rest = parsing.split_subcommand(command.get("text", ""))
    now = store.now_ist()
    if not rest.strip():
        mine = [r for r in betting.live() if may_move(r, caller)]
        if not mine:
            respond(":grey_question: You've no fixtures to move. "
                    "`/tt schedule @bob 6pm` puts one up.")
            return
        lines = [f"`#{r['id']}`  {fmt_side(r['side_a'])} vs {fmt_side(r['side_b'])}"
                 f"  ·  {fmt_when(r, now)}" for r in mine]
        respond(":clock3: *Move which one?*  `/tt reschedule "
                f"{mine[0]['id']} 7pm`\n" + "\n".join(lines))
        return
    try:
        sid, when = parsing.parse_reschedule(rest, now)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return
    error = apply_reschedule(sid, when, caller, client, now, logger)
    if error:
        respond(error)
    else:
        respond(f":white_check_mark: Moved `#{sid}`.")


def build_reschedule_modal(record, now=None):
    """Just the time — moving a fixture is moving *this* match, and changing who
    is playing would make it a different one with the same pot on it."""
    now = now or store.now_ist()
    when = betting.starts_at(record) or _default_start(now)
    sid = record["id"]
    staked = betting.pool(sid)["total"]
    context = (f"{plain_side(record['side_a'])} vs {plain_side(record['side_b'])}"
               f" · currently {fmt_when(record, now)}")
    if staked:
        context += f" · {staked:,} {betting.CURRENCY} staked, which stands"
    blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": context}]},
        {"type": "input", "block_id": "when",
         "label": {"type": "plain_text", "text": "New start time"},
         "hint": {"type": "plain_text",
                  "text": "Everyone who backed it keeps their stake."},
         "element": {"type": "datetimepicker", "action_id": "v",
                     "initial_date_time": int(max(when, _default_start(now)).timestamp())}},
    ]
    return {
        "type": "modal",
        "callback_id": RESCHEDULE_MODAL,
        "private_metadata": str(sid),
        "title": {"type": "plain_text", "text": "Move a match"},
        "submit": {"type": "plain_text", "text": "Move it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def handle_reschedule_button(body, client, respond, logger=None):
    sid = _action_value(body)
    record = betting.get(sid)
    if not record:
        _only_you(respond, ":information_source: That fixture has gone.")
        return
    user = body["user"]["id"]
    if not may_move(record, user):
        _only_you(respond, ":lock: Only the players or whoever set it up can "
                           "move that one.")
        return
    try:
        client.views_open(trigger_id=body["trigger_id"],
                          view=build_reschedule_modal(record))
    except Exception as e:
        (logger or log).warning("reschedule modal failed: %s", e)
        _only_you(respond, ":warning: Couldn't open the form — type it instead: "
                           f"`/tt reschedule {sid} 7pm`")


def handle_reschedule_modal(ack, body, view, client=None, logger=None):
    sid = view.get("private_metadata") or ""
    epoch = _modal_value(view["state"]["values"], "when", "selected_date_time")
    now = store.now_ist()
    if not epoch:
        ack(response_action="errors", errors={"when": "Pick when it starts."})
        return
    when = datetime.fromtimestamp(int(epoch), tz=store.IST)
    if when <= now:
        ack(response_action="errors",
            errors={"when": "That's already past — pick a time still to come."})
        return
    if when - now > timedelta(days=parsing.MAX_LEAD_DAYS):
        ack(response_action="errors",
            errors={"when": f"More than {parsing.MAX_LEAD_DAYS} days out."})
        return
    ack()
    user = body["user"]["id"]
    error = apply_reschedule(sid, when, user, client, now, logger)
    if error:
        _dm(client, user, error, logger=logger)


def _refresh_with(record, client, blocks, text, logger=None):
    if not (client and record.get("channel") and record.get("ts")):
        return
    try:
        client.chat_update(channel=record["channel"], ts=record["ts"],
                           blocks=blocks, text=text)
    except Exception as e:
        (logger or log).warning("fixture %s update failed: %s", record["id"], e)


def _settle_bets(blob, client, logger=None):
    """Settle any fixture this session decided, without ever risking the result.

    The rating is already written by the time this runs; a wallet problem must
    not turn a confirmed match into an error the player sees.
    """
    try:
        return settle_fixture_for(blob, client, logger=logger)
    except Exception:
        (logger or log).exception("settling bets for match %s failed", blob.get("id"))
        return None


def settle_fixture_for(blob, client, now=None, logger=None):
    """Settle the fixture a just-confirmed session decided, if there was one.

    Matched on the players alone, so nobody has to quote a fixture id when they
    log the result — the thing people forget is exactly the thing that would
    strand a pot.
    """
    record = betting.find_for_result(blob["side_a"], blob["side_b"])
    if not record or not betting.claim(record["id"]):
        return None
    winner = betting.winner_from(record, blob["side_a"], blob["games_a"], blob["games_b"])
    pot = betting.pool(record["id"])
    settled = betting.settle(record, winner, match_id=blob["id"], now=now)
    _refresh_with(settled, client, settled_fixture_blocks(settled, pot),
                  "Fixture settled.", logger=logger)
    for uid, paid in (settled.get("payouts") or {}).items():
        staked = (settled.get("staked") or {}).get(uid, 0)
        _dm(client, uid, _settlement_note(settled, uid, staked, paid), logger=logger)
    return settled


def _settlement_note(record, uid, staked, paid):
    net = paid - staked
    head = f"Fixture `#{record['id']}` settled."
    if record["winner"] == "draw":
        return (f":moneybag: {head} It was a draw — your {fmt_spins(staked)} "
                "came back.")
    if not paid:
        return (f":chart_with_downwards_trend: {head} Your {fmt_spins(staked)} "
                f"went to the other side. Balance: *{fmt_spins(betting.balance(uid))}*.")
    if net == 0:
        return (f":moneybag: {head} Nobody backed the winner, so your "
                f"{fmt_spins(staked)} came back.")
    return (f":tada: {head} You staked {fmt_spins(staked)} and took back "
            f"*{fmt_spins(paid)}* — up {fmt_spins(net)}. "
            f"Balance: *{fmt_spins(betting.balance(uid))}*.")


def settled_fixture_blocks(record, pot):
    a, b = fmt_side(record["side_a"]), fmt_side(record["side_b"])
    winner = record.get("winner")
    if winner == "draw":
        head = f":table_tennis_paddle_and_ball: *{a}* drew with *{b}*"
    else:
        won, lost = (a, b) if winner == "a" else (b, a)
        head = f":table_tennis_paddle_and_ball: *{won}* beat *{lost}*"
    lines = [head]
    paid = record.get("payouts") or {}
    staked = record.get("staked") or {}
    winners = sorted(((u, p - staked.get(u, 0)) for u, p in paid.items() if p),
                     key=lambda i: -i[1])
    if not staked:
        lines.append("_Nobody had a stake on this one._")
    elif winner == "draw" or all(p - staked.get(u, 0) == 0 for u, p in paid.items()):
        lines.append(f"_Every stake refunded — {fmt_spins(sum(staked.values()))}._")
    else:
        lines.append(f"{fmt_spins(sum(staked.values()))} in the pot.")
        for uid, net in winners[:8]:
            lines.append(f"<@{uid}>  +{fmt_spins(net)}")
    return [_section("\n".join(lines)),
            _context(f"Fixture `#{record['id']}` · settled from match "
                     f"`#{record.get('match_id') or '?'}`")]


def fixture_detail(record, caller=None):
    """One fixture in full: every stake, and what each would return."""
    pot = betting.pool(record["id"])
    state = {"open": "betting open", "closed": "betting closed",
             "settled": "settled", "void": "called off"}.get(record.get("state"), "")
    lines = [f":date: *{fmt_side(record['side_a'])}* vs *{fmt_side(record['side_b'])}*",
             f"_Fixture `#{record['id']}` · {fmt_when(record)} · {state}_", ""]
    if not pot["total"]:
        lines.append("_Nobody has staked anything yet._")
        return "\n".join(lines)

    lines.append(f":moneybag: *{fmt_spins(pot['total'])}* in the pot")
    for side, uids in (("a", record["side_a"]), ("b", record["side_b"])):
        staked, ret = pot[side], betting.projected(pot, side)
        lines.append("")
        lines.append(f"*{fmt_side(uids)}* — {fmt_spins(staked)}"
                     + (f" · pays *{ret:.2f}×*" if ret else " · _no takers_"))
        rows = sorted(((u, a) for u, (s, a) in pot["bets"].items() if s == side),
                      key=lambda i: (-i[1], i[0]))
        for uid, amount in rows:
            would = int(amount * pot["total"] / staked) if staked else 0
            mine = ("a" if uid in record["side_a"]
                    else "b" if uid in record["side_b"] else None)
            note = ""
            if mine and mine != side:
                note = "  :eyes: _playing, backed the other side_"
            elif mine:
                note = "  _playing_"
            lines.append(f"　<@{uid}>  {amount:,} → *{would:,}*{note}")
        if not rows:
            lines.append("　_nobody yet_")
    if caller:
        lines.append(f"\n_Your balance: *{fmt_spins(betting.balance(caller))}*._")
    return "\n".join(lines)


def handle_transfer(command, respond, client=None, bot_id=None, logger=None):
    """`/tt transfer @bob 500` — move spins. Admin only.

    Two forms: out of your own wallet, or between two other people. Both are
    zero-sum, so nothing here mints. Restricted because a wallet you didn't
    agree to empty is not something any player should be able to reach.
    """
    caller = command["user_id"]
    if not is_admin(caller):
        respond(f":lock: Only an admin can move {betting.CURRENCY}. "
                f"`/tt wallet` shows yours.")
        return
    _, rest = parsing.split_subcommand(command.get("text", ""))
    try:
        sender, recipient, amount = parsing.parse_transfer(rest, caller, bot_id)
    except parsing.ParseError as e:
        respond(f":warning: {e}")
        return

    ok, message = betting.transfer(sender, recipient, amount, by=caller)
    if not ok:
        respond(f":warning: {message}")
        return
    respond(f":money_with_wings: {message}  "
            f"<@{sender}> now has *{fmt_spins(betting.balance(sender))}*, "
            f"<@{recipient}> *{fmt_spins(betting.balance(recipient))}*.")

    # Tell the people whose wallets moved. A balance changing without warning is
    # the sort of thing that reads as a bug.
    by = "" if caller == sender else f" <@{caller}> moved it."
    _dm(client, recipient,
        f":money_with_wings: <@{sender}> sent you *{fmt_spins(amount)}*.{by} "
        f"You now have *{fmt_spins(betting.balance(recipient))}*.", logger=logger)
    if caller != sender:
        _dm(client, sender,
            f":money_with_wings: *{fmt_spins(amount)}* went from your wallet to "
            f"<@{recipient}>, moved by <@{caller}>. You have "
            f"*{fmt_spins(betting.balance(sender))}*.", logger=logger)


def handle_wallet(command, respond):
    uid = command["user_id"]
    betting.ensure_wallets([uid])
    held = betting.balance(uid)
    lines = [f":moneybag: You have *{fmt_spins(held)}*."]
    entries = betting.ledger(uid, limit=6)
    if entries:
        lines.append("")
        for entry in entries:
            sign = "+" if entry["delta"] > 0 else ""
            lines.append(f"`{sign}{entry['delta']:>5}`  {entry['reason']}  "
                         f"_{fmt_ago(entry['at'])}_")
    else:
        stipend = (f", plus {fmt_spins(betting.WEEKLY_STIPEND)} a week"
                   if betting.WEEKLY_STIPEND > 0 else "")
        lines.append(f"_Everyone starts with {fmt_spins(betting.START_SPINS)}"
                     f"{stipend}._")
    rank, size = wallet_rank_of(uid)
    if rank and size > 1:
        lines.append(f"\n_#{rank} of {size} wallets · `/tt rich` for the table · "
                     "`/tt book` for what's open to bet on._")
    else:
        lines.append("\n_`/tt book` for what's open to bet on._")
    respond("\n".join(lines))


RICH_LIMIT = 20


def wallet_rank_of(uid):
    """(rank, wallets) for one player on the spins table."""
    ranked = betting.standings(store.player_ids())
    for i, (u, _, _) in enumerate(ranked, start=1):
        if u == uid:
            return i, len(ranked)
    return None, len(ranked)


def rich_text(ranked, limit=RICH_LIMIT, title=f"Who's rich — {betting.CURRENCY}",
              circulating=None):
    """The spins leaderboard. Shared by `/tt rich` and anything else that wants
    to say who is up. `ranked` is what betting.standings() returns."""
    if not ranked:
        return (f":moneybag: *{title}*\n_Nobody has a wallet yet — everyone opens with "
                f"{fmt_spins(betting.START_SPINS)}._")
    lines = [f":moneybag: *{title}*"]
    for i, (uid, held, net) in enumerate(ranked[:limit]):
        badge = MEDALS[i] if i < 3 else f"`{i + 1:>2}.`"
        move = f"`{net:+,}`" if net else "`   —`"
        lines.append(f"{badge}  <@{uid}> — *{fmt_spins(held)}*  {move}")
    if len(ranked) > limit:
        lines.append(f"_…and {len(ranked) - limit} more._")
    # Passed in, not read here: a stake has left its wallet but not the economy,
    # so summing this table under-reports while any fixture is open. Kept as an
    # argument so the renderer stays pure.
    total = circulating if circulating is not None else sum(h for _, h, _ in ranked)
    lines.append(f"\n_{fmt_spins(total)} in circulation across {len(ranked)} wallets"
                 f"{', open bets included' if circulating is not None else ''}. "
                 f"Nothing mints them — a spin won is a spin somebody else lost._")
    return "\n".join(lines)


def handle_rich(respond):
    uids = store.player_ids()
    respond(rich_text(betting.standings(uids), circulating=betting.circulating(uids)))


def titles_text(table, names=None):
    """Every title and who holds it. The unheld ones are listed too — the answer
    to "what can I win here" includes whatever is currently going spare."""
    lines = [":military_medal: *Titles*"]
    for title, uid in awards.holder_rows(table):
        who = f"<@{uid}>" if uid else "_going spare_"
        lines.append(f"*{title.name}* — {who}\n_{title.blurb}._")
    url = ladder_url()
    lines.append(f"\n_Worked out from the results, never stored"
                 + (f" · {url}/titles_" if url else "_"))
    return "\n".join(lines)


def handle_titles(respond):
    respond(titles_text(awards.current()))


def handle_book(command, respond):
    """Everything with a betting window open or a result outstanding.
    `/tt book 6` gives one fixture in full."""
    _, rest = parsing.split_subcommand(command.get("text", ""))
    wanted = rest.strip().lstrip("#")
    if wanted:
        record = betting.get(wanted)
        if not record:
            respond(f":grey_question: No fixture `#{wanted}`.")
            return
        betting.close_if_due(record)
        respond(fixture_detail(record, command.get("user_id")))
        return
    records = [r for r in betting.live() if r.get("state") in ("open", "closed")]
    for record in records:
        betting.close_if_due(record)
    if not records:
        respond(":date: Nothing scheduled. `/tt schedule @opponent 6pm` opens one.")
        return
    lines = [":date: *The book*"]
    for record in records:
        pot = betting.pool(record["id"])
        shut = "open" if record["state"] == "open" else "closed"
        lines.append(
            f"`#{record['id']}`  {fmt_side(record['side_a'])} vs "
            f"{fmt_side(record['side_b'])} · {fmt_when(record)} · {shut} · "
            f"{fmt_spins(pot['total'])} in the pot")
    lines.append(f"\n_Balance: *{fmt_spins(betting.balance(command['user_id']))}*._")
    respond("\n".join(lines))
