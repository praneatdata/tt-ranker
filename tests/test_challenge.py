"""Challenging someone, and agreeing how long the session runs.

`/tt schedule` states a fact. A challenge is the step before it, where the other
person still gets a say — so nothing reaches the board until they answer, and
what they're answering includes how many games it runs to.

Accepting turns it into an ordinary fixture, which is the point: betting, moving
it and calling it off are all machinery that already exists, and a challenge
never becomes a second kind of scheduled match to keep in step.
"""
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import betting
import bot
import challenge
import elo
import parsing
import store
from tests.fake_kv import FakeRedis

A, B, C, D = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1"


@pytest.fixture
def fake():
    redis = FakeRedis()
    with redis.patched():
        yield redis


def command(text, user=A, channel="C1"):
    return {"user_id": user, "text": text, "channel_id": channel, "trigger_id": "t"}


def said(mock):
    import json
    return "\n".join(json.dumps(a, default=str, ensure_ascii=False)
                     for c in mock.call_args_list
                     for a in list(c.args) + list(c.kwargs.values()))


def issue(side_a=(A,), side_b=(B,), games=3, first_to=2, when=None, by=None):
    return challenge.issue(list(side_a), list(side_b), games, by=by or side_a[0],
                           first_to=first_to, starts_at=when, channel="C1")


# --- saying how long it runs ----------------------------------------------

@pytest.mark.parametrize("text,games,first_to", [
    ("best of 5", 5, 3),
    ("bestof5", 5, 3),
    ("bo7", 7, 4),
    ("best-of-3", 3, 2),
    ("first to 3", 5, 3),
    ("ft2", 3, 2),
    ("5 games", 5, None),
    ("4 matches", 4, None),      # what people here actually call them
    ("1 game", 1, None),
    ("2 sets", 2, None),
])
def test_the_ways_to_say_how_long(text, games, first_to):
    assert parsing.parse_length(text)[:2] == (games, first_to)


def test_no_length_given_is_a_different_fact_from_a_short_one():
    """The caller supplies the default, so "they didn't say" stays visible."""
    assert parsing.parse_length("nothing here")[:2] == (None, None)


def test_best_of_five_means_first_to_three():
    games, first_to, _ = parsing.parse_length("best of 5")
    assert games == 5 and first_to == 3


def test_first_to_three_means_up_to_five_games():
    games, first_to, _ = parsing.parse_length("first to 3")
    assert games == 5 and first_to == 3


def test_the_length_reads_back_the_way_it_was_asked_for():
    assert challenge.length_note({"games": 5, "first_to": 3}) == "Best of 5 — first to 3"
    assert challenge.length_note({"games": 5, "first_to": None}) == "5 games"
    assert challenge.length_note({"games": 1, "first_to": None}) == "One game"


# --- parsing the whole thing ----------------------------------------------

def m(uid):
    return f"<@{uid}>"


def test_a_bare_challenge_takes_the_default_length():
    now = store.now_ist()
    side_a, side_b, games, first_to, when = parsing.parse_challenge(
        m(B), caller=A, now=now, default_games=3)
    assert side_a == [A] and side_b == [B]
    assert (games, first_to, when) == (3, 2, None)


def test_a_time_is_optional_on_a_challenge():
    """Unlike /tt schedule. "Play me some time today" is a real thing to say."""
    now = store.now_ist()
    assert parsing.parse_challenge(m(B), caller=A, now=now)[4] is None
    when = parsing.parse_challenge(f"{m(B)} at 6pm", caller=A, now=now)[4]
    assert when and when.hour == 18


def test_doubles_challenges_split_on_vs():
    now = store.now_ist()
    side_a, side_b, *_ = parsing.parse_challenge(
        f"{m(B)} vs {m(C)} {m(D)}", caller=A, now=now)
    assert side_a == [A, B] and side_b == [C, D]


def test_you_cannot_challenge_yourself():
    now = store.now_ist()
    with pytest.raises(parsing.ParseError):
        parsing.parse_challenge(f"{m(B)} vs {m(A)}", caller=A, now=now)


def test_a_session_longer_than_the_cap_is_refused():
    now = store.now_ist()
    with pytest.raises(parsing.ParseError, match=str(elo.MAX_GAMES)):
        parsing.parse_challenge(f"{m(B)} {elo.MAX_GAMES + 1} games",
                                caller=A, now=now)


def test_a_clock_time_already_gone_today_means_tomorrow():
    """Challenging someone at 11am when it is noon is an invitation for
    tomorrow, not an error — parse_when rolls a bare clock time forward, and a
    challenge has no reason to disagree with the scheduler about that."""
    now = store.now_ist().replace(hour=12, minute=0)
    when = parsing.parse_challenge(f"{m(B)} at 11am", caller=A, now=now)[4]
    assert when > now and when.hour == 11
    assert when.date() == (now + timedelta(days=1)).date()


def test_a_date_beyond_the_horizon_is_refused():
    now = store.now_ist()
    with pytest.raises(parsing.ParseError, match="days out"):
        parsing.parse_challenge(f"{m(B)} in {parsing.MAX_LEAD_DAYS * 24 + 48}h",
                                caller=A, now=now)


# --- the record ------------------------------------------------------------

def test_a_challenge_starts_open_and_is_listed(fake):
    record = issue()
    assert record["state"] == "open"
    assert [r["id"] for r in challenge.live()] == [record["id"]]


def test_only_the_challenged_side_may_answer(fake):
    record = issue(side_a=[A], side_b=[B])
    assert challenge.may_answer(record, B)
    assert not challenge.may_answer(record, A)     # that's just /tt schedule
    assert not challenge.may_answer(record, C)


def test_the_challenger_may_take_it_back(fake):
    record = issue(side_a=[A], side_b=[B])
    assert challenge.may_withdraw(record, A)
    assert not challenge.may_withdraw(record, B)


def test_only_one_challenge_stands_between_two_sides(fake):
    issue(side_a=[A], side_b=[B])
    assert challenge.open_between([A], [B])
    assert challenge.open_between([B], [A]), "either way round is the same pair"
    assert not challenge.open_between([A], [C])


def test_answering_frees_the_pair_to_challenge_again(fake):
    record = issue(side_a=[A], side_b=[B])
    challenge.claim(record["id"])
    challenge.decline(record, B)
    assert not challenge.open_between([A], [B])


def test_only_one_person_can_answer_a_challenge(fake):
    """Two of a doubles pair pressing Accept at once would otherwise put two
    fixtures up for the same match."""
    record = issue(side_a=[A], side_b=[C, D])
    assert challenge.claim(record["id"]) is True
    assert challenge.claim(record["id"]) is False


# --- accepting -------------------------------------------------------------

def test_accepting_puts_a_fixture_up(fake):
    now = store.now_ist()
    record = issue(side_a=[A], side_b=[B], games=5, first_to=3)
    fixture = challenge.accept(record, B, now=now)
    assert fixture["side_a"] == [A] and fixture["side_b"] == [B]
    assert betting.get(fixture["id"])["state"] == "open"
    assert record["state"] == "accepted" and record["fixture"] == fixture["id"]


def test_the_agreed_length_is_carried_onto_the_fixture(fake):
    record = issue(games=5, first_to=3)
    fixture = challenge.accept(record, B)
    assert fixture["note"] == "Best of 5 — first to 3"


def test_a_challenge_with_a_time_keeps_it(fake):
    now = store.now_ist()
    when = now + timedelta(hours=3)
    record = issue(when=when)
    fixture = challenge.accept(record, B, now=now)
    assert betting.starts_at(fixture) == when.replace(microsecond=0)


def test_a_challenge_with_no_time_starts_shortly_after_it_is_accepted(fake):
    now = store.now_ist()
    record = issue(when=None)
    fixture = challenge.accept(record, B, now=now)
    assert betting.starts_at(fixture) > now


def test_a_time_that_has_gone_by_while_it_sat_unanswered_is_pushed_out(fake):
    """Otherwise accepting would open a fixture that is already due, and
    betting would shut the instant it appeared."""
    now = store.now_ist()
    record = issue(when=now + timedelta(minutes=10))
    later = now + timedelta(hours=2)
    fixture = challenge.accept(record, B, now=later)
    assert betting.starts_at(fixture) > later
    assert fixture["state"] == "open"


def test_the_fixture_can_then_be_bet_on_like_any_other(fake):
    """The whole reason accepting makes a fixture rather than a third thing."""
    record = issue()
    fixture = challenge.accept(record, B)
    ok, _ = betting.place_bet(fixture, C, "a", 50)
    assert ok and betting.pool(fixture["id"])["total"] == 50


# --- declining, withdrawing, expiring --------------------------------------

def test_declining_closes_it_without_a_fixture(fake):
    record = issue()
    challenge.claim(record["id"])
    challenge.decline(record, B)
    assert record["state"] == "declined"
    assert betting.live() == []


def test_withdrawing_closes_it_too(fake):
    record = issue()
    challenge.claim(record["id"])
    challenge.withdraw(record, A)
    assert challenge.get(record["id"])["state"] == "withdrawn"


def test_an_unanswered_challenge_expires(fake):
    now = store.now_ist()
    record = challenge.issue([A], [B], 3, by=A, now=now)
    assert not challenge.is_expired(record, now + timedelta(hours=1))
    assert challenge.is_expired(
        record, now + timedelta(hours=challenge.EXPIRE_HOURS + 1))


def test_an_answered_challenge_never_expires(fake):
    now = store.now_ist()
    record = challenge.issue([A], [B], 3, by=A, now=now)
    challenge.decline(record, B, now)
    assert not challenge.is_expired(
        record, now + timedelta(hours=challenge.EXPIRE_HOURS + 1))


def test_the_sweep_closes_stale_challenges(fake):
    import standings
    now = store.now_ist()
    fresh = challenge.issue([A], [B], 3, by=A, now=now)
    stale = challenge.issue([C], [D], 3, by=C,
                            now=now - timedelta(hours=challenge.EXPIRE_HOURS + 2))
    out = standings.sweep_challenges(MagicMock(), now=now)
    assert out["expired"] == [stale["id"]]
    assert challenge.get(stale["id"])["state"] == "expired"
    assert challenge.get(fresh["id"])["state"] == "open"


# --- the ratings on it -----------------------------------------------------

def test_the_challenge_carries_both_ratings(fake):
    """A challenge is a claim about which of two numbers is better, so the
    numbers are on it."""
    store.ensure_players([A, B])
    players = store.get_players([A, B])
    line = bot.challenge_line(issue(), players=players)
    assert f"<@{A}> `{elo.START_RATING}`" in line
    assert f"<@{B}> `{elo.START_RATING}`" in line


def test_a_player_with_no_record_still_shows_a_rating(fake):
    """They are rated — at the opening rating, which is a fact, not a blank."""
    line = bot.challenge_line(issue(), players={})
    assert f"`{elo.START_RATING}`" in line


def test_the_favourite_is_named_from_the_ratings(fake):
    players = {A: {"rating": 1300}, B: {"rating": 1000}}
    line = bot.favourite_line([A], [B], players)
    assert f"<@{A}>" in line and "%" in line


def test_an_even_match_is_called_even(fake):
    players = {A: {"rating": 1005}, B: {"rating": 1000}}
    assert "Too close to call" in bot.favourite_line([A], [B], players)


def test_the_doubles_favourite_is_read_off_the_pair(fake):
    players = {A: {"rating": 1200}, B: {"rating": 1200},
               C: {"rating": 900}, D: {"rating": 900}}
    assert f"<@{A}>" in bot.favourite_line([A, B], [C, D], players)


def test_the_channel_post_shows_the_ratings_and_the_odds(fake):
    store.ensure_players([A, B])
    blocks = bot.challenge_blocks(issue())
    flat = " ".join(b["text"]["text"] if b["type"] == "section"
                    else " ".join(e["text"] for e in b["elements"])
                    for b in blocks)
    assert f"`{elo.START_RATING}`" in flat and "Too close to call" in flat


# --- the Slack routes ------------------------------------------------------

def test_the_command_posts_and_dms_the_buttons(fake):
    respond, client = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge(command(f"challenge {m(B)} best of 5"), respond, client)
    channels = [c.kwargs["channel"] for c in client.chat_postMessage.call_args_list]
    assert "C1" in channels, "the channel sees the callout"
    assert B in channels, "the challenged side gets the buttons"
    assert A in channels, "the challenger gets a way to take it back"


def test_the_channel_post_carries_no_buttons(fake):
    """Same rule as a pending result: the channel reads it, it doesn't rule."""
    respond, client = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge(command(f"challenge {m(B)}"), respond, client)
    posted = next(c for c in client.chat_postMessage.call_args_list
                  if c.kwargs["channel"] == "C1")
    assert not any(b["type"] == "actions" for b in posted.kwargs["blocks"])


def test_a_bare_challenge_command_opens_the_form(fake):
    client = MagicMock()
    bot.handle_challenge(command("challenge"), MagicMock(), client)
    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == bot.CHALLENGE_MODAL


def test_the_form_falls_back_to_the_typed_route_if_it_cannot_open(fake):
    client, respond = MagicMock(), MagicMock()
    client.views_open.side_effect = RuntimeError("no trigger")
    bot.handle_challenge(command("challenge"), respond, client)
    assert "type it instead" in said(respond)


# --- the form --------------------------------------------------------------

def test_the_form_offers_every_length_and_starts_on_the_default(fake):
    view = bot.build_challenge_modal(A, "C1")
    block = next(b for b in view["blocks"] if b["block_id"] == "length")
    values = [o["value"] for o in block["element"]["options"]]
    assert values == [k for k, _, _ in challenge.LENGTH_CHOICES]
    assert block["element"]["initial_option"]["value"] == challenge.DEFAULT_CHOICE


def test_every_option_is_labelled_the_way_the_challenge_will_read(fake):
    """So the menu can't promise "Best of 5" and post something else."""
    view = bot.build_challenge_modal(A, "C1")
    block = next(b for b in view["blocks"] if b["block_id"] == "length")
    for option in block["element"]["options"]:
        games, first_to = challenge.length_of(option["value"])
        assert option["text"]["text"] == challenge.length_note(
            {"games": games, "first_to": first_to})


def test_the_start_time_is_optional_on_the_form(fake):
    """Unlike the schedule form. "Play me some time today" is a real thing to
    say, and a required picker would turn it into a commitment nobody made."""
    view = bot.build_challenge_modal(A, "C1")
    when = next(b for b in view["blocks"] if b["block_id"] == "when")
    assert when["optional"] is True
    assert "initial_date_time" not in when["element"]


def test_the_form_preselects_you(fake):
    view = bot.build_challenge_modal(A, "C1")
    side_a = next(b for b in view["blocks"] if b["block_id"] == "side_a")
    assert side_a["element"]["initial_users"] == [A]


def test_the_form_asks_for_a_channel_only_from_the_shortcuts_menu(fake):
    assert not any(b.get("block_id") == "channel"
                   for b in bot.build_challenge_modal(A, "C1")["blocks"])
    assert any(b.get("block_id") == "channel"
               for b in bot.build_challenge_modal(A, pick_channel=True)["blocks"])


def _submit(side_a=(A,), side_b=(B,), length="bo5", epoch=None, channel="C1"):
    state = {
        "side_a": {"v": {"selected_users": list(side_a)}},
        "side_b": {"v": {"selected_users": list(side_b)}},
        "length": {"v": {"selected_option": {"value": length}}},
        "when": {"v": {"selected_date_time": epoch}},
    }
    return {"state": {"values": state}, "private_metadata": channel}


def test_submitting_the_form_puts_a_challenge_up(fake):
    ack, client = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge_modal(ack, {"user": {"id": A}}, _submit(), client)
    ack.assert_called_with()
    live = challenge.live()
    assert len(live) == 1
    assert (live[0]["games"], live[0]["first_to"]) == (5, 3)


def test_the_form_and_the_typed_route_produce_the_same_thing(fake):
    """One creator behind both, so neither can drift."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge_modal(MagicMock(), {"user": {"id": A}}, _submit(), client)
    from_form = challenge.live()[0]

    for cid in [r["id"] for r in challenge.live()]:
        challenge.claim(cid)
    bot.handle_challenge(command(f"challenge {m(B)} best of 5"),
                         MagicMock(), client)
    typed = [r for r in challenge.live()][0]
    for field in ("side_a", "side_b", "games", "first_to", "from"):
        assert from_form[field] == typed[field], field


def test_a_form_with_someone_on_both_sides_comes_back_as_a_field_error(fake):
    ack = MagicMock()
    bot.handle_challenge_modal(ack, {"user": {"id": A}},
                               _submit(side_a=[A], side_b=[A]))
    assert ack.call_args.kwargs["response_action"] == "errors"
    assert "side_b" in ack.call_args.kwargs["errors"]
    assert challenge.live() == []


def test_a_form_start_time_in_the_past_is_a_field_error(fake):
    ack = MagicMock()
    past = int((store.now_ist() - timedelta(hours=1)).timestamp())
    bot.handle_challenge_modal(ack, {"user": {"id": A}}, _submit(epoch=past))
    assert "when" in ack.call_args.kwargs["errors"]


def test_the_form_refuses_a_second_challenge_between_the_same_pair(fake):
    issue(side_a=[A], side_b=[B])
    ack = MagicMock()
    bot.handle_challenge_modal(ack, {"user": {"id": A}}, _submit())
    assert "already an open challenge" in ack.call_args.kwargs["errors"]["side_b"]


def test_a_stale_form_value_falls_back_rather_than_losing_the_challenge(fake):
    """A menu key we don't recognise came from a form opened before a deploy."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge_modal(MagicMock(), {"user": {"id": A}},
                               _submit(length="nonsense"), client)
    assert challenge.live()[0]["games"] == challenge.DEFAULT_GAMES


def test_the_shortcut_opens_the_form_with_a_channel_picker(fake):
    client = MagicMock()
    bot.handle_challenge_shortcut(MagicMock(), {"user": {"id": A},
                                                "trigger_id": "t"}, client)
    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == bot.CHALLENGE_MODAL
    assert any(b.get("block_id") == "channel" for b in view["blocks"])


def test_a_challenge_that_cannot_be_posted_is_not_left_open(fake):
    """Nowhere to see it means nobody can answer it."""
    client, respond = MagicMock(), MagicMock()
    client.chat_postMessage.side_effect = RuntimeError("channel_not_found")
    bot.handle_challenge(command(f"challenge {m(B)}"), respond, client)
    assert challenge.live() == []


def test_a_second_challenge_between_the_same_pair_is_refused(fake):
    respond, client = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.handle_challenge(command(f"challenge {m(B)}"), respond, client)
    bot.handle_challenge(command(f"challenge {m(B)} bo7"), respond, client)
    assert "already an open challenge" in said(respond)


def _press(action, cid, user):
    return {"user": {"id": user}, "trigger_id": "t",
            "actions": [{"action_id": action, "value": cid}]}


def test_accepting_by_button_puts_the_fixture_up(fake):
    record = issue(side_a=[A], side_b=[B])
    client, respond = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "9", "channel": "C1"}
    bot.handle_challenge_button(_press(bot.ACCEPT_ACTION, record["id"], B),
                                client, respond)
    assert challenge.get(record["id"])["state"] == "accepted"
    assert len(betting.live()) == 1


def test_the_challenger_cannot_accept_their_own(fake):
    record = issue(side_a=[A], side_b=[B])
    respond = MagicMock()
    bot.handle_challenge_button(_press(bot.ACCEPT_ACTION, record["id"], A),
                                MagicMock(), respond)
    assert "Only" in said(respond)
    assert challenge.get(record["id"])["state"] == "open"
    assert betting.live() == []


def test_a_bystander_cannot_answer(fake):
    record = issue(side_a=[A], side_b=[B])
    respond = MagicMock()
    bot.handle_challenge_button(_press(bot.DECLINE_ACTION, record["id"], C),
                                MagicMock(), respond)
    assert challenge.get(record["id"])["state"] == "open"


def test_declining_by_button_closes_it(fake):
    record = issue(side_a=[A], side_b=[B])
    bot.handle_challenge_button(_press(bot.DECLINE_ACTION, record["id"], B),
                                MagicMock(), MagicMock())
    assert challenge.get(record["id"])["state"] == "declined"
    assert betting.live() == []


def test_the_challenger_can_take_it_back(fake):
    record = issue(side_a=[A], side_b=[B])
    bot.handle_challenge_button(_press(bot.WITHDRAW_ACTION, record["id"], A),
                                MagicMock(), MagicMock())
    assert challenge.get(record["id"])["state"] == "withdrawn"


def test_answering_twice_is_refused(fake):
    record = issue(side_a=[A], side_b=[B])
    bot.handle_challenge_button(_press(bot.DECLINE_ACTION, record["id"], B),
                                MagicMock(), MagicMock())
    respond = MagicMock()
    bot.handle_challenge_button(_press(bot.ACCEPT_ACTION, record["id"], B),
                                MagicMock(), respond)
    assert "already declined" in said(respond)


def test_the_typed_route_works_when_the_dm_never_arrived(fake):
    record = issue(side_a=[A], side_b=[B])
    client, respond = MagicMock(), MagicMock()
    client.chat_postMessage.return_value = {"ts": "9", "channel": "C1"}
    bot.handle_answer_command(command(f"accept {record['id']}", user=B),
                              respond, client)
    assert challenge.get(record["id"])["state"] == "accepted"


def test_accept_with_no_number_lists_what_is_waiting_on_you(fake):
    record = issue(side_a=[A], side_b=[B])
    respond = MagicMock()
    bot.handle_answer_command(command("accept", user=B), respond, MagicMock())
    assert f"#{record['id']}" in said(respond)


def test_the_challenges_list_shows_what_is_open(fake):
    record = issue(side_a=[A], side_b=[B], games=5, first_to=3)
    respond = MagicMock()
    bot.handle_challenges(command("challenges"), respond)
    out = said(respond)
    assert f"#{record['id']}" in out and "Best of 5" in out


# --- open calls: a band instead of a name ----------------------------------

NOW = None      # parse_open_challenge only needs one when a time is given


def rated(uid, rating, games=8):
    """A player sitting at a known rating on both boards, past placement."""
    player = store.new_player()
    player.update({"rating": rating, "games_won": games, "games_lost": 0,
                   "matches": games, "peak": rating})
    for prefix in (store.SINGLES, store.DOUBLES):
        player[prefix + "rating"] = rating
        player[prefix + "games_won"] = games
        player[prefix + "games_lost"] = 0
        player[prefix + "matches"] = games
        player[prefix + "peak"] = rating
    store.kv.pipeline([["HSET", store.player_key(uid)] + store._flatten(player)])
    store.kv.sadd(store.PLAYERS_KEY, uid)
    return player


def open_call(side_a=(A,), band=(900, 1100), games=3, first_to=2, when=None):
    return challenge.issue(list(side_a), [], games, by=side_a[0],
                           first_to=first_to, starts_at=when, channel="C1",
                           band=band)


def test_the_word_open_is_what_picks_the_other_route():
    assert parsing.split_open("open ±100 bo5") == (True, "±100 bo5")
    assert parsing.split_open("anyone 900-1100") == (True, "900-1100")
    assert parsing.split_open(f"<@{B}> bo5") == (False, f"<@{B}> bo5")


@pytest.mark.parametrize("text,band", [
    ("900-1100", (900, 1100)),
    ("1100 to 1250", (1100, 1250)),
    ("1250-1100", (1100, 1250)),        # either way round
    ("+150", (1200, 1350)),
    ("-150", (1050, 1200)),
    ("±100", (1100, 1300)),
    ("+-100", (1100, 1300)),
])
def test_the_ways_to_say_a_range(text, band):
    assert parsing.parse_band(text, rating=1200)[0] == band


def test_a_range_wider_than_everyone_is_not_a_range():
    with pytest.raises(parsing.ParseError):
        parsing.parse_band("200-1400", rating=1200)


def test_a_relative_range_needs_to_know_your_rating():
    """Rather than quietly treating an unrated player as 1000 and calling it
    their level."""
    with pytest.raises(parsing.ParseError):
        parsing.parse_band("±100", rating=None)


def test_no_range_given_is_the_band_around_you():
    side_a, band, _, _, _ = parsing.parse_open_challenge(
        "", caller=A, rating=1200, now=store.now_ist())
    assert band == (1200 - parsing.DEFAULT_BAND, 1200 + parsing.DEFAULT_BAND)
    assert side_a == [A]


def test_a_mention_on_an_open_call_is_your_own_partner():
    """The whole difference from a directed challenge: there is no opponent to
    read, so whoever you name is on your side and the taker brings their own."""
    side_a, _, _, _, _ = parsing.parse_open_challenge(
        f"<@{B}> ±100", caller=A, rating=1200, now=store.now_ist())
    assert side_a == [A, B]


def test_three_on_a_side_is_not_a_side():
    with pytest.raises(parsing.ParseError):
        parsing.parse_open_challenge(f"<@{B}> <@{C}> ±100", caller=A,
                                     rating=1200, now=store.now_ist())


def test_the_length_reads_the_same_as_on_a_directed_challenge():
    _, _, games, first_to, _ = parsing.parse_open_challenge(
        "bo7 900-1100", caller=A, now=store.now_ist())
    assert (games, first_to) == (7, 4)


# --- who may take one ------------------------------------------------------

def test_anyone_outside_it_may_answer_an_open_call(fake):
    record = open_call()
    assert challenge.may_answer(record, B)
    assert challenge.may_answer(record, C)


def test_you_cannot_take_your_own_call(fake):
    """That is `/tt schedule`, which already exists."""
    record = open_call(side_a=(A, B))
    assert not challenge.may_answer(record, A)
    assert not challenge.may_answer(record, B)      # nor the partner named in it


def test_the_band_admits_its_ends(fake):
    record = open_call(band=(900, 1100))
    assert challenge.admits(record, 900) and challenge.admits(record, 1100)
    assert not challenge.admits(record, 899)
    assert not challenge.admits(record, 1101)


def test_a_directed_challenge_has_no_band_and_admits_whoever_it_named(fake):
    assert challenge.admits(issue(), 5000)
    assert challenge.band_of(issue()) is None
    assert not challenge.is_open_call(issue())


def test_one_standing_offer_each(fake):
    """Five identical callouts from one player is a spammed channel, not five
    chances of a game."""
    record = open_call()
    assert challenge.open_call_by(A)["id"] == record["id"]
    assert challenge.open_call_by(B) is None


# --- through the command ---------------------------------------------------

def test_an_open_call_goes_up_with_a_button_anyone_can_press(fake, client=None):
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    rated(A, 1000)
    respond = MagicMock()
    bot.handle_challenge(command("challenge open 900-1100 bo5"), respond, client)
    record = challenge.live()[0]
    assert record["side_b"] == [] and record["band"] == [900, 1100]

    blocks = bot.challenge_blocks(record)
    posted = said(MagicMock(call_args_list=[]))          # blocks checked directly
    head = blocks[0]["text"]["text"]
    assert "calling anyone out" in head and "900–1100" in head
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert actions, "an open call needs a button in the channel"
    # Nobody was DM'd: there is no named audience to send buttons to.
    assert client.chat_postMessage.call_count == 1


def test_a_taker_inside_the_band_gets_the_fixture(fake):
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    rated(A, 1000)
    rated(B, 1050)
    record = open_call(band=(900, 1100))
    assert bot.answer_challenge(record["id"], B, "accept", client) is None
    settled = challenge.get(record["id"])
    assert settled["state"] == "accepted" and settled["side_b"] == [B]
    assert betting.get(settled["fixture"])


def test_a_taker_outside_the_band_is_told_the_numbers(fake):
    client = MagicMock()
    rated(A, 1000)
    rated(B, 1400)
    record = open_call(band=(900, 1100))
    said_back = bot.answer_challenge(record["id"], B, "accept", client)
    assert "900–1100" in said_back and "1400" in said_back


def test_a_refusal_leaves_the_call_open_for_somebody_else(fake):
    """Checked before the claim, so a wrong presser doesn't burn the challenge."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    rated(A, 1000)
    rated(B, 1400)
    rated(C, 1000)
    record = open_call(band=(900, 1100))
    bot.answer_challenge(record["id"], B, "accept", client)
    assert challenge.get(record["id"])["state"] == "open"
    assert bot.answer_challenge(record["id"], C, "accept", client) is None
    assert challenge.get(record["id"])["state"] == "accepted"


def test_only_the_first_taker_gets_it(fake):
    """Two people pressing at once is the case the claim exists for, and an open
    call is the first time the race has been a real one."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    for uid in (A, B, C):
        rated(uid, 1000)
    record = open_call(band=(900, 1100))
    assert bot.answer_challenge(record["id"], B, "accept", client) is None
    second = bot.answer_challenge(record["id"], C, "accept", client)
    assert "already" in second
    assert challenge.get(record["id"])["side_b"] == [B]


# --- doubles ---------------------------------------------------------------

def test_a_doubles_call_needs_a_pair_to_answer_it(fake):
    client = MagicMock()
    for uid in (A, B, C, D):
        rated(uid, 1000)
    record = open_call(side_a=(A, B), band=(900, 1100))
    assert challenge.side_size(record) == 2
    alone = bot.answer_challenge(record["id"], C, "accept", client)
    assert "bring someone" in alone
    assert challenge.get(record["id"])["state"] == "open"


def test_a_pair_takes_it_and_both_go_on_the_fixture(fake):
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    for uid in (A, B, C, D):
        rated(uid, 1000)
    record = open_call(side_a=(A, B), band=(900, 1100))
    assert bot.answer_challenge(record["id"], C, "accept", client,
                                partner=D) is None
    settled = challenge.get(record["id"])
    assert sorted(settled["side_b"]) == sorted([C, D])
    fixture = betting.get(settled["fixture"])
    assert sorted(fixture["side_b"]) == sorted([C, D])


def test_a_pair_is_judged_on_the_average_of_the_two(fake):
    """So a 1400 cannot take a 900-1100 call by bringing a 1000 along — the two
    of them average 1200, which is not what the call asked for."""
    client = MagicMock()
    rated(A, 1000)
    rated(B, 1000)
    rated(C, 1400)
    rated(D, 1000)
    record = open_call(side_a=(A, B), band=(900, 1100))
    refused = bot.answer_challenge(record["id"], C, "accept", client,
                                   partner=D)
    assert "1100" in refused and "average" in refused


def test_a_pair_averaging_onto_the_edge_is_admitted(fake):
    """1400 and 800 average to exactly 1100, and the band's ends are in it."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    rated(A, 1000)
    rated(B, 1000)
    rated(C, 1400)
    rated(D, 800)
    record = open_call(side_a=(A, B), band=(900, 1100))
    assert bot.answer_challenge(record["id"], C, "accept", client,
                                partner=D) is None


def test_a_partner_already_in_the_call_is_refused(fake):
    client = MagicMock()
    for uid in (A, B, C):
        rated(uid, 1000)
    record = open_call(side_a=(A, B), band=(900, 1100))
    refused = bot.answer_challenge(record["id"], C, "accept", client, partner=B)
    assert "already in that one" in refused


def test_a_singles_call_is_just_you(fake):
    client = MagicMock()
    for uid in (A, B, C):
        rated(uid, 1000)
    record = open_call(band=(900, 1100))
    refused = bot.answer_challenge(record["id"], B, "accept", client, partner=C)
    assert "just you" in refused


# --- taking one back -------------------------------------------------------

def test_an_open_call_can_be_taken_back(fake):
    """It carries no DM, so its buttons are nowhere — without a command there
    would be no way to withdraw one at all."""
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    rated(A, 1000)
    record = open_call()
    respond = MagicMock()
    bot.handle_answer_command({"user_id": A, "text": f"withdraw {record['id']}"},
                              respond, client)
    assert challenge.get(record["id"])["state"] == "withdrawn"


def test_somebody_elses_call_is_not_yours_to_take_back(fake):
    client = MagicMock()
    record = open_call()
    refused = bot.answer_challenge(record["id"], C, "withdraw", client)
    assert "threw it down" in refused
    assert challenge.get(record["id"])["state"] == "open"


def test_the_outstanding_list_says_what_an_open_call_is_open_to(fake):
    open_call(band=(900, 1100))
    respond = MagicMock()
    bot.handle_challenges({"user_id": A, "text": "challenges"}, respond)
    printed = respond.call_args[0][0]
    assert "anyone" in printed and "900–1100" in printed


# --- an open call is not anybody's to turn down ----------------------------

def test_a_bystander_cannot_decline_an_open_call(fake):
    """It is addressed to the channel, so nobody has been asked and nobody can
    answer for everyone. One uninterested passer-by typing `decline` would
    otherwise close an invitation meant for forty people."""
    record = challenge.issue([A], [], 3, by=A, first_to=2, channel="C1",
                             band=(900, 1100))
    out = bot.answer_challenge(record["id"], C, "decline", MagicMock())
    assert "nothing to turn down" in out
    assert challenge.get(record["id"])["state"] == "open"
    assert [r["id"] for r in challenge.live()] == [record["id"]]


def test_not_even_the_person_who_posted_it_declines_an_open_call(fake):
    """Theirs to withdraw, which says what actually happened, not to decline."""
    record = challenge.issue([A], [], 3, by=A, first_to=2, channel="C1",
                             band=(900, 1100))
    out = bot.answer_challenge(record["id"], A, "decline", MagicMock())
    assert "withdraw" in out
    assert challenge.get(record["id"])["state"] == "open"


def test_an_open_call_can_still_be_taken_back_by_its_owner(fake):
    record = challenge.issue([A], [], 3, by=A, first_to=2, channel="C1",
                             band=(900, 1100))
    assert bot.answer_challenge(record["id"], A, "withdraw", MagicMock()) is None
    assert challenge.get(record["id"])["state"] == "withdrawn"


def test_a_directed_challenge_is_still_declinable_by_its_target(fake):
    """The fix narrows open calls only — being asked is what gives you the
    standing to say no, and on a directed challenge you were asked."""
    record = issue(side_a=[A], side_b=[B])
    assert bot.answer_challenge(record["id"], B, "decline", MagicMock()) is None
    assert challenge.get(record["id"])["state"] == "declined"


def test_a_bystander_still_cannot_decline_a_directed_challenge(fake):
    record = issue(side_a=[A], side_b=[B])
    out = bot.answer_challenge(record["id"], C, "decline", MagicMock())
    assert "Only" in out
    assert challenge.get(record["id"])["state"] == "open"


def test_declining_and_accepting_are_gated_separately(fake):
    """C may take the open call but may not kill it — the two questions have
    different answers, which is the whole point of may_decline()."""
    record = challenge.issue([A], [], 3, by=A, first_to=2, channel="C1",
                             band=(900, 1100))
    assert challenge.may_answer(record, C) is True
    assert challenge.may_decline(record, C) is False
