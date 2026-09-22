"""The wall of shame — results thrown out, challenges ducked and ghosted.

Counted at the moment each thing happens rather than derived afterwards,
because most of these destroy the record they happened to: throwing a result out
deletes its pending record, and a challenge ages out of Redis within the week.
So the tests that matter are the ones driving the real flows and checking a
counter moved.
"""
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

import betting
import bot
import challenge
import elo
import shame
import standings
import store
from tests.fake_kv import FakeRedis

A, B, C, D = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1"


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("TT_ADMINS", "")
    redis = FakeRedis()
    with redis.patched():
        yield redis


# --- the counters ----------------------------------------------------------

def test_nothing_is_on_the_wall_to_begin_with(fake):
    assert shame.board() == [] and shame.total() == 0


def test_a_count_survives_being_read_back(fake):
    shame.record(A, "rejected")
    shame.record(A, "rejected")
    assert shame.for_player(A) == {"rejected": 2}


def test_an_unknown_kind_is_ignored_rather_than_stored(fake):
    shame.record(A, "sulked")
    assert shame.for_player(A) == {}


def test_recording_never_raises_even_when_the_database_is_unhappy(fake, monkeypatch):
    """It hangs off a match flow. It has no business turning a confirmed result
    into an error somebody sees."""
    import kv
    monkeypatch.setattr(kv, "hincrby", lambda *a, **k: (_ for _ in ()).throw(RuntimeError))
    shame.record(A, "rejected")          # must not raise


def test_the_worst_offender_is_first(fake):
    shame.record(A, "ghosted")
    for _ in range(3):
        shame.record(B, "rejected")
    assert [uid for uid, _, _ in shame.board()] == [B, A]


def test_a_thrown_out_result_weighs_more_than_a_ghosted_challenge(fake):
    """It cost somebody else something: they have to log it again."""
    assert shame.score({"rejected": 1}) > shame.score({"ghosted": 1})


def test_ties_break_the_same_way_every_time(fake):
    shame.record(B, "ducked")
    shame.record(A, "ducked")
    assert shame.board() == sorted(shame.board(), key=lambda r: (-r[2], r[0]))


def test_clearing_one_player_leaves_the_rest(fake):
    shame.record(A, "ducked")
    shame.record(B, "ducked")
    shame.clear(A)
    assert shame.for_player(A) == {} and shame.for_player(B) == {"ducked": 1}


def test_clearing_everything_empties_the_wall(fake):
    shame.record(A, "ducked")
    shame.clear()
    assert shame.board() == []


# --- the real flows put people on it ---------------------------------------

def play_pending(logged_by=A, other=B):
    return store.create_pending([logged_by], [other], [(21, 15), (21, 17)],
                                logged_by=logged_by)


def test_throwing_out_a_result_counts_against_whoever_threw_it(fake):
    record = play_pending(logged_by=A, other=B)
    bot.handle_dispute({"user": {"id": B},
                        "actions": [{"action_id": bot.DISPUTE_ACTION,
                                     "value": record["id"]}]},
                       MagicMock(), MagicMock())
    assert shame.for_player(B) == {"rejected": 1}


def test_taking_back_your_own_mistake_is_not_shameful(fake):
    """The person who logged it pressing the same button is cancelling their own
    typo, which is the opposite of refusing to accept a result."""
    record = play_pending(logged_by=A, other=B)
    bot.handle_dispute({"user": {"id": A},
                        "actions": [{"action_id": bot.DISPUTE_ACTION,
                                     "value": record["id"]}]},
                       MagicMock(), MagicMock())
    assert shame.for_player(A) == {}


def test_declining_a_challenge_counts(fake):
    record = challenge.issue([A], [B], 3, by=A, first_to=2, channel="C1")
    bot.answer_challenge(record["id"], B, "decline", MagicMock())
    assert shame.for_player(B) == {"ducked": 1}


def test_accepting_one_does_not(fake):
    record = challenge.issue([A], [B], 3, by=A, first_to=2, channel="C1")
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "1", "channel": "C1"}
    bot.answer_challenge(record["id"], B, "accept", client)
    assert shame.for_player(B) == {}


def test_withdrawing_your_own_challenge_is_not_shameful(fake):
    record = challenge.issue([A], [B], 3, by=A, first_to=2, channel="C1")
    bot.answer_challenge(record["id"], A, "withdraw", MagicMock())
    assert shame.for_player(A) == {}


def test_never_answering_a_challenge_counts_as_ghosting(fake):
    now = store.now_ist()
    challenge.issue([A], [B], 3, by=A, first_to=2, channel="C1",
                    now=now - timedelta(hours=challenge.EXPIRE_HOURS + 2))
    standings.sweep_challenges(MagicMock(), now=now)
    assert shame.for_player(B) == {"ghosted": 1}
    assert shame.for_player(A) == {}, "the person who asked didn't ghost anyone"


def test_an_open_call_nobody_takes_shames_nobody(fake):
    """It was addressed to the channel. Nobody was asked, so nobody ignored it."""
    now = store.now_ist()
    challenge.issue([A], [], 3, by=A, first_to=2, channel="C1", band=(900, 1100),
                    now=now - timedelta(hours=challenge.EXPIRE_HOURS + 2))
    standings.sweep_challenges(MagicMock(), now=now)
    assert shame.board() == []


def test_calling_a_fixture_off_counts_against_whoever_called_it(fake):
    record = betting.schedule([A], [B], store.now_ist() + timedelta(hours=1),
                              created_by=A, channel="C1")
    bot.handle_cancel_fixture({"user": {"id": A},
                               "actions": [{"action_id": bot.CANCEL_FIXTURE_ACTION,
                                            "value": record["id"]}]},
                              MagicMock(), MagicMock())
    assert shame.for_player(A) == {"bailed": 1}


def test_a_fixture_nobody_ever_reports_shames_everyone_in_it(fake):
    now = store.now_ist()
    betting.schedule([A], [B], now - timedelta(hours=betting.ABANDON_HOURS + 2),
                     created_by=A, channel="C1", now=now - timedelta(days=3))
    standings.sweep_fixtures(MagicMock(), now=now)
    assert shame.for_player(A) == {"bailed": 1}
    assert shame.for_player(B) == {"bailed": 1}


# --- the command -----------------------------------------------------------

def command(text, user=A):
    return {"user_id": user, "text": text, "channel_id": "C1"}


def said(mock):
    import json
    return "\n".join(json.dumps(a, default=str, ensure_ascii=False)
                     for c in mock.call_args_list
                     for a in list(c.args) + list(c.kwargs.values()))


def test_an_empty_wall_says_so(fake):
    respond = MagicMock()
    bot.handle_shame(command("shame"), respond)
    assert "Nothing on it" in said(respond)


def test_the_wall_lists_the_worst_first(fake):
    for _ in range(3):
        shame.record(B, "rejected")
    shame.record(A, "ducked")
    respond = MagicMock()
    bot.handle_shame(command("shame"), respond)
    out = said(respond)
    assert out.index(B) < out.index(A)


def test_one_player_can_be_looked_up(fake):
    shame.record(B, "ducked")
    respond = MagicMock()
    bot.handle_shame(command(f"shame <@{B}>"), respond)
    assert "ducked" in said(respond)


def test_a_clean_player_is_told_so(fake):
    respond = MagicMock()
    bot.handle_shame(command(f"shame <@{B}>"), respond)
    assert "nothing against their name" in said(respond)


def test_the_wall_says_it_is_a_joke(fake):
    """If it ever stops reading as one, the board goes, not the counters."""
    shame.record(B, "rejected")
    respond = MagicMock()
    bot.handle_shame(command("shame"), respond)
    out = said(respond)
    assert "not a charge sheet" in out and "ladder working" in out
