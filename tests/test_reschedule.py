"""Moving a scheduled match.

Plans change, and before this the only way to move one was to call it off and
put it up again — which hands every stake back and loses the pool. The bet was
on who wins, not on when they played, so the time moves and the stakes stand.

The rule worth arguing about is at the bottom: a betting window that has already
shut does not reopen because somebody postponed the match.
"""
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import betting
import bot
import parsing
import store
from tests.fake_kv import FakeRedis

A, B, C, D = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1"
ADMIN = "U0ADM1"


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("TT_ADMINS", ADMIN)
    redis = FakeRedis()
    with redis.patched():
        yield redis


def fixture_at(minutes=60, side_a=None, side_b=None, by=None, now=None):
    now = now or store.now_ist()
    return betting.schedule(side_a or [A], side_b or [B],
                            now + timedelta(minutes=minutes),
                            created_by=by or A, channel="C1", now=now)


# --- the move itself -------------------------------------------------------

def test_moving_a_fixture_changes_when_it_starts(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    ok, why = betting.reschedule(record, now + timedelta(hours=3), by=A, now=now)
    assert ok, why
    assert betting.starts_at(betting.get(record["id"])) == \
        (now + timedelta(hours=3)).replace(microsecond=0)


def test_the_stakes_stand(fake):
    """The whole point. Calling it off and re-posting refunds everyone."""
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.place_bet(record, C, "a", 300, now=now)
    betting.place_bet(record, D, "b", 100, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=A, now=now)
    assert betting.pool(record["id"])["total"] == 400
    assert betting.bets(record["id"])[C] == ("a", 300)
    assert betting.balance(C) == betting.START_SPINS - 300


def test_an_open_fixture_stays_open(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=A, now=now)
    assert betting.get(record["id"])["state"] == "open"
    ok, _ = betting.place_bet(betting.get(record["id"]), C, "a", 50,
                              now=now + timedelta(hours=1))
    assert ok, "a match moved later should still take bets until it is due"


def test_moving_it_is_recorded(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=B, now=now)
    betting.reschedule(betting.get(record["id"]), now + timedelta(hours=5),
                       by=B, now=now)
    stored = betting.get(record["id"])
    assert stored["moves"] == 2 and stored["moved_by"] == B


# --- what it refuses -------------------------------------------------------

def test_a_time_in_the_past_is_refused(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    ok, why = betting.reschedule(record, now - timedelta(minutes=1), now=now)
    assert not ok and "gone by" in why


def test_too_far_out_is_refused(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    ok, why = betting.reschedule(
        record, now + timedelta(days=parsing.MAX_LEAD_DAYS + 1), now=now)
    assert not ok and "days out" in why


def test_moving_it_to_when_it_already_was_is_refused(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    ok, why = betting.reschedule(record, betting.starts_at(record), now=now)
    assert not ok and "already set for" in why


@pytest.mark.parametrize("state", ["settled", "void"])
def test_a_finished_fixture_cannot_be_moved(fake, state):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    record["state"] = state
    ok, why = betting.reschedule(record, now + timedelta(hours=3), now=now)
    assert not ok and state in why


# --- the rule that matters -------------------------------------------------

def test_moving_a_fixture_reopens_betting(fake):
    """A match that hasn't been played yet is one people should be able to back,
    so the window follows the clock: shut by the old start time going by,
    reopened by the new one being in the future."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    assert record["state"] == "closed"

    ok, why = betting.reschedule(record, later + timedelta(hours=3), by=A, now=later)
    assert ok, why
    moved = betting.get(record["id"])
    assert moved["state"] == "open", "moving it should let people back it again"

    placed, _ = betting.place_bet(moved, C, "a", 50, now=later)
    assert placed


def test_a_reopened_window_shuts_again_at_the_new_time(fake):
    now = store.now_ist()
    record = fixture_at(10, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    betting.reschedule(record, later + timedelta(hours=1), by=A, now=later)
    moved = betting.get(record["id"])
    placed, message = betting.place_bet(moved, C, "a", 50,
                                        now=later + timedelta(hours=2))
    assert not placed and "closed" in message


def test_a_reopened_fixture_says_so(fake):
    """The guard is daylight, not a rule: whoever bets after a move can see that
    the match may already have started once."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    betting.reschedule(record, later + timedelta(hours=3), by=A, now=later)
    assert betting.get(record["id"])["reopened"] is True


def test_an_open_fixture_moved_was_never_reopened(fake):
    """Nothing to flag — its window never shut in the first place."""
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=A, now=now)
    assert not betting.get(record["id"]).get("reopened")


def test_the_stakes_already_in_survive_a_reopening(fake):
    """Reopening lets more in; it doesn't hand back what was already staked."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    betting.place_bet(record, C, "a", 300, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    betting.reschedule(record, later + timedelta(hours=3), by=A, now=later)
    assert betting.pool(record["id"])["total"] == 300
    betting.place_bet(betting.get(record["id"]), D, "b", 100, now=later)
    assert betting.pool(record["id"])["total"] == 400


def test_a_moved_fixture_is_abandoned_from_its_new_time(fake):
    """Otherwise the sweep would refund a match that has been postponed into
    the future, because the *old* time was long enough ago."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    stale = now + timedelta(hours=betting.ABANDON_HOURS + 1)
    assert betting.is_abandoned(record, stale)
    betting.reschedule(record, stale + timedelta(hours=2), by=A, now=stale)
    assert not betting.is_abandoned(betting.get(record["id"]), stale)


# --- who may -------------------------------------------------------------

def test_the_players_and_the_organiser_may_move_it(fake):
    record = fixture_at(60, side_a=[A], side_b=[B], by=C)
    for uid in (A, B, C, ADMIN):
        assert bot.may_move(record, uid), uid


def test_a_bystander_may_not(fake):
    record = fixture_at(60, side_a=[A], side_b=[B], by=A)
    assert not bot.may_move(record, D)


def test_a_bystander_is_turned_away_and_nothing_moves(fake):
    now = store.now_ist()
    record = fixture_at(60, side_a=[A], side_b=[B], by=A, now=now)
    was = betting.starts_at(record)
    out = bot.apply_reschedule(record["id"], now + timedelta(hours=3), D,
                               MagicMock(), now)
    assert "Only the players" in out
    assert betting.starts_at(betting.get(record["id"])) == was


# --- the Slack routes ------------------------------------------------------

def command(text, user=A):
    return {"user_id": user, "text": text, "channel_id": "C1", "trigger_id": "t"}


def said(mock):
    import json
    return "\n".join(json.dumps(a, default=str, ensure_ascii=False)
                     for c in mock.call_args_list
                     for a in list(c.args) + list(c.kwargs.values()))


def test_the_typed_command_moves_it(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    respond, client = MagicMock(), MagicMock()
    bot.handle_reschedule(command(f"reschedule {record['id']} in 4h"), respond, client)
    assert "Moved" in said(respond)
    assert betting.starts_at(betting.get(record["id"])) > betting.starts_at(record)


def test_the_bare_command_lists_what_you_could_move(fake):
    record = fixture_at(60, side_a=[A], side_b=[B])
    respond = MagicMock()
    bot.handle_reschedule(command("reschedule"), respond, MagicMock())
    assert f"#{record['id']}" in said(respond)


def test_the_bare_command_lists_nothing_that_is_not_yours(fake):
    fixture_at(60, side_a=[B], side_b=[C], by=B)
    respond = MagicMock()
    bot.handle_reschedule(command("reschedule", user=D), respond, MagicMock())
    assert "no fixtures to move" in said(respond)


def test_an_unknown_fixture_says_so(fake):
    respond = MagicMock()
    bot.handle_reschedule(command("reschedule 999 7pm"), respond, MagicMock())
    assert "no fixture by that number" in said(respond).lower()


def test_moving_it_tells_the_channel(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.place_bet(record, C, "a", 300, now=now)
    client = MagicMock()
    bot.apply_reschedule(record["id"], now + timedelta(hours=3), A, client, now)
    posted = client.chat_postMessage.call_args.kwargs
    assert posted["channel"] == "C1"
    assert "moved" in posted["text"].lower()
    assert "stakes stand" in posted["text"].lower()


def test_a_reopened_fixture_tells_the_channel_betting_is_back_on(fake):
    now = store.now_ist()
    record = fixture_at(10, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    client = MagicMock()
    bot.apply_reschedule(record["id"], later + timedelta(hours=3), A, client, later)
    said = client.chat_postMessage.call_args.kwargs["text"].lower()
    assert "betting is open again" in said


def test_the_fixture_message_offers_the_button_while_it_is_open(fake):
    record = fixture_at(60)
    ids = [el["action_id"] for b in bot.fixture_blocks(record)
           if b["type"] == "actions" for el in b["elements"]]
    assert bot.RESCHEDULE_ACTION in ids


def test_a_closed_fixture_still_offers_it_but_not_the_bets(fake):
    """Running late is exactly when the window has already shut, and there was
    no button to press."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    betting.close_if_due(record, now + timedelta(minutes=11))
    ids = [el["action_id"] for b in bot.fixture_blocks(record)
           if b["type"] == "actions" for el in b["elements"]]
    assert bot.RESCHEDULE_ACTION in ids and bot.CANCEL_FIXTURE_ACTION in ids
    assert bot.BET_ACTION_A not in ids


def test_the_message_says_it_has_been_moved(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=B, now=now)
    blocks = bot.fixture_blocks(betting.get(record["id"]), now)
    flat = " ".join(el["text"] for b in blocks if b["type"] == "context"
                    for el in b["elements"])
    assert "Moved" in flat and "Stakes stand" in flat


def test_the_fixture_message_warns_that_betting_reopened(fake):
    """The channel note scrolls away; this sits next to the bet buttons."""
    now = store.now_ist()
    record = fixture_at(10, now=now)
    later = now + timedelta(minutes=11)
    betting.close_if_due(record, later)
    betting.reschedule(record, later + timedelta(hours=3), by=A, now=later)
    flat = " ".join(el["text"] for b in bot.fixture_blocks(betting.get(record["id"]), later)
                    if b["type"] == "context" for el in b["elements"])
    assert "Betting reopened" in flat


def test_a_fixture_moved_before_it_was_due_carries_no_such_warning(fake):
    now = store.now_ist()
    record = fixture_at(60, now=now)
    betting.reschedule(record, now + timedelta(hours=3), by=A, now=now)
    flat = " ".join(el["text"] for b in bot.fixture_blocks(betting.get(record["id"]), now)
                    if b["type"] == "context" for el in b["elements"])
    assert "Moved" in flat and "reopened" not in flat
