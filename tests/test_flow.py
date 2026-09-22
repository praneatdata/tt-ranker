"""The whole loop through the Slack handlers: log → confirm → rating moves."""
import itertools
import json
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import bot
import elo
import standings
import store
from tests.fake_kv import FakeRedis

A, B, C, D, E = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1", "U0EEE1"
BOT = "U0BOT01"


@pytest.fixture
def fake():
    redis = FakeRedis()
    with redis.patched():
        yield redis


@pytest.fixture
def client():
    """Echoes back the channel it was posted to, so a channel post and each
    verdict DM are distinguishable. (Real Slack returns a D-id for a DM rather
    than the user id; the code stores whatever comes back either way.)"""
    c = MagicMock()
    counter = itertools.count(1)
    c.chat_postMessage.side_effect = lambda **kw: {
        "channel": kw.get("channel", "C1"), "ts": f"1700000000.{next(counter)}"}
    return c


def run(text, client, user=A, respond=None):
    """Drive `/tt <text>` the way Bolt would. trigger_id is always present on a
    real slash command and is what opens the form."""
    respond = respond or MagicMock()
    bot.handle_tt_command(
        MagicMock(), {"user_id": user, "text": text, "channel_id": "C1",
                      "trigger_id": "tid.1"},
        respond, client=client, context={"bot_user_id": BOT})
    return respond


def press(action, mid, user, client, respond=None, channel="C1", ts="1700000000.1",
          ephemeral=False):
    respond = respond or MagicMock()
    container = {"channel_id": channel, "message_ts": ts}
    if ephemeral:
        container["is_ephemeral"] = True   # as a press from /tt pending arrives
    action({"user": {"id": user}, "actions": [{"value": mid}],
            "container": container}, client, respond)
    return respond


def said(mock):
    """Everything a mock was told to say, as one searchable string.

    ensure_ascii=False so the en-dashes and emoji in the real messages survive
    the round trip and can be asserted on.
    """
    parts = []
    for call in mock.call_args_list:
        parts += [json.dumps(a, default=str, ensure_ascii=False) for a in call.args]
        parts += [json.dumps(v, default=str, ensure_ascii=False)
                  for v in call.kwargs.values()]
    return "\n".join(parts)


def posts(client):
    return client.chat_postMessage.call_args_list


def channel_post(client):
    """The most recent message that went to a channel, not a verdict DM."""
    for c in reversed(posts(client)):
        if str(c.kwargs.get("channel", "")).startswith("C"):
            return c
    return None


def dm_to(client, uid):
    """The most recent verdict DM sent to one person, or None."""
    for c in reversed(posts(client)):
        if c.kwargs.get("channel") == uid:
            return c
    return None


def dm_text(client, uid):
    """What one person's most recent DM said."""
    call = dm_to(client, uid)
    return "" if call is None else json.dumps(call.kwargs, default=str,
                                              ensure_ascii=False)


def buttons_in(call):
    if call is None:
        return []
    for b in call.kwargs.get("blocks") or []:
        if b.get("type") == "actions":
            return [e["action_id"] for e in b["elements"]]
    return []


def posted_mid(client):
    """The pending id on the most recently posted message carrying buttons."""
    for c in reversed(posts(client)):
        for b in c.kwargs.get("blocks") or []:
            if b.get("type") == "actions":
                return b["elements"][0]["value"]
    raise AssertionError("no message carried buttons")


# --- logging ---------------------------------------------------------------

def test_logging_posts_a_prompt_and_moves_nothing_yet(fake, client):
    respond = run(f"log <@{B}> 11-7 9-11 11-5", client)
    text = said(client.chat_postMessage)
    assert f"<@{A}>" in text and f"<@{B}>" in text and "11-7" in text
    assert "Confirm" in text
    assert respond.call_count == 0          # the channel message is the reply
    assert fake.data.get(store.player_key(A)) is None  # nobody rated yet


def test_the_channel_post_names_who_the_verdict_went_to(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    assert f"Sent to <@{B}> to confirm" in said(client.chat_postMessage)


def test_a_bad_command_explains_itself_privately(fake, client):
    respond = run(f"log <@{B}>", client)
    assert "No game scores" in said(respond)
    assert client.chat_postMessage.call_count == 0


def test_a_channel_it_cannot_post_in_leaves_no_orphan(fake, client):
    client.chat_postMessage.side_effect = SlackRefusal("not_in_channel")
    respond = run(f"log <@{B}> 11-7", client)
    assert "invite me" in said(respond)
    assert store.list_pending() == []


# --- confirming ------------------------------------------------------------

def test_the_opponent_confirming_applies_the_rating(fake, client):
    run(f"log <@{B}> 11-7 9-11 11-5", client)
    mid = posted_mid(client)
    press(bot.handle_confirm, mid, B, client)

    assert fake.rating(A) > elo.START_RATING > fake.rating(B)
    updated = said(client.chat_update)
    assert "beat" in updated and str(fake.rating(A)) in updated
    assert store.get_pending(mid) is None


def test_the_prompt_is_replaced_so_the_buttons_cannot_be_pressed_again(fake, client):
    run(f"log <@{B}> 11-7", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    blocks = client.chat_update.call_args.kwargs["blocks"]
    assert not any(b["type"] == "actions" for b in blocks)


def test_you_cannot_confirm_your_own_result(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    respond = press(bot.handle_confirm, posted_mid(client), A, client)
    assert "Only" in said(respond)
    assert store.get_pending(posted_mid(client)) is not None
    assert fake.data.get(store.player_key(A)) is None


def test_a_bystander_cannot_confirm(fake, client):
    run(f"log <@{B}> 11-7", client)
    respond = press(bot.handle_confirm, posted_mid(client), C, client)
    assert "Only" in said(respond)


def test_in_doubles_either_opponent_can_confirm(fake, client):
    run(f"log <@{B}> vs <@{C}> <@{D}> 11-7 11-9", client)
    assert bot.confirmers(store.get_pending(posted_mid(client))) == [C, D]
    press(bot.handle_confirm, posted_mid(client), D, client)
    assert fake.player(A)["matches"] == 1


def test_a_match_logged_by_a_bystander_can_be_confirmed_by_any_player(fake, client):
    run(f"log <@{A}> vs <@{B}> 11-7", client, user=C)
    record = store.get_pending(posted_mid(client))
    assert bot.confirmers(record) == [A, B]
    press(bot.handle_confirm, posted_mid(client), A, client)
    assert fake.player(A)["matches"] == 1


def test_two_people_confirming_at_once_rate_the_match_once(fake, client):
    run(f"log <@{B}> vs <@{C}> <@{D}> 11-7 11-9", client)
    mid = posted_mid(client)
    press(bot.handle_confirm, mid, C, client)
    rating = fake.rating(A)
    respond = press(bot.handle_confirm, mid, D, client)
    assert fake.rating(A) == rating
    assert "already been settled" in said(respond)


def test_confirming_a_vanished_match_says_so(fake, client):
    respond = press(bot.handle_confirm, "999", B, client)
    assert "already been settled" in said(respond)


def test_a_failure_while_rating_leaves_the_match_confirmable(fake, client, monkeypatch):
    run(f"log <@{B}> 11-7", client)
    mid = posted_mid(client)
    monkeypatch.setattr(store, "apply_match", MagicMock(side_effect=RuntimeError("boom")))
    respond = press(bot.handle_confirm, mid, B, client)
    assert "went wrong" in said(respond)
    monkeypatch.undo()
    press(bot.handle_confirm, mid, B, client)   # the retry works
    assert fake.player(A)["matches"] == 1


# --- disputing -------------------------------------------------------------

def test_disputing_throws_the_match_out(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    mid = posted_mid(client)
    press(bot.handle_dispute, mid, B, client)
    assert store.get_pending(mid) is None
    assert fake.data.get(store.player_key(A)) is None
    assert "Thrown out" in said(client.chat_update)


def test_the_reporter_can_cancel_their_own_mistake(fake, client):
    run(f"log <@{B}> 11-7", client)
    press(bot.handle_dispute, posted_mid(client), A, client)
    assert store.list_pending() == []


def test_a_bystander_cannot_dispute(fake, client):
    run(f"log <@{B}> 11-7", client)
    respond = press(bot.handle_dispute, posted_mid(client), C, client)
    assert "Only the players" in said(respond)
    assert store.list_pending()


# --- nobody presses anything ----------------------------------------------

def test_an_ignored_match_applies_itself_after_the_window(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    mid = posted_mid(client)
    later = store.now_ist() + timedelta(hours=store.AUTO_CONFIRM_HOURS + 1)

    assert standings.sweep_pending(client, now=store.now_ist())["applied"] == []
    result = standings.sweep_pending(client, now=later)

    assert result["applied"] == [mid]
    assert fake.rating(A) > elo.START_RATING
    assert "auto-confirmed" in said(client.chat_update)


def test_the_sweep_leaves_fresh_matches_alone(fake, client):
    run(f"log <@{B}> 11-7", client)
    assert standings.sweep_pending(client)["still_waiting"] == 1
    assert store.list_pending()


def test_a_dry_sweep_changes_nothing(fake, client):
    run(f"log <@{B}> 11-7", client)
    later = store.now_ist() + timedelta(days=2)
    assert standings.sweep_pending(client, now=later, dry_run=True)["applied"]
    assert store.list_pending()          # still there
    assert fake.data.get(store.player_key(A)) is None


# --- the read-only commands ------------------------------------------------

def test_register_then_register_again(fake, client):
    assert str(elo.START_RATING) in said(run("register", client))
    assert "already on the ladder" in said(run("register", client))


def test_the_card_shows_the_record(fake, client):
    run(f"log <@{B}> 11-7 9-11 11-5", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    card = said(run("me", client))
    assert "1-0" in card and str(fake.rating(A)) in card


def test_the_card_of_a_stranger(fake, client):
    assert "isn't on the ladder" in said(run(f"me <@{C}>", client))


def test_the_board_separates_the_settled_from_the_settling(fake, client):
    for opponent in (B, C, D):
        run(f"log <@{opponent}> 11-7 11-9", client)
        press(bot.handle_confirm, posted_mid(client), opponent, client)
    board = said(run("board", client))
    assert "Still placing" in board and f"<@{A}>" in board


def test_the_board_is_ordered_by_rating(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "PLACEMENT_GAMES", 1)
    run(f"log <@{B}> 11-2 11-3", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    board = bot.board_text(store.all_players())
    assert board.index(f"<@{A}>") < board.index(f"<@{B}>")


def test_history_lists_the_match(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert "2–0" in said(run("history", client))


def test_pending_lists_what_is_waiting(fake, client):
    run(f"log <@{B}> 11-7", client)
    listed = said(run("pending", client))
    assert f"#{posted_mid(client)}" in listed and f"<@{B}>" in listed


def test_pending_when_everything_is_settled(fake, client):
    assert "Nothing waiting" in said(run("pending", client))


def test_undo_rolls_the_last_match_back(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert fake.rating(A) > elo.START_RATING

    assert "Undid" in said(run("undo", client))
    assert fake.rating(A) == elo.START_RATING
    assert fake.rating(B) == elo.START_RATING


def test_undo_with_nothing_to_undo(fake, client):
    assert "haven't logged any" in said(run("undo", client))


def test_undo_will_not_erase_a_later_match(fake, client):
    """A undoes their own match, but B has played again since — rewinding B to
    the snapshot would silently wipe that later result too."""
    run(f"log <@{B}> 11-7", client, user=A)
    press(bot.handle_confirm, posted_mid(client), B, client)
    run(f"log <@{C}> 11-9", client, user=B)
    press(bot.handle_confirm, posted_mid(client), C, client)

    rating = fake.rating(A)
    assert "already played another match" in said(run("undo", client, user=A))
    assert fake.rating(A) == rating


def test_odds_reads_the_gap(fake, client):
    store.ensure_players([A, B])
    store.kv.hset(store.player_key(B), "rating", 1400)
    odds = said(run(f"odds <@{B}>", client))
    assert "9%" in odds and "91%" in odds


def test_help_needs_no_database(fake, client):
    assert "TT Ranker" in said(run("help", client))


def test_without_a_database_it_says_so(client, monkeypatch):
    monkeypatch.setattr(bot.kv, "kv_available", lambda: False)
    assert "No database" in said(run("board", client))


def test_an_unexpected_failure_is_not_a_stack_trace(fake, client, monkeypatch):
    monkeypatch.setattr(store, "all_players", MagicMock(side_effect=RuntimeError("boom")))
    assert "went wrong" in said(run("board", client))


# --- auto-registration on joining the channel ------------------------------

def joined(channel, user, client, context=None):
    bot.handle_member_joined({"channel": channel, "user": user}, client=client,
                             context=context if context is not None else {"bot_user_id": BOT})


def test_joining_the_home_channel_puts_you_on_the_ladder(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    joined("C_TT", B, client)
    assert store.get_player(B)["rating"] == elo.START_RATING
    dm = said(client.chat_postMessage)
    assert f"<@{B}>" in dm and "Welcome" in dm
    assert client.chat_postMessage.call_args.kwargs["channel"] == B   # a DM, not the channel


def test_joining_some_other_channel_does_nothing(fake, client, monkeypatch):
    """The bot being invited somewhere busy for one match must not enrol that
    channel's whole membership."""
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    joined("C_RANDOM", B, client)
    assert store.get_player(B) is None
    assert client.chat_postMessage.call_count == 0


def test_the_bot_joining_is_not_a_new_player(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    joined("C_TT", BOT, client)
    assert store.get_player(BOT) is None


def test_rejoining_does_not_welcome_you_twice(fake, client, monkeypatch):
    """Slack retries event deliveries; ensure_players only reports genuinely new
    uids, so the second delivery is silent."""
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    joined("C_TT", B, client)
    joined("C_TT", B, client)
    assert client.chat_postMessage.call_count == 1


def test_a_failed_welcome_dm_still_registers_the_player(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    client.chat_postMessage.side_effect = Exception("cannot_dm_bot")
    joined("C_TT", B, client)
    assert store.get_player(B)["rating"] == elo.START_RATING


def test_auto_registration_is_off_without_a_home_channel(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "")
    joined("C_TT", B, client)
    assert store.get_player(B) is None


# --- /tt sync --------------------------------------------------------------

def members(client, *uids, pages=None):
    """Stub conversations.members, optionally paginated."""
    if pages:
        client.conversations_members.side_effect = [
            {"members": page, "response_metadata": {"next_cursor": cur}}
            for page, cur in pages]
    else:
        client.conversations_members.return_value = {"members": list(uids)}


def test_sync_backfills_everyone_already_in_the_channel(fake, client):
    members(client, A, B, C, BOT)
    out = said(run("sync", client))
    assert "Added *3*" in out and f"<@{C}>" in out
    assert sorted(store.all_players()) == sorted([A, B, C])   # not the bot


def test_sync_a_second_time_adds_nobody(fake, client):
    members(client, A, B)
    run("sync", client)
    assert "already on the ladder" in said(run("sync", client))


def test_sync_follows_slack_pagination(fake, client):
    members(client, pages=[([A, B], "cur1"), ([C, D], "")])
    run("sync", client)
    assert sorted(store.all_players()) == sorted([A, B, C, D])


def test_sync_says_what_to_fix_when_it_cannot_read_the_channel(fake, client):
    client.conversations_members.side_effect = Exception("missing_scope")
    out = said(run("sync", client))
    assert "channels:read" in out and "missing_scope" in out
    assert store.all_players() == {}


def test_sync_mentions_auto_registration_only_in_the_home_channel(fake, client, monkeypatch):
    members(client, A, B)
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C1")     # run() posts from C1
    assert "automatically" in said(run("sync", client))
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_OTHER")
    members(client, C, D)
    assert "automatically" not in said(run("sync", client))


# --- the guided form -------------------------------------------------------

def submit(state, client, user=A, channel="C1", respond=None):
    ack = MagicMock()
    bot.handle_log_modal(ack, {"user": {"id": user}},
                         {"state": {"values": state}, "private_metadata": channel},
                         client=client)
    return ack


def form_state(side_a, side_b, games):
    return {"side_a": {"v": {"selected_users": side_a}},
            "side_b": {"v": {"selected_users": side_b}},
            "games": {"v": {"value": games}}}


def test_a_bare_log_opens_the_form(fake, client):
    run("log", client)
    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == bot.LOG_MODAL
    assert view["private_metadata"] == "C1"
    assert [b["block_id"] for b in view["blocks"]] == ["side_a", "side_b", "games"]


def test_the_form_pre_picks_you_on_your_own_side(fake, client):
    run("log", client)
    view = client.views_open.call_args.kwargs["view"]
    assert view["blocks"][0]["element"]["initial_users"] == [A]


def test_the_form_caps_each_side_at_two(fake, client):
    run("log", client)
    view = client.views_open.call_args.kwargs["view"]
    assert all(b["element"]["max_selected_items"] == 2 for b in view["blocks"][:2])


def test_a_form_that_cannot_open_falls_back_to_the_typed_form(fake, client):
    client.views_open.side_effect = Exception("expired_trigger_id")
    assert "type it instead" in said(run("log", client))


def test_submitting_the_form_logs_the_match(fake, client):
    ack = submit(form_state([A], [B], "11-7 9-11 11-5"), client)
    ack.assert_called_once_with()          # closed cleanly, no errors
    record = store.get_pending(posted_mid(client))
    assert record["side_a"] == [A] and record["side_b"] == [B]
    assert record["games"] == [[11, 7], [9, 11], [11, 5]]


def test_the_form_logs_doubles_from_the_pickers_alone(fake, client):
    submit(form_state([A, B], [C, D], "11-7 11-9"), client)
    record = store.get_pending(posted_mid(client))
    assert record["side_a"] == [A, B] and record["side_b"] == [C, D]


def test_a_form_match_confirms_like_any_other(fake, client):
    submit(form_state([A], [B], "11-7 11-9"), client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert fake.rating(A) > elo.START_RATING > fake.rating(B)


@pytest.mark.parametrize("state,field,fragment", [
    (form_state([A], [B], "not scores"), "games", "No game scores"),
    (form_state([A], [B], "11-11"), "games", "has to win"),
    (form_state([A], [B, C], "11-7"), "side_b", "Uneven sides"),
    (form_state([A], [A], "11-7"), "side_b", "both sides"),
    (form_state([A], [], "11-7"), "side_b", "who played"),
])
def test_form_errors_come_back_on_the_field(fake, client, state, field, fragment):
    """Attached to the field rather than posted after the modal closes, so a typo
    is one correction instead of a retype."""
    ack = submit(state, client)
    kwargs = ack.call_args.kwargs
    assert kwargs["response_action"] == "errors"
    assert fragment in kwargs["errors"][field]
    assert store.list_pending() == []      # nothing parked on a rejected form


def test_a_form_match_that_cannot_be_posted_is_explained_by_dm(fake, client):
    client.chat_postMessage.side_effect = Exception("not_in_channel")
    submit(form_state([A], [B], "11-7"), client)
    assert client.chat_postMessage.call_args.kwargs["channel"] == A   # DM to the logger
    assert store.list_pending() == []


# --- the pinnable intro ----------------------------------------------------

def test_intro_posts_the_how_it_works_message(fake, client):
    respond = run("intro", client)
    posted = said(client.chat_postMessage)
    assert "Welcome to the table tennis ladder" in posted
    assert "/tt log @opponent" in posted
    assert "Pin to channel" in said(respond)


def test_the_intro_quotes_the_constants_the_code_actually_runs_on(fake, client):
    """It's a command rather than a wiki page precisely so it can't drift."""
    run("intro", client)
    posted = said(client.chat_postMessage)
    assert str(elo.START_RATING) in posted
    assert str(bot.PLACEMENT_GAMES) in posted
    assert str(store.AUTO_CONFIRM_HOURS) in posted


def test_intro_falls_back_to_showing_the_caller(fake, client):
    client.chat_postMessage.side_effect = Exception("not_in_channel")
    assert "Welcome to the table tennis ladder" in said(run("intro", client))


@pytest.mark.parametrize("alias", ["intro", "welcome", "rules", "howto"])
def test_intro_aliases(alias):
    import parsing
    assert parsing.split_subcommand(alias)[0] == "intro"


# --- per-game scoring, end to end -----------------------------------------

def test_a_longer_session_moves_ratings_further(fake, client):
    run(f"log <@{B}> " + " ".join(["11-7"] * 3), client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    short = fake.rating(A) - elo.START_RATING

    run(f"log <@{C}> " + " ".join(["11-7"] * 10), client)
    press(bot.handle_confirm, posted_mid(client), C, client)
    long_ = fake.rating(A) - elo.START_RATING - short
    assert long_ > short > 0


def test_an_even_session_leaves_both_ratings_untouched(fake, client):
    run(f"log <@{B}> 11-7 7-11 11-9 9-11", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert fake.rating(A) == fake.rating(B) == elo.START_RATING
    assert fake.player(A)["games_won"] == 2 and fake.player(A)["games_lost"] == 2


def test_the_board_counts_games_not_sessions(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "PLACEMENT_GAMES", 5)
    run(f"log <@{B}> 11-7 11-9 11-8 11-6 11-5", client)   # one session, five games
    press(bot.handle_confirm, posted_mid(client), B, client)
    board = bot.board_text(store.all_players())
    assert "Still placing" not in board      # five games qualifies them both
    assert f"<@{A}>" in board


def test_a_long_session_is_still_one_undoable_entry(fake, client):
    run(f"log <@{B}> " + " ".join(["11-7"] * 8), client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert "Undid" in said(run("undo", client))
    assert fake.rating(A) == fake.rating(B) == elo.START_RATING
    assert fake.player(A)["games_won"] == 0


# --- the shortcuts-menu entry ----------------------------------------------

def shortcut(client, user=A):
    ack = MagicMock()
    bot.handle_log_shortcut(ack, {"user": {"id": user}, "trigger_id": "tid.9"},
                            client=client)
    return ack


def test_the_shortcut_opens_the_same_form(fake, client):
    ack = shortcut(client)
    ack.assert_called_once_with()
    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == bot.LOG_MODAL
    assert view["blocks"][0]["element"]["initial_users"] == [A]


def test_the_shortcut_form_asks_which_channel(fake, client):
    """A global shortcut carries no channel context, so it has to ask."""
    shortcut(client)
    blocks = client.views_open.call_args.kwargs["view"]["blocks"]
    assert [b["block_id"] for b in blocks] == ["side_a", "side_b", "games", "channel"]
    assert blocks[-1]["element"]["type"] == "conversations_select"


def test_the_channel_picker_starts_on_the_home_channel(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    shortcut(client)
    picker = client.views_open.call_args.kwargs["view"]["blocks"][-1]["element"]
    assert picker["initial_conversation"] == "C_TT"


def test_the_picker_has_no_preset_without_a_home_channel(fake, client, monkeypatch):
    """initial_conversation pointing at nothing would stop the view opening."""
    monkeypatch.setattr(bot, "HOME_CHANNEL", "")
    shortcut(client)
    picker = client.views_open.call_args.kwargs["view"]["blocks"][-1]["element"]
    assert "initial_conversation" not in picker


def test_the_slash_command_form_has_no_channel_picker(fake, client):
    """It already knows where it was run."""
    run("log", client)
    blocks = client.views_open.call_args.kwargs["view"]["blocks"]
    assert "channel" not in [b["block_id"] for b in blocks]


def test_a_session_logged_from_the_shortcut_posts_to_the_chosen_channel(fake, client):
    state = form_state([A], [B], "11-7 9-11 11-5")
    state["channel"] = {"v": {"selected_conversation": "C_PICKED"}}
    submit(state, client, channel="")           # no private_metadata, as a shortcut
    assert channel_post(client).kwargs["channel"] == "C_PICKED"
    assert store.get_pending(posted_mid(client))["side_b"] == [B]


def test_a_shortcut_session_confirms_like_any_other(fake, client):
    state = form_state([A], [B], "11-7 11-9")
    state["channel"] = {"v": {"selected_conversation": "C_PICKED"}}
    submit(state, client, channel="")
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert fake.rating(A) > elo.START_RATING > fake.rating(B)


def test_the_shortcut_form_rejects_an_empty_channel(fake, client):
    state = form_state([A], [B], "11-7")
    state["channel"] = {"v": {"selected_conversation": None}}
    ack = submit(state, client, channel="")
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "channel" in ack.call_args.kwargs["errors"]
    assert store.list_pending() == []


def test_a_shortcut_that_cannot_open_is_explained_by_dm(fake, client):
    client.views_open.side_effect = Exception("expired_trigger_id")
    shortcut(client)
    assert client.chat_postMessage.call_args.kwargs["channel"] == A
    assert "/tt log @opponent" in said(client.chat_postMessage)


# --- a bystander's click must not touch the channel's view -----------------

def ephemeral_calls(respond):
    return [c.kwargs for c in respond.call_args_list
            if c.kwargs.get("response_type") == "ephemeral"]


def test_a_bystander_pressing_confirm_leaves_the_prompt_alone(fake, client):
    """A reply to an interactive component replaces the message it came from
    unless told otherwise — so without replace_original=False a passer-by's
    click would wipe the buttons for the people who can actually press them."""
    run(f"log <@{B}> 11-7 11-9", client)
    mid = posted_mid(client)
    respond = press(bot.handle_confirm, mid, C, client)

    assert all(c["replace_original"] is False for c in ephemeral_calls(respond))
    assert client.chat_update.call_count == 0      # channel message untouched
    assert store.get_pending(mid) is not None      # still confirmable
    press(bot.handle_confirm, mid, B, client)      # and B can still settle it
    assert fake.rating(A) > elo.START_RATING


def test_a_bystander_pressing_dispute_leaves_the_prompt_alone(fake, client):
    run(f"log <@{B}> 11-7", client)
    mid = posted_mid(client)
    respond = press(bot.handle_dispute, mid, C, client)
    assert all(c["replace_original"] is False for c in ephemeral_calls(respond))
    assert client.chat_update.call_count == 0
    assert store.get_pending(mid) is not None


@pytest.mark.parametrize("user,action", [
    (A, bot.handle_confirm),      # the reporter confirming their own
    (C, bot.handle_confirm),      # a bystander
    (C, bot.handle_dispute),      # a bystander
])
def test_every_refusal_is_private_and_non_destructive(fake, client, user, action):
    run(f"log <@{B}> 11-7 11-9", client)
    respond = press(action, posted_mid(client), user, client)
    calls = ephemeral_calls(respond)
    assert calls, "a refusal must say something"
    assert all(c["replace_original"] is False for c in calls)
    assert store.get_pending(posted_mid(client)) is not None


def test_settling_the_match_still_replaces_the_prompt(fake, client):
    """The guard must not have broken the case that *should* edit the message."""
    run(f"log <@{B}> 11-7", client)
    press(bot.handle_confirm, posted_mid(client), B, client)
    edited = {c.kwargs["channel"] for c in client.chat_update.call_args_list}
    assert "C1" in edited                      # the channel post became the result
    assert all(not any(b["type"] == "actions" for b in c.kwargs["blocks"])
               for c in client.chat_update.call_args_list)


# --- admin: record a result with no confirmation --------------------------

ADMIN = "U0ADMIN1"


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("TT_ADMINS", ADMIN)
    return ADMIN


def test_an_admin_session_is_rated_immediately(fake, client, admin):
    run(f"log <@{B}> 11-7 11-9 11-8", client, user=ADMIN)
    assert store.list_pending() == []            # never waits on anyone
    assert fake.rating(ADMIN) > elo.START_RATING > fake.rating(B)
    posted = said(client.chat_postMessage)
    assert "beat" in posted and str(fake.rating(ADMIN)) in posted


def test_the_admin_result_has_no_buttons_to_press(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=ADMIN)
    blocks = client.chat_postMessage.call_args.kwargs["blocks"]
    assert not any(b["type"] == "actions" for b in blocks)


def test_skipping_confirmation_is_visible_to_the_channel(fake, client, admin):
    """An admin result must not be indistinguishable from an agreed one."""
    run(f"log <@{B}> 11-7", client, user=ADMIN)
    assert f"recorded by <@{ADMIN}>" in said(client.chat_postMessage)


def test_a_non_admin_still_needs_confirmation(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    assert len(store.list_pending()) == 1
    assert fake.data.get(store.player_key(A)) is None


def test_admin_rights_come_from_the_environment(fake, client, monkeypatch):
    monkeypatch.setenv("TT_ADMINS", "")
    run(f"log <@{B}> 11-7", client, user=ADMIN)
    assert len(store.list_pending()) == 1        # nobody is an admin by default


@pytest.mark.parametrize("raw", ["U0ADMIN1", "U0ADMIN1,U0AAA1", "U0ADMIN1 U0AAA1",
                                 " U0ADMIN1 , U0AAA1 "])
def test_the_admin_list_accepts_commas_or_spaces(monkeypatch, raw):
    monkeypatch.setenv("TT_ADMINS", raw)
    assert bot.is_admin(ADMIN)
    assert not bot.is_admin("U0NOBODY")


def test_an_admin_can_settle_someone_elses_stuck_session(fake, client, admin):
    """The only way to clear a session whose players have gone quiet, short of
    waiting for the daily sweep."""
    run(f"log <@{B}> 11-7 11-9", client, user=A)
    mid = posted_mid(client)
    press(bot.handle_confirm, mid, ADMIN, client)
    assert store.get_pending(mid) is None
    assert fake.rating(A) > elo.START_RATING


def test_an_admin_can_throw_out_someone_elses_session(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    press(bot.handle_dispute, posted_mid(client), ADMIN, client)
    assert store.list_pending() == []
    assert fake.data.get(store.player_key(A)) is None


def test_a_non_admin_bystander_still_cannot(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    respond = press(bot.handle_confirm, posted_mid(client), C, client)
    assert "Only" in said(respond)
    assert store.list_pending()


def test_an_admin_session_is_undoable_like_any_other(fake, client, admin):
    run(f"log <@{B}> 11-7 11-9", client, user=ADMIN)
    assert "Undid" in said(run("undo", client, user=ADMIN))
    assert fake.rating(ADMIN) == fake.rating(B) == elo.START_RATING


def test_an_admin_session_that_cannot_be_posted_still_counts(fake, client, admin):
    """Rated before posting, so a channel problem can't silently drop a result."""
    client.chat_postMessage.side_effect = Exception("not_in_channel")
    respond = run(f"log <@{B}> 11-7", client, user=ADMIN)
    assert fake.rating(ADMIN) > elo.START_RATING
    assert "Ratings updated" in said(respond)


def test_an_admin_can_record_a_session_between_two_other_people(fake, client, admin):
    run(f"log <@{A}> vs <@{B}> 11-7 11-9", client, user=ADMIN)
    assert store.list_pending() == []
    assert fake.rating(A) > elo.START_RATING > fake.rating(B)
    assert fake.data.get(store.player_key(ADMIN)) is None   # not a player here


# --- the verdict goes to the people it costs, not the channel -------------

def test_the_channel_post_carries_no_buttons(fake, client):
    """Buttons in a channel invite everyone who can see them to press, and the
    ones who shouldn't only find out after clicking."""
    run(f"log <@{B}> 11-7 9-11 11-5", client)
    assert buttons_in(channel_post(client)) == []
    assert f"<@{A}>" in said(client.chat_postMessage)       # still shows the claim
    assert "11-7" in said(client.chat_postMessage)


def test_the_opponent_gets_the_buttons_by_dm(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    assert buttons_in(dm_to(client, B)) == [bot.CONFIRM_ACTION, bot.DISPUTE_ACTION]


def test_the_logger_gets_a_cancel_only_dm(fake, client):
    """Their mistake to take back, but not their result to wave through."""
    run(f"log <@{B}> 11-7", client)
    assert buttons_in(dm_to(client, A)) == [bot.DISPUTE_ACTION]
    assert "Cancel" in said(client.chat_postMessage)


def test_nobody_else_is_messaged(fake, client):
    run(f"log <@{B}> 11-7", client)
    assert dm_to(client, C) is None and dm_to(client, D) is None


def test_both_opponents_get_asked_in_doubles(fake, client):
    run(f"log <@{B}> vs <@{C}> <@{D}> 11-7 11-9", client)
    assert buttons_in(dm_to(client, C)) == [bot.CONFIRM_ACTION, bot.DISPUTE_ACTION]
    assert buttons_in(dm_to(client, D)) == [bot.CONFIRM_ACTION, bot.DISPUTE_ACTION]
    assert dm_to(client, B) is None          # the logger's partner is not asked


def test_the_dm_locations_are_remembered(fake, client):
    run(f"log <@{B}> 11-7", client)
    record = store.get_pending(posted_mid(client))
    assert set(record["dms"]) == {A, B}
    assert all(len(loc) == 2 for loc in record["dms"].values())


def test_confirming_updates_the_channel_and_every_dm(fake, client):
    """Otherwise live buttons sit in someone's DM for a settled session."""
    run(f"log <@{B}> vs <@{C}> <@{D}> 11-7 11-9", client)
    press(bot.handle_confirm, posted_mid(client), C, client)

    updated = {c.kwargs["channel"] for c in client.chat_update.call_args_list}
    assert updated == {"C1", A, C, D}        # channel + logger + both opponents
    for call in client.chat_update.call_args_list:
        assert not any(b["type"] == "actions" for b in call.kwargs["blocks"])


def test_disputing_updates_the_channel_and_every_dm(fake, client):
    run(f"log <@{B}> 11-7", client)
    press(bot.handle_dispute, posted_mid(client), B, client)
    updated = {c.kwargs["channel"] for c in client.chat_update.call_args_list}
    assert updated == {"C1", A, B}


def test_the_sweep_clears_every_copy_too(fake, client):
    run(f"log <@{B}> 11-7 11-9", client)
    later = store.now_ist() + timedelta(hours=store.AUTO_CONFIRM_HOURS + 1)
    standings.sweep_pending(client, now=later)
    updated = {c.kwargs["channel"] for c in client.chat_update.call_args_list}
    assert updated == {"C1", A, B}


def test_one_unreachable_person_does_not_stop_the_others(fake, client):
    def selective(**kwargs):
        if kwargs.get("channel") == A:
            raise Exception("cannot_dm_bot")
        return {"channel": kwargs.get("channel"), "ts": "1.1"}
    client.chat_postMessage.side_effect = selective

    respond = run(f"log <@{B}> 11-7", client)
    record = store.get_pending(posted_mid(client))
    assert set(record["dms"]) == {B}          # B still got asked
    assert respond.call_count == 0            # and it's not reported as a failure
    press(bot.handle_confirm, posted_mid(client), B, client)
    assert fake.rating(A) > elo.START_RATING


def test_if_nobody_could_be_asked_the_logger_is_told(fake, client):
    """Silently sitting until the sweep would look like it simply worked."""
    def channel_only(**kwargs):
        if not str(kwargs.get("channel", "")).startswith("C"):
            raise Exception("cannot_dm_bot")
        return {"channel": kwargs["channel"], "ts": "1.1"}
    client.chat_postMessage.side_effect = channel_only

    respond = run(f"log <@{B}> 11-7", client)
    assert "couldn't DM anyone to confirm" in said(respond)
    assert len(store.list_pending()) == 1     # still valid, still sweepable


def test_a_settled_session_can_still_be_settled_from_an_old_message(fake, client):
    """A session logged before DMs existed has no stored locations; the press
    still has to land somewhere."""
    run(f"log <@{B}> 11-7", client)
    mid = posted_mid(client)
    record = store.get_pending(mid)
    record.pop("dms"), record.pop("channel"), record.pop("ts")
    store.kv.set_(store.pending_key(mid), json.dumps(record))

    press(bot.handle_confirm, mid, B, client)
    assert fake.rating(A) > elo.START_RATING
    assert client.chat_update.call_count == 1     # the container fallback


# --- an admin settling someone else's session -----------------------------

def admin_pending(client, caller=ADMIN):
    respond = MagicMock()
    bot.handle_pending({"user_id": caller}, respond)
    return respond


def blocks_of(respond):
    for c in respond.call_args_list:
        if c.kwargs.get("blocks"):
            return c.kwargs["blocks"]
    return []


def action_ids_for(respond, mid):
    for b in blocks_of(respond):
        if b.get("block_id") == f"tt_admin_{mid}":
            return [e["action_id"] for e in b["elements"]]
    return []


def test_pending_gives_an_admin_buttons(fake, client, admin):
    """The verdict DMs go to the players, so without this an admin holds the
    permission and has nowhere to use it."""
    run(f"log <@{B}> 11-7 11-9", client, user=A)
    mid = posted_mid(client)
    assert action_ids_for(admin_pending(client), mid) == \
        [bot.CONFIRM_ACTION, bot.DISPUTE_ACTION]


def test_pending_stays_plain_text_for_everyone_else(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    assert blocks_of(admin_pending(client, caller=C)) == []
    assert "Waiting on confirmation" in said(admin_pending(client, caller=C))


def test_an_admin_confirms_another_persons_session_from_the_list(fake, client, admin):
    run(f"log <@{B}> 11-7 11-9", client, user=A)
    mid = posted_mid(client)
    respond = MagicMock()
    press(bot.handle_confirm, mid, ADMIN, client, respond=respond, ephemeral=True)

    assert store.get_pending(mid) is None
    assert fake.rating(A) > elo.START_RATING > fake.rating(B)
    assert f"Settled `#{mid}`" in said(respond)       # the list looks unchanged otherwise


def test_an_admin_throws_out_another_persons_session_from_the_list(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    mid = posted_mid(client)
    respond = MagicMock()
    press(bot.handle_dispute, mid, ADMIN, client, respond=respond, ephemeral=True)
    assert store.list_pending() == []
    assert f"Threw out `#{mid}`" in said(respond)


def test_settling_from_the_list_still_updates_the_players_copies(fake, client, admin):
    run(f"log <@{B}> 11-7", client, user=A)
    press(bot.handle_confirm, posted_mid(client), ADMIN, client, ephemeral=True)
    updated = {c.kwargs["channel"] for c in client.chat_update.call_args_list}
    assert updated == {"C1", A, B}          # channel + both players' DMs


def test_an_admin_cannot_confirm_a_session_they_logged_themselves(fake, client, monkeypatch):
    """Nobody waves through their own result — an admin least defensibly of all.
    (Reachable only if admin was granted after the session was logged.)"""
    run(f"log <@{B}> 11-7 11-9", client, user=A)      # A logs it as a normal player
    mid = posted_mid(client)
    monkeypatch.setenv("TT_ADMINS", A)                # A is promoted afterwards

    respond = press(bot.handle_confirm, mid, A, client)
    assert "Only" in said(respond)
    assert store.get_pending(mid) is not None
    assert action_ids_for(admin_pending(client, caller=A), mid) == [bot.DISPUTE_ACTION]


def test_an_admin_can_still_cancel_their_own(fake, client, monkeypatch):
    run(f"log <@{B}> 11-7", client, user=A)
    mid = posted_mid(client)
    monkeypatch.setenv("TT_ADMINS", A)
    press(bot.handle_dispute, mid, A, client)
    assert store.list_pending() == []


def test_a_normal_dm_press_gets_no_extra_note(fake, client):
    """Pressing from a DM edits that DM, so an extra 'settled' note is noise."""
    run(f"log <@{B}> 11-7", client, user=A)
    respond = press(bot.handle_confirm, posted_mid(client), B, client)
    assert "Settled" not in said(respond)


def test_the_admin_list_is_capped(fake, client, admin, monkeypatch):
    monkeypatch.setattr(bot, "ADMIN_PENDING_LIMIT", 2)
    for opponent in (B, C, D):
        run(f"log <@{opponent}> 11-7", client, user=A)
    respond = admin_pending(client)
    assert len([b for b in blocks_of(respond) if b["type"] == "actions"]) == 2
    assert "1 more" in said(respond)


# --- choosing a name for the ladder ---------------------------------------

def test_setting_a_name(fake, client):
    assert "Sagnik" in said(run("name Sagnik", client))
    assert store.chosen_names()[A] == "Sagnik"


def test_a_chosen_name_beats_the_slack_handle(fake, client):
    """The handle is a fallback; what someone asked to be called always wins."""
    store.remember_handle(A, "praneat.data")
    run("name Sagnik", client)
    assert store.names()[A] == "Sagnik"


def test_the_handle_is_kept_when_no_name_is_chosen(fake, client):
    respond = MagicMock()
    bot.handle_tt_command(MagicMock(),
                          {"user_id": A, "user_name": "praneat.data", "text": "board",
                           "channel_id": "C1", "trigger_id": "t"},
                          respond, client=client, context={})
    assert store.names()[A] == "praneat.data"


def test_asking_what_your_name_is(fake, client):
    assert "haven't set a name" in said(run("name", client))
    run("name Sagnik", client)
    assert "You're *Sagnik*" in said(run("name", client))


def test_clearing_a_name(fake, client):
    run("name Sagnik", client)
    assert "Cleared" in said(run("name clear", client))
    assert A not in store.chosen_names()


def test_a_name_is_tidied_and_capped(fake, client):
    run("name    Sagnik   the    Destroyer of Worlds and Several Bats", client)
    saved = store.chosen_names()[A]
    assert len(saved) <= store.MAX_NAME and "  " not in saved


def test_nudging_asks_everyone_without_a_name(fake, client, admin):
    store.ensure_players([A, B, C])
    store.set_name(B, "Vikash")
    respond = run("nudge", client, user=ADMIN)
    asked = {c.kwargs["channel"] for c in client.chat_postMessage.call_args_list}
    assert asked == {A, C}                    # B already chose one
    assert "Asked *2*" in said(respond)


def test_only_an_admin_can_nudge_everyone(fake, client, admin):
    store.ensure_players([A, B])
    respond = run("nudge", client, user=B)
    assert "Only an admin" in said(respond)
    assert client.chat_postMessage.call_count == 0


def test_nudging_when_everyone_is_named(fake, client, admin):
    store.ensure_players([A])
    store.set_name(A, "Sagnik")
    assert "Everyone on the ladder has chosen" in said(run("nudge", client, user=ADMIN))


def test_the_welcome_dm_asks_for_a_name(fake, client, monkeypatch):
    monkeypatch.setattr(bot, "HOME_CHANNEL", "C_TT")
    bot.handle_member_joined({"channel": "C_TT", "user": B}, client=client,
                             context={"bot_user_id": BOT})
    assert "/tt name" in said(client.chat_postMessage)


# --- an admin naming someone else -----------------------------------------

def test_an_admin_names_another_player(fake, client, admin):
    respond = run(f"name <@{B}> Vikash Maddi", client, user=ADMIN)
    assert store.chosen_names()[B] == "Vikash Maddi"
    assert f"<@{B}> is *Vikash Maddi*" in said(respond)


def test_the_player_is_told_their_name_was_set_for_them(fake, client, admin):
    """A name is how you're shown to the whole office. Finding out from the
    leaderboard is not the way to learn it changed."""
    run(f"name <@{B}> Vikash", client, user=ADMIN)
    assert client.chat_postMessage.call_args.kwargs["channel"] == B
    assert "An admin set your name" in said(client.chat_postMessage)
    assert "/tt name" in said(client.chat_postMessage)


def test_a_normal_player_cannot_name_someone_else(fake, client, admin):
    respond = run(f"name <@{B}> Something Rude", client, user=C)
    assert "Only an admin" in said(respond)
    assert B not in store.chosen_names()
    assert client.chat_postMessage.call_count == 0


def test_an_admin_reads_back_someone_elses_name(fake, client, admin):
    store.set_name(B, "Vikash")
    assert "is *Vikash*" in said(run(f"name <@{B}>", client, user=ADMIN))


def test_an_admin_asking_about_an_unnamed_player(fake, client, admin):
    assert "hasn't set a name" in said(run(f"name <@{B}>", client, user=ADMIN))


def test_an_admin_clears_someone_elses_name(fake, client, admin):
    store.set_name(B, "Vikash")
    respond = run(f"name <@{B}> clear", client, user=ADMIN)
    assert B not in store.chosen_names()
    assert "falls back to their Slack name" in said(respond)
    assert "cleared your ladder name" in said(client.chat_postMessage)


def test_naming_yourself_still_works_for_an_admin(fake, client, admin):
    respond = run("name Praneat", client, user=ADMIN)
    assert store.chosen_names()[ADMIN] == "Praneat"
    assert "You're *Praneat*" in said(respond)
    assert client.chat_postMessage.call_count == 0     # no DM to yourself


def test_the_bot_is_not_a_target(fake, client, admin):
    """@-ing the bot while naming yourself shouldn't rename the bot."""
    respond = MagicMock()
    bot.handle_tt_command(MagicMock(),
                          {"user_id": ADMIN, "text": f"name <@{BOT}> Praneat",
                           "channel_id": "C1", "trigger_id": "t"},
                          respond, client=client, context={"bot_user_id": BOT})
    assert store.chosen_names().get(ADMIN) == "Praneat"
    assert BOT not in store.chosen_names()


def test_a_name_set_by_an_admin_shows_on_the_ladder(fake, client, admin):
    import page
    run(f"name <@{B}> Vikash Maddi", client, user=ADMIN)
    store.ensure_players([B])
    html = page.render(store.all_players(), store.names(), [], {}, {}, 6)
    assert "Vikash Maddi" in html


# --- the public ladder link -----------------------------------------------

def test_the_link_prefers_the_stable_production_domain(monkeypatch):
    """VERCEL_URL is the per-deployment host and changes on every push, so a
    link built from it is dead as soon as anyone deploys again."""
    monkeypatch.delenv("TT_PUBLIC_URL", raising=False)
    monkeypatch.setenv("VERCEL_URL", "tt-ranker-8ypc8rubm-personalpraneat.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "tt-ranker.vercel.app")
    assert bot.ladder_url() == "https://tt-ranker.vercel.app/ladder"


def test_an_explicit_url_wins(monkeypatch):
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "tt-ranker.vercel.app")
    monkeypatch.setenv("TT_PUBLIC_URL", "https://pingpong.example.com/")
    assert bot.ladder_url() == "https://pingpong.example.com/ladder"


def test_the_deployment_url_is_only_a_last_resort(monkeypatch):
    monkeypatch.delenv("TT_PUBLIC_URL", raising=False)
    monkeypatch.delenv("VERCEL_PROJECT_PRODUCTION_URL", raising=False)
    monkeypatch.setenv("VERCEL_URL", "tt-ranker-abc123.vercel.app")
    assert bot.ladder_url() == "https://tt-ranker-abc123.vercel.app/ladder"


def test_no_link_when_the_deployment_has_no_address(monkeypatch):
    for var in ("TT_PUBLIC_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
        monkeypatch.delenv(var, raising=False)
    assert bot.ladder_url() == ""


def test_the_pinned_intro_carries_the_link(fake, client, monkeypatch):
    monkeypatch.setenv("TT_PUBLIC_URL", "https://tt-ranker.vercel.app")
    run("intro", client)
    assert "https://tt-ranker.vercel.app/ladder" in said(client.chat_postMessage)


def test_the_board_carries_the_link(fake, client, monkeypatch):
    monkeypatch.setenv("TT_PUBLIC_URL", "https://tt-ranker.vercel.app")
    assert "https://tt-ranker.vercel.app/ladder" in said(run("board", client))


def test_no_dangling_link_text_without_a_url(fake, client, monkeypatch):
    for var in ("TT_PUBLIC_URL", "VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
        monkeypatch.delenv(var, raising=False)
    assert "Live ladder" not in said(run("board", client))


# --- betting, end to end ---------------------------------------------------

import betting  # noqa: E402


def fixture_id(client):
    """The fixture id carried by the Back buttons on the message just posted."""
    for call in reversed(posts(client)):
        for b in call.kwargs.get("blocks") or []:
            if str(b.get("block_id", "")).startswith("tt_fixture_"):
                return b["block_id"].removeprefix("tt_fixture_")
    raise AssertionError("no fixture message was posted")


def back(client, sid, user, side, amount):
    """Stake through the modal, the way the buttons do."""
    ack = MagicMock()
    bot.handle_bet_modal(ack, {"user": {"id": user}},
                         {"private_metadata": f"{sid}:{side}",
                          "state": {"values": {"amount": {"v": {"value": str(amount)}}}}},
                         client=client)
    return ack


def play_and_confirm(client, opponent, games="21-14 21-16", user=A, by=None):
    run(f"log <@{opponent}> {games}", client, user=user)
    press(bot.handle_confirm, posted_mid(client), by or opponent, client)


def test_scheduling_posts_a_fixture_with_both_sides_to_back(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    posted = said(client.chat_postMessage)
    assert f"<@{A}>" in posted and f"<@{B}>" in posted
    assert set(buttons_in(channel_post(client))) >= set(bot.BET_ACTIONS)


def test_a_fixture_states_the_time_it_resolved_to(fake, client):
    """Always echoed back, so a misread "9am" is visible rather than a surprise."""
    run(f"schedule <@{B}> 6pm", client)
    assert "18:00" in said(client.chat_postMessage)


def test_a_stake_leaves_the_wallet_and_shows_in_the_pot(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 50)
    assert betting.balance(C) == betting.START_SPINS - 50
    assert betting.pool(sid)["a"] == 50
    assert "50" in said(client.chat_update)          # the message repainted


def test_the_pot_and_projected_return_are_shown(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 300)
    back(client, sid, D, "b", 100)
    shown = said(client.chat_update)
    assert "400" in shown and "4.00×" in shown       # 400 pot, b pays 4x


def test_a_bad_amount_comes_back_on_the_field(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    ack = back(client, fixture_id(client), C, "a", "loads")
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "amount" in ack.call_args.kwargs["errors"]


def test_staking_more_than_you_hold_is_refused_in_the_modal(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    ack = back(client, fixture_id(client), C, "a", betting.START_SPINS + 1)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert betting.balance(C) == betting.START_SPINS


def test_playing_the_match_settles_the_pot(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 300)      # backs A
    back(client, sid, D, "b", 100)      # backs B
    play_and_confirm(client, B)         # A wins 2-0

    assert betting.get(sid)["state"] == "settled"
    assert betting.balance(C) == betting.START_SPINS + 100
    assert betting.balance(D) == betting.START_SPINS - 100
    assert "beat" in said(client.chat_update)


def test_a_result_logged_the_other_way_round_still_settles_it(fake, client):
    """Nobody quotes a fixture id when logging, so the players are the only
    thing tying a session to a pot."""
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 100)      # backs A, side A of the fixture
    back(client, sid, D, "b", 100)      # backs B, so there is a winning side
    play_and_confirm(client, A, user=B, by=A)   # B logs it, and B wins

    assert betting.get(sid)["winner"] == "b"
    assert betting.balance(C) == betting.START_SPINS - 100
    assert betting.balance(D) == betting.START_SPINS + 100


def test_winners_are_told_what_they_took(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 300)
    back(client, sid, D, "b", 100)
    play_and_confirm(client, B)
    dm = dm_text(client, C)
    assert "took back" in dm and "400" in dm


def test_an_unrelated_match_settles_nothing(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 100)
    play_and_confirm(client, D)         # A vs D, not the scheduled A vs B
    assert betting.get(sid)["state"] == "open"
    assert betting.balance(C) == betting.START_SPINS - 100


def test_a_broken_wallet_never_unwinds_a_confirmed_match(fake, client, monkeypatch):
    """The rating is already written by the time bets settle."""
    run(f"schedule <@{B}> in 2h", client)
    back(client, fixture_id(client), C, "a", 50)
    monkeypatch.setattr(betting, "settle", MagicMock(side_effect=RuntimeError("boom")))
    play_and_confirm(client, B)
    assert fake.rating(A) > elo.START_RATING        # the match still counted


def test_calling_a_fixture_off_refunds_everyone(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 300)
    back(client, sid, D, "b", 100)

    body = {"user": {"id": A}, "actions": [{"value": sid}],
            "container": {"channel_id": "C1", "message_ts": "1"}}
    bot.handle_cancel_fixture(body, client, MagicMock())

    assert betting.get(sid)["state"] == "void"
    assert betting.balance(C) == betting.balance(D) == betting.START_SPINS
    assert "called off" in said(client.chat_update)


def test_only_the_players_or_the_organiser_can_call_it_off(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    respond = MagicMock()
    bot.handle_cancel_fixture({"user": {"id": E}, "actions": [{"value": sid}],
                               "container": {}}, client, respond)
    assert "Only the players" in said(respond)
    assert betting.get(sid)["state"] == "open"


def test_backing_your_own_opponent_is_allowed_but_shown(fake, client):
    """House rule says anything goes, so the guard is daylight."""
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, A, "b", 50)       # A is playing, and backs B
    assert betting.balance(A) == betting.START_SPINS - 50
    assert "Backing the other side of their own match" in said(client.chat_update)


def test_the_window_shuts_once_the_match_is_due(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    record = betting.get(sid)
    record["starts_at"] = store.stamp(store.now_ist() - timedelta(minutes=1))
    betting.save(record)

    ack = back(client, sid, C, "a", 50)
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert betting.balance(C) == betting.START_SPINS
    assert betting.get(sid)["state"] == "closed"


def test_the_sweep_refunds_a_fixture_nobody_ever_reported(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 80)
    later = store.now_ist() + timedelta(hours=betting.ABANDON_HOURS + 3)

    result = standings.sweep_fixtures(client, now=later)
    assert sid in result["refunded"]
    assert betting.balance(C) == betting.START_SPINS
    assert betting.get(sid)["state"] == "void"


def test_the_wallet_command_shows_the_balance_and_recent_moves(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    back(client, fixture_id(client), A, "a", 50)
    shown = said(run("wallet", client))
    # formatted, not raw: balances are four figures now and carry a separator
    assert bot.fmt_spins(betting.START_SPINS - 50) in shown
    assert "stake on" in shown


def test_the_book_lists_what_is_open(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 75)
    shown = said(run("book", client))
    assert f"#{sid}" in shown and "75" in shown


def test_the_book_when_nothing_is_scheduled(fake, client):
    assert "Nothing scheduled" in said(run("book", client))


def test_betting_by_command_works_too(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    respond = run(f"bet {sid} a 60", client, user=C)
    assert betting.balance(C) == betting.START_SPINS - 60
    assert "Balance" in said(respond)


def test_a_bet_on_a_fixture_that_does_not_exist(fake, client):
    assert "No fixture" in said(run("bet 999 a 50", client))


# --- the scheduling form ---------------------------------------------------

def schedule_form(client, user=A):
    run("schedule", client, user=user)
    return client.views_open.call_args.kwargs["view"]


def submit_schedule(client, side_a, side_b, when, user=A, channel="C1", extra=None):
    state = {"side_a": {"v": {"selected_users": side_a}},
             "side_b": {"v": {"selected_users": side_b}},
             "when": {"v": {"selected_date_time": int(when.timestamp()) if when else None}}}
    state.update(extra or {})
    ack = MagicMock()
    bot.handle_schedule_modal(ack, {"user": {"id": user}},
                              {"state": {"values": state}, "private_metadata": channel},
                              client=client)
    return ack


def test_a_bare_schedule_opens_the_form(fake, client):
    view = schedule_form(client)
    assert view["callback_id"] == bot.SCHEDULE_MODAL
    assert [b["block_id"] for b in view["blocks"]] == ["side_a", "side_b", "when"]


def test_the_form_uses_a_real_date_picker(fake, client):
    """"6pm" has to be parsed, guessed across midnight and echoed back to be
    checked. A picker is unambiguous the moment it's set."""
    when = next(b for b in schedule_form(client)["blocks"] if b["block_id"] == "when")
    assert when["element"]["type"] == "datetimepicker"
    assert when["element"]["initial_date_time"] > int(store.now_ist().timestamp())


def test_the_form_pre_picks_you_and_caps_each_side_at_two(fake, client):
    blocks = schedule_form(client)["blocks"]
    assert blocks[0]["element"]["initial_users"] == [A]
    assert all(b["element"]["max_selected_items"] == 2 for b in blocks[:2])


def test_the_default_start_is_an_hour_out_on_a_quarter(fake):
    from datetime import datetime
    odd = datetime(2026, 9, 17, 14, 7, 33, tzinfo=store.IST)
    assert bot._default_start(odd) == datetime(2026, 9, 17, 15, 15, tzinfo=store.IST)
    on_the_quarter = datetime(2026, 9, 17, 14, 15, tzinfo=store.IST)
    assert bot._default_start(on_the_quarter) == datetime(2026, 9, 17, 15, 15,
                                                          tzinfo=store.IST)


def test_submitting_the_form_puts_a_fixture_up(fake, client):
    when = store.now_ist() + timedelta(hours=2)
    ack = submit_schedule(client, [A], [B], when)
    ack.assert_called_once_with()
    record = betting.get(fixture_id(client))
    assert record["side_a"] == [A] and record["side_b"] == [B]
    assert abs(betting.starts_at(record) - when).total_seconds() < 60


def test_a_doubles_fixture_from_the_pickers_alone(fake, client):
    submit_schedule(client, [A, B], [C, D], store.now_ist() + timedelta(hours=2))
    record = betting.get(fixture_id(client))
    assert record["side_a"] == [A, B] and record["side_b"] == [C, D]


def test_a_fixture_from_the_form_can_be_bet_on_and_settles(fake, client):
    submit_schedule(client, [A], [B], store.now_ist() + timedelta(hours=2))
    sid = fixture_id(client)
    back(client, sid, C, "a", 200)
    back(client, sid, D, "b", 100)
    play_and_confirm(client, B)
    assert betting.get(sid)["state"] == "settled"
    assert betting.balance(C) == betting.START_SPINS + 100


@pytest.mark.parametrize("side_a,side_b,when_offset,field,fragment", [
    ([A], [], timedelta(hours=2), "side_b", "who played"),
    ([A], [A], timedelta(hours=2), "side_b", "both sides"),
    ([A], [B, C], timedelta(hours=2), "side_b", "Uneven sides"),
    ([A], [B], timedelta(minutes=-5), "when", "already past"),
    ([A], [B], timedelta(days=60), "when", "days out"),
])
def test_schedule_form_errors_come_back_on_the_field(fake, client, side_a, side_b,
                                            when_offset, field, fragment):
    ack = submit_schedule(client, side_a, side_b, store.now_ist() + when_offset)
    kwargs = ack.call_args.kwargs
    assert kwargs["response_action"] == "errors"
    assert fragment in kwargs["errors"][field]
    assert betting.live() == []          # nothing put up on a rejected form


def test_a_missing_time_is_caught(fake, client):
    ack = submit_schedule(client, [A], [B], None)
    assert "Pick when it starts" in ack.call_args.kwargs["errors"]["when"]


def test_a_form_that_cannot_open_falls_back_to_the_typed_route(fake, client):
    client.views_open.side_effect = Exception("expired_trigger_id")
    assert "type it instead" in said(run("schedule", client))


# --- the scheduling shortcut ----------------------------------------------

def schedule_shortcut(client, user=A):
    ack = MagicMock()
    bot.handle_schedule_shortcut(ack, {"user": {"id": user}, "trigger_id": "t.1"},
                                 client=client)
    return client.views_open.call_args.kwargs["view"]


def test_the_shortcut_opens_the_same_form_plus_a_channel_picker(fake, client):
    view = schedule_shortcut(client)
    assert view["callback_id"] == bot.SCHEDULE_MODAL
    assert [b["block_id"] for b in view["blocks"]] == \
        ["side_a", "side_b", "when", "channel"]


def test_a_shortcut_fixture_posts_to_the_chosen_channel(fake, client):
    submit_schedule(client, [A], [B], store.now_ist() + timedelta(hours=2),
                    channel="", extra={"channel": {"v": {"selected_conversation": "C_PICKED"}}})
    assert channel_post(client).kwargs["channel"] == "C_PICKED"


def test_the_shortcut_form_needs_a_channel(fake, client):
    ack = submit_schedule(client, [A], [B], store.now_ist() + timedelta(hours=2),
                          channel="", extra={"channel": {"v": {"selected_conversation": None}}})
    assert "channel" in ack.call_args.kwargs["errors"]
    assert betting.live() == []


def test_a_schedule_shortcut_that_cannot_open_is_explained_by_dm(fake, client):
    client.views_open.side_effect = Exception("expired_trigger_id")
    ack = MagicMock()
    bot.handle_schedule_shortcut(ack, {"user": {"id": A}, "trigger_id": "t"}, client=client)
    assert dm_to(client, A) is not None
    assert "/tt schedule @opponent" in dm_text(client, A)


# --- saying what actually went wrong --------------------------------------

class SlackRefusal(Exception):
    """A slack_sdk error, which carries the reason in .response['error']."""
    def __init__(self, code):
        self.response = {"error": code}
        super().__init__(code)


def test_a_private_channel_is_explained_as_one(fake, client):
    """channel_not_found is what Slack says for a private channel the bot isn't
    in, which is the single most confusing refusal here — chat:write.public
    covers public channels only."""
    client.chat_postMessage.side_effect = SlackRefusal("channel_not_found")
    respond = run(f"schedule <@{B}> in 2h", client)
    said_it = said(respond)
    assert "private channel" in said_it and "/invite" in said_it
    assert betting.live() == []          # nothing left standing with no message


def test_being_outside_the_channel_says_so(fake, client):
    client.chat_postMessage.side_effect = SlackRefusal("not_in_channel")
    assert "I'm not in" in said(run(f"schedule <@{B}> in 2h", client))


def test_an_unknown_refusal_is_quoted_rather_than_guessed_at(fake, client):
    """It used to blame the channel for every failure — a guess dressed as a
    diagnosis, and useless when the cause was something else."""
    client.chat_postMessage.side_effect = SlackRefusal("ratelimited")
    assert "`ratelimited`" in said(run(f"schedule <@{B}> in 2h", client))


def test_a_failure_with_no_slack_code_still_says_something(fake, client):
    client.chat_postMessage.side_effect = RuntimeError("connection reset")
    assert "connection reset" in said(run(f"schedule <@{B}> in 2h", client))


def test_a_failed_fixture_stakes_nothing(fake, client):
    client.chat_postMessage.side_effect = SlackRefusal("not_in_channel")
    respond = run(f"schedule <@{B}> in 2h", client)
    assert "Nothing was staked" in said(respond)
    assert betting.balance(A) == betting.START_SPINS


def test_logging_reports_the_real_reason_too(fake, client):
    client.chat_postMessage.side_effect = SlackRefusal("is_archived")
    assert "archived" in said(run(f"log <@{B}> 11-7", client))
    assert store.list_pending() == []


# --- the intro replaces itself --------------------------------------------

def test_posting_an_intro_remembers_where_it_went(fake, client):
    run("intro", client)
    assert store.last_intro("C1")        # the ts the post came back with


def test_re_running_intro_replaces_the_old_one(fake, client):
    """It's regenerated from live constants, so it gets re-run after every
    change — a trail of stale intros is the default outcome otherwise."""
    run("intro", client)
    first_ts = store.last_intro("C1")
    respond = run("intro", client)

    client.chat_delete.assert_called_once_with(channel="C1", ts=first_ts)
    assert "Replaced the old intro" in said(respond)
    assert store.last_intro("C1") != first_ts


def test_the_first_intro_is_not_announced_as_a_replacement(fake, client):
    assert "Posted" in said(run("intro", client))
    assert client.chat_delete.call_count == 0


def test_clearing_takes_the_intro_down(fake, client):
    run("intro", client)
    ts = store.last_intro("C1")
    respond = run("intro clear", client)
    client.chat_delete.assert_called_once_with(channel="C1", ts=ts)
    assert "taken down" in said(respond)
    assert store.last_intro("C1") is None


def test_clearing_when_there_is_nothing_to_clear(fake, client):
    respond = run("intro clear", client)
    assert "haven't got an intro posted here" in said(respond)
    assert "Delete message" in said(respond)       # how to remove an older one


def test_an_intro_deleted_by_hand_is_forgotten_anyway(fake, client):
    """Most likely cause of a failed delete, and it must not wedge the command."""
    run("intro", client)
    client.chat_delete.side_effect = SlackRefusal("message_not_found")
    run("intro clear", client)
    assert store.last_intro("C1") is None


@pytest.mark.parametrize("word", ["clear", "delete", "remove", "off", "unpin"])
def test_the_ways_to_take_it_down(fake, client, word):
    run("intro", client)
    run(f"intro {word}", client)
    assert store.last_intro("C1") is None


def test_each_channel_keeps_its_own_intro(fake, client):
    run("intro", client)
    bot.handle_tt_command(MagicMock(),
                          {"user_id": A, "text": "intro", "channel_id": "C2",
                           "trigger_id": "t"},
                          MagicMock(), client=client, context={})
    assert store.last_intro("C1") and store.last_intro("C2")
    assert store.last_intro("C1") != store.last_intro("C2")


# --- who backed what -------------------------------------------------------

def test_the_fixture_message_names_the_backers(fake, client):
    """On a small ladder, who backed you is most of the point — and it's what
    makes an odd-looking stake something the room notices."""
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 1020)
    back(client, sid, D, "b", 5000)
    shown = said(client.chat_update)
    assert f"<@{C}> 1,020" in shown and f"<@{D}> 5,000" in shown


def test_backers_are_listed_biggest_first(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 50)
    back(client, sid, D, "a", 900)
    line = bot.backers_line(betting.pool(sid), "a")
    assert line.index(f"<@{D}>") < line.index(f"<@{C}>")


def test_a_long_list_of_backers_is_trimmed(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    for i, uid in enumerate([C, D, E, "U0FFF1", "U0GGG1", "U0HHH1", "U0III1",
                             "U0JJJ1", "U0KKK1", "U0LLL1"]):
        back(client, sid, uid, "a", 10 + i)
    line = bot.backers_line(betting.pool(sid), "a")
    assert line.count("<@") == bot.BACKERS_SHOWN
    assert "+2 more" in line


def test_a_side_with_no_backers_lists_nobody(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 50)
    assert bot.backers_line(betting.pool(sid), "b") == ""


def test_book_with_an_id_gives_one_fixture_in_full(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, C, "a", 1020)
    back(client, sid, D, "b", 4000)     # a stake above the balance is refused

    shown = said(run(f"book {sid}", client))
    # sole backer of a side takes the whole pot either way round
    assert f"<@{C}>  1,020 → *5,020*" in shown
    assert f"<@{D}>  4,000 → *5,020*" in shown
    assert "pays" in shown


def test_the_detail_view_flags_a_player_backing_their_opponent(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, A, "b", 50)       # A is playing, and backs B
    back(client, sid, C, "a", 50)
    shown = said(run(f"book {sid}", client))
    assert "playing, backed the other side" in shown


def test_the_detail_view_marks_a_player_backing_themselves(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    sid = fixture_id(client)
    back(client, sid, A, "a", 50)
    shown = said(run(f"book {sid}", client))
    assert "_playing_" in shown and "backed the other side" not in shown


def test_the_detail_view_of_an_untouched_fixture(fake, client):
    run(f"schedule <@{B}> in 2h", client)
    assert "Nobody has staked" in said(run(f"book {fixture_id(client)}", client))


def test_asking_about_a_fixture_that_does_not_exist(fake, client):
    assert "No fixture" in said(run("book 999", client))


# --- moving spins ----------------------------------------------------------

def test_an_admin_transfers_out_of_their_own_wallet(fake, client, admin):
    respond = run(f"transfer <@{B}> 500", client, user=ADMIN)
    assert betting.balance(ADMIN) == betting.START_SPINS - 500
    assert betting.balance(B) == betting.START_SPINS + 500
    assert "Moved" in said(respond)


def test_an_admin_moves_spins_between_two_other_people(fake, client, admin):
    run(f"transfer <@{C}> <@{D}> 250", client, user=ADMIN)
    assert betting.balance(C) == betting.START_SPINS - 250
    assert betting.balance(D) == betting.START_SPINS + 250


def test_a_normal_player_cannot_move_spins(fake, client, admin):
    respond = run(f"transfer <@{C}> 500", client, user=B)
    assert "Only an admin" in said(respond)
    assert betting.balance(C) == betting.START_SPINS


def test_the_recipient_is_told(fake, client, admin):
    """A balance changing with no warning reads as a bug."""
    run(f"transfer <@{B}> 500", client, user=ADMIN)
    assert "sent you" in dm_text(client, B)


def test_both_sides_are_told_when_a_third_party_moved_it(fake, client, admin):
    run(f"transfer <@{C}> <@{D}> 250", client, user=ADMIN)
    assert f"moved by <@{ADMIN}>" in dm_text(client, C)
    assert f"<@{ADMIN}> moved it" in dm_text(client, D)


def test_a_transfer_with_no_amount_explains_itself(fake, client, admin):
    assert "How many spins" in said(run(f"transfer <@{B}>", client, user=ADMIN))


def test_a_transfer_with_nobody_named_explains_itself(fake, client, admin):
    assert "Who to" in said(run("transfer 500", client, user=ADMIN))


def test_a_comma_separated_amount_works(fake, client, admin):
    run(f"transfer <@{B}> 1,500", client, user=ADMIN)
    assert betting.balance(B) == betting.START_SPINS + 1500


def test_the_digits_in_a_user_id_are_not_read_as_an_amount(fake, client, admin):
    """U0BBB1 has digits in it; only what's left after stripping mentions counts."""
    run(f"transfer <@{B}> 75", client, user=ADMIN)
    assert betting.balance(B) == betting.START_SPINS + 75


def test_an_overdraft_is_refused_with_the_real_balance(fake, client, admin):
    respond = run(f"transfer <@{B}> 999999", client, user=ADMIN)
    assert "only has" in said(respond)
    assert betting.balance(B) == betting.START_SPINS


def test_a_transfer_shows_up_in_the_wallet(fake, client, admin):
    run(f"transfer <@{B}> 500", client, user=ADMIN)
    assert f"<@{ADMIN}>" in said(run("wallet", client, user=B))


# --- the spins leaderboard -------------------------------------------------

def test_rich_lists_wallets_richest_first(fake, client):
    run("register", client, user=A)
    run("register", client, user=B)
    run("register", client, user=C)
    fake.exec(["HSET", "tt:wallet", A, 4000, B, 7000])
    out = said(run("rich", client, user=C))
    assert out.index(f"<@{B}>") < out.index(f"<@{C}>") < out.index(f"<@{A}>")
    assert "7,000 spins" in out and "+2,000" in out and "-1,000" in out
    assert "16,000 spins in circulation" in out


def test_the_wallet_says_where_you_stand(fake, client):
    run("register", client, user=A)
    run("register", client, user=B)
    fake.exec(["HSET", "tt:wallet", B, 9000])
    assert "#2 of 2 wallets" in said(run("wallet", client, user=A))
# --- history by day --------------------------------------------------------

def _played(fake, client, a, b, when):
    """A confirmed session between a and b, rated at `when`."""
    rec = store.create_pending([a], [b], [(11, 7), (11, 9)], logged_by=a, now=when)
    assert store.claim_pending(rec["id"])
    return store.apply_match(rec, confirmed_by=b, now=when)


def test_history_can_be_asked_for_a_day(fake, client):
    now = store.now_ist()
    _played(fake, client, A, B, now - timedelta(days=1))
    today = _played(fake, client, A, C, now)
    out = said(run("history today", client))
    assert f"#{today['id']}" in out and f"<@{C}>" in out
    assert f"<@{B}>" not in out
    assert "today* — 1" in out


def test_history_for_one_player_on_one_day(fake, client):
    now = store.now_ist()
    _played(fake, client, A, B, now)
    _played(fake, client, C, D, now)
    out = said(run(f"history <@{C}> today", client))
    assert f"<@{D}>" in out and f"<@{B}>" not in out
    out = said(run(f"history yesterday <@{C}>", client))
    assert "No matches recorded" in out and "yesterday" in out


def test_an_unreadable_day_is_explained(fake, client):
    out = said(run("history 2026-13-40", client))
    assert "don't know which day" in out and "yesterday" in out


# --- who is that on the ladder? -------------------------------------------

def test_a_ladder_name_resolves_to_a_mention(fake, client):
    """The page can't render a mention, so it shows chosen names — this is the
    way back from one of those to a person."""
    store.set_name(B, "ChumChum")
    store.ensure_players([A, B])
    assert f"*ChumChum* is <@{B}>" in said(run("who ChumChum", client))


def test_the_lookup_does_not_care_about_case(fake, client):
    store.set_name(B, "ChumChum")
    store.ensure_players([B])
    assert f"<@{B}>" in said(run("who chumchum", client))


def test_a_partial_name_is_enough(fake, client):
    store.set_name(B, "farzibatman")
    store.ensure_players([B])
    assert f"<@{B}>" in said(run("who farzi", client))


def test_an_exact_name_beats_a_longer_one_containing_it(fake, client):
    """Ram shouldn't lose to Ramesh — which is exactly when you need this."""
    store.set_name(B, "Ram")
    store.set_name(C, "Ramesh")
    store.ensure_players([B, C])
    out = said(run("who Ram", client))
    assert f"<@{B}>" in out and f"<@{C}>" not in out


def test_several_matches_are_all_offered(fake, client):
    store.set_name(B, "Ramesh")
    store.set_name(C, "Ramona")
    store.ensure_players([B, C])
    out = said(run("who Ram", client))
    assert "2 match" in out and f"<@{B}>" in out and f"<@{C}>" in out


def test_a_name_nobody_has(fake, client):
    store.ensure_players([A])
    assert "Nobody on the ladder is called" in said(run("who Nobody", client))


def test_the_lookup_runs_the_other_way_too(fake, client):
    store.set_name(B, "ChumChum")
    store.ensure_players([B])
    assert "is *ChumChum* on the ladder" in said(run(f"who <@{B}>", client))


def test_someone_who_never_set_a_name_is_told_apart_from_one_who_did(fake, client):
    store.remember_handle(B, "bob.smith")
    store.ensure_players([B, C])
    assert "their Slack name" in said(run(f"who <@{B}>", client))
    assert "hasn't got a ladder name yet" in said(run(f"who <@{C}>", client))


def test_bare_who_lists_everyone_against_their_mention(fake, client):
    store.set_name(A, "danger")
    store.set_name(B, "ChumChum")
    store.ensure_players([A, B])
    out = said(run("who", client))
    assert f"*ChumChum* — <@{B}>" in out and f"*danger* — <@{A}>" in out
    assert out.index("ChumChum") < out.index("danger")      # alphabetical


def test_a_player_with_no_name_at_all_is_still_findable(fake, client):
    """They show as a stub on the page, so the stub has to resolve."""
    store.ensure_players([A])
    assert f"<@{A}>" in said(run(f"who @{A[-4:]}", client))


def test_the_list_puts_names_first_and_collapses_the_rest(fake, client):
    """Sorted together, `@abcd` stubs sort above every real name and bury the
    only rows the command exists to show."""
    store.set_name(A, "danger")
    store.ensure_players([A, B, C, D])      # B, C, D have no name
    out = said(run("who", client))
    assert out.index("danger") < out.index("haven't set a name")
    assert "3 haven't set a name" in out
    for uid in (B, C, D):
        assert f"<@{uid}>" in out


# --- titles ----------------------------------------------------------------

def test_titles_lists_the_lot_held_or_not(fake, client):
    for _ in range(3):
        rec = store.create_pending([A], [B], [(11, 5), (11, 6)], logged_by=A)
        store.claim_pending(rec["id"])
        store.apply_match(rec, confirmed_by=B)
    out = said(run("titles", client))
    assert "On Fire" in out and f"<@{A}>" in out
    assert "going spare" in out            # nobody has moved a wallet


def test_the_me_card_wears_what_you_have_won(fake, client):
    for _ in range(3):
        rec = store.create_pending([A], [B], [(11, 5), (11, 6)], logged_by=A)
        store.claim_pending(rec["id"])
        store.apply_match(rec, confirmed_by=B)
    assert "On Fire" in said(run("me", client, user=A))
    assert "On Fire" not in said(run("me", client, user=B))


# --- the quick list, end to end --------------------------------------------

def test_help_carries_the_whole_command_list(fake, client):
    out = said(run("help", client))
    assert "/tt board" in out and "/tt titles" in out
    assert "How the rating works" in out


def test_the_words_people_reach_for_all_land_on_help(fake, client):
    """Somebody typing `commands` wants the list, and the list is in help."""
    for word in ("commands", "cheatsheet", "quick"):
        assert "/tt board" in said(run(word, client))


def test_a_mistyped_command_is_answered_with_a_guess(fake, client):
    out = said(run("boad", client))
    assert "`boad`" in out and "/tt board" in out
    assert "How the rating works" not in out       # not the whole of HELP


def test_help_is_still_the_whole_thing(fake, client):
    out = said(run("help", client))
    assert "How the rating works" in out


# --- winning a session pays spins ------------------------------------------

def test_confirming_a_match_pays_the_winner(fake):
    import betting
    from unittest.mock import MagicMock
    store.ensure_players([A, B])
    betting.ensure_wallets([A, B])
    record = store.create_pending([A], [B], [(21, 10), (21, 12), (21, 15)],
                                  logged_by=A)
    bot.handle_confirm({"user": {"id": B},
                        "actions": [{"action_id": bot.CONFIRM_ACTION,
                                     "value": record["id"]}]},
                       MagicMock(), MagicMock())
    assert betting.balance(A) == betting.START_SPINS + 20     # 3-0, a wipeout
    assert betting.balance(B) == betting.START_SPINS


def test_an_auto_confirmed_match_pays_too(fake):
    """The sweep goes through the same payout as a confirmation, so a match
    nobody answered still pays whoever won it."""
    import betting, standings
    from datetime import timedelta
    from unittest.mock import MagicMock
    now = store.now_ist()
    store.ensure_players([A, B])
    betting.ensure_wallets([A, B])
    store.create_pending([A], [B], [(21, 10), (21, 12)], logged_by=A,
                         now=now - timedelta(hours=store.AUTO_CONFIRM_HOURS + 1))
    standings.sweep_pending(MagicMock(), now=now)
    assert betting.balance(A) == betting.START_SPINS + 10     # 2-0, decent


def test_undoing_a_match_takes_the_spins_back_with_the_rating(fake):
    import betting
    from unittest.mock import MagicMock
    store.ensure_players([A, B])
    betting.ensure_wallets([A, B])
    record = store.create_pending([A], [B], [(21, 10), (21, 12), (21, 15)],
                                  logged_by=A)
    bot.handle_confirm({"user": {"id": B},
                        "actions": [{"action_id": bot.CONFIRM_ACTION,
                                     "value": record["id"]}]},
                       MagicMock(), MagicMock())
    respond = MagicMock()
    bot.handle_undo({"user_id": A, "text": "undo"}, respond)
    assert betting.balance(A) == betting.START_SPINS


def test_the_result_message_says_what_winning_paid(fake):
    store.ensure_players([A, B])
    record = store.create_pending([A], [B], [(21, 10), (21, 12), (21, 15)],
                                  logged_by=A)
    store.claim_pending(record["id"])
    blob = store.apply_match(record, confirmed_by=B)
    text = " ".join(b["text"]["text"] for b in bot.applied_blocks(blob)
                    if b["type"] == "section")
    assert "20" in text and "wipeout" in text
