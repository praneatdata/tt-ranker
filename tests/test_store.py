"""Persistence: registration, the pending queue, applying a match, and undo."""
from datetime import timedelta

import pytest

import elo
import store
from tests.fake_kv import FakeRedis

A, B, C, D = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1"
WIN_2_1 = [(11, 7), (9, 11), (11, 5)]


@pytest.fixture
def fake():
    redis = FakeRedis()
    with redis.patched():
        yield redis


def log(side_a, side_b, games=WIN_2_1, by=None, now=None):
    return store.create_pending(side_a, side_b, games, logged_by=by or side_a[0], now=now)


def confirm(record, by=None, **kw):
    assert store.claim_pending(record["id"])
    return store.apply_match(record, confirmed_by=by, **kw)


# --- registration ----------------------------------------------------------

def test_a_new_player_starts_at_the_opening_rating(fake):
    assert store.ensure_players([A]) == [A]
    assert store.get_player(A)["rating"] == elo.START_RATING
    assert store.get_player(A)["matches"] == 0


def test_registering_twice_changes_nothing(fake):
    store.ensure_players([A])
    store.get_player(A)  # established
    assert store.ensure_players([A, B]) == [B]


def test_an_unregistered_player_reads_as_absent(fake):
    assert store.get_player(A) is None
    assert store.get_players([A, B]) == {}


def test_load_for_match_invents_a_record_rather_than_failing(fake):
    """A crash between the SADD and the HSET would leave a uid with no hash;
    that player must rate as a newcomer, not blow up a confirmation."""
    loaded = store.load_for_match([A])
    assert loaded[A]["rating"] == elo.START_RATING


# --- the pending queue -----------------------------------------------------

def test_a_logged_match_is_parked_not_rated(fake):
    store.ensure_players([A, B])
    record = log([A], [B])
    assert store.get_pending(record["id"])["side_b"] == [B]
    assert fake.rating(A) == elo.START_RATING  # untouched until confirmed


def test_only_one_caller_can_claim_a_pending_match(fake):
    record = log([A], [B])
    assert store.claim_pending(record["id"]) is True
    assert store.claim_pending(record["id"]) is False


def test_pending_ids_are_listed_oldest_first(fake):
    first, second = log([A], [B]), log([A], [C])
    assert [r["id"] for r in store.list_pending()] == [first["id"], second["id"]]


def test_a_pending_record_whose_json_expired_leaves_the_index(fake):
    record = log([A], [B])
    del fake.data[store.pending_key(record["id"])]  # as Redis would on TTL
    assert store.list_pending() == []
    assert fake.data[store.PENDING_KEY] == set()


def test_expiry_is_measured_from_when_it_was_logged(fake):
    now = store.now_ist()
    record = log([A], [B], now=now)
    assert not store.is_expired(record, now + timedelta(hours=store.AUTO_CONFIRM_HOURS - 1))
    assert store.is_expired(record, now + timedelta(hours=store.AUTO_CONFIRM_HOURS))


def test_disputing_removes_every_trace(fake):
    record = log([A], [B])
    store.drop_pending(record["id"])
    assert store.get_pending(record["id"]) is None
    assert store.list_pending() == []


# --- applying --------------------------------------------------------------

def test_confirming_moves_both_ratings_in_opposite_directions(fake):
    blob = confirm(log([A], [B]), by=B)
    assert fake.rating(A) > elo.START_RATING > fake.rating(B)
    assert blob["deltas"][A] == -blob["deltas"][B]
    assert fake.rating(A) == blob["after"][A]


def test_confirming_registers_players_nobody_registered(fake):
    confirm(log([A], [B]), by=B)
    assert sorted(fake.data[store.PLAYERS_KEY]) == [A, B]


def test_the_counters_behind_the_player_card(fake):
    confirm(log([A], [B]), by=B)
    a, b = fake.player(A), fake.player(B)
    assert (a["matches"], a["wins"], a["losses"]) == (1, 1, 0)
    assert (a["games_won"], a["games_lost"]) == (2, 1)
    assert (a["points_won"], a["points_lost"]) == (31, 23)
    assert (b["wins"], b["losses"], b["games_won"]) == (0, 1, 1)
    assert a["peak"] == a["rating"]


def test_a_winning_streak_builds_and_a_loss_resets_it(fake):
    for _ in range(3):
        confirm(log([A], [B]), by=B)
    assert fake.player(A)["streak"] == 3
    confirm(log([A], [B], games=[(5, 11), (7, 11)]), by=B)
    assert fake.player(A)["streak"] == -1
    assert fake.player(A)["best_streak"] == 3


def test_an_even_split_is_a_draw_and_breaks_the_streak(fake):
    confirm(log([A], [B]), by=B)
    confirm(log([A], [B], games=[(11, 7), (7, 11)]), by=B)
    assert fake.player(A)["draws"] == 1
    assert fake.player(A)["streak"] == 0


def test_a_match_is_rated_when_confirmed_not_when_logged(fake):
    """Two matches logged back to back, confirmed in the other order: the second
    confirmation must see the rating the first one produced."""
    first, second = log([A], [B]), log([A], [B])
    later = confirm(second, by=B)
    earlier = confirm(first, by=B)
    assert earlier["before"][A] == later["after"][A]
    assert fake.rating(A) == earlier["after"][A]


def test_a_doubles_match_moves_four_players(fake):
    blob = confirm(log([A, B], [C, D]), by=C)
    assert blob["doubles"] is True
    assert set(blob["deltas"]) == {A, B, C, D}
    assert all(fake.player(u)["matches"] == 1 for u in (A, B, C, D))


def test_history_records_the_match_for_everyone_in_it(fake):
    blob = confirm(log([A], [B]), by=B)
    assert [m["id"] for m in store.recent_matches()] == [blob["id"]]
    assert [m["id"] for m in store.recent_matches(uid=B)] == [blob["id"]]
    assert store.recent_matches(uid=C) == []


def test_history_is_newest_first(fake):
    ids = [confirm(log([A], [B]), by=B)["id"] for _ in range(3)]
    assert [m["id"] for m in store.recent_matches()] == list(reversed(ids))


def test_the_week_counters_follow_the_confirmations(fake):
    blob = confirm(log([A], [B]), by=B)
    delta, played = store.week_movement(blob["week"])
    assert delta[A] == blob["deltas"][A]
    assert played == {A: 1, B: 1}


# --- undo ------------------------------------------------------------------

def test_undo_puts_everything_back_exactly(fake):
    confirm(log([A], [B]), by=B)          # a first match to restore *to*
    before = {u: fake.player(u) for u in (A, B)}
    blob = confirm(log([A], [B]), by=B)
    store.undo_match(blob)
    assert {u: fake.player(u) for u in (A, B)} == before
    assert store.get_match(blob["id"]) is None
    assert store.recent_matches() and store.recent_matches()[0]["id"] != blob["id"]


def test_undo_rewinds_the_week_counters_too(fake):
    blob = confirm(log([A], [B]), by=B)
    store.undo_match(blob)
    delta, played = store.week_movement(blob["week"])
    assert delta == {A: 0, B: 0} and played == {A: 0, B: 0}


def test_undo_is_refused_once_someone_has_played_again(fake):
    blob = confirm(log([A], [B]), by=B)
    confirm(log([A], [C]), by=C)
    ok, reason = store.can_undo(blob)
    assert not ok and f"<@{A}>" in reason


def test_undo_is_allowed_while_the_match_is_still_everyone_s_last(fake):
    blob = confirm(log([A], [B]), by=B)
    assert store.can_undo(blob) == (True, "")


def test_you_can_only_undo_a_match_you_logged(fake):
    mine = confirm(log([A], [B], by=A), by=B)
    confirm(log([C], [D], by=C), by=D)
    assert store.last_match_by(A)["id"] == mine["id"]
    assert store.last_match_by(B) is None


# --- the admin reset -------------------------------------------------------

def test_scan_finds_only_the_matching_prefix(fake):
    """The ladder shares a database with another bot, so a prefix scan is the
    difference between a reset and an outage."""
    import kv
    confirm(log([A], [B]), by=B)
    fake.data["prlb:total"] = {"U1": "31"}          # pr-raiser's, must survive
    fake.data["prwatch:acme/web#12"] = {"U1": ""}

    ladder = kv.scan("tt:*")
    assert ladder and all(k.startswith("tt:") for k in ladder)
    assert "prlb:total" not in ladder
    assert set(kv.scan("*")) - set(ladder) == {"prlb:total", "prwatch:acme/web#12"}


def test_scan_follows_the_cursor_to_the_end(fake):
    import kv
    for i in range(250):
        fake.data[f"tt:player:U{i}"] = {"rating": "1000"}
    assert len(kv.scan("tt:*")) == 250


# --- matches by day --------------------------------------------------------

def test_a_day_window_returns_only_the_matches_inside_it(fake):
    from datetime import datetime
    d16 = datetime(2026, 9, 16, 18, 0, tzinfo=store.IST)
    d17 = datetime(2026, 9, 17, 9, 30, tzinfo=store.IST)
    old = confirm(log([A], [B], now=d16), by=B, now=d16)
    new = confirm(log([A], [C], now=d17), by=C, now=d17)
    start = datetime(2026, 9, 17, tzinfo=store.IST)
    found = store.matches_in(start, start + timedelta(days=1))
    assert [m["id"] for m in found] == [new["id"]]
    found = store.matches_in(start - timedelta(days=1), start)
    assert [m["id"] for m in found] == [old["id"]]


def test_a_window_can_be_narrowed_to_one_player(fake):
    from datetime import datetime
    when = datetime(2026, 9, 17, 9, 30, tzinfo=store.IST)
    confirm(log([A], [B], now=when), by=B, now=when)
    confirm(log([C], [D], now=when), by=D, now=when)
    start = when.replace(hour=0, minute=0)
    assert len(store.matches_in(start, start + timedelta(days=1))) == 2
    mine = store.matches_in(start, start + timedelta(days=1), uid=C)
    assert [set(m["side_a"] + m["side_b"]) for m in mine] == [{C, D}]


def test_the_walk_stops_at_the_first_match_older_than_the_window(fake, monkeypatch):
    """History is newest-first, so once one match predates the window every
    later one does too; the rest of history should never be fetched."""
    from datetime import datetime
    base = datetime(2026, 9, 17, 9, 0, tzinfo=store.IST)
    for days_back in (5, 4, 3, 2, 1, 0):
        when = base - timedelta(days=days_back)
        confirm(log([A], [B], now=when), by=B, now=when)
    monkeypatch.setattr(store, "MATCH_CHUNK", 2)
    calls = []
    real = store.kv.mget
    monkeypatch.setattr(store.kv, "mget", lambda keys: calls.append(list(keys)) or real(calls[-1]))
    start = base.replace(hour=0, minute=0)
    found = store.matches_in(start, start + timedelta(days=1))
    assert len(found) == 1
    assert len(calls) == 1   # first chunk of two already crossed the boundary


# --- the books balance, all the way to the database -------------------------

def test_a_confirmed_match_conserves_both_ladders(fake):
    """Not just the maths in elo.py: the ratings that actually get written.

    A newcomer against a settled player is the case that used to mint — the two
    carried different K and the difference came from nowhere.
    """
    store.ensure_players([A, B, C])
    for _ in range(12):                      # B becomes well played, A stays new
        confirm(log([B], [C]), by=C)
    before = {uid: store.get_player(uid)["rating"] for uid in (A, B)}
    blob = confirm(log([A], [B], games=[(11, 4)] * 3), by=B)
    assert sum(blob["deltas"].values()) == 0
    assert sum(blob["split_rated"]["deltas"].values()) == 0
    after = {uid: store.get_player(uid)["rating"] for uid in (A, B)}
    assert (after[A] - before[A]) + (after[B] - before[B]) == 0


def test_the_whole_pool_is_the_same_size_it_started(fake):
    """Play a season of mixed experience and the total is untouched. This is
    the property a rating means: yours only says anything against everyone
    else's."""
    players = [A, B, C, D]
    store.ensure_players(players)
    start = sum(store.get_player(uid)["rating"] for uid in players)
    pairs = [(A, B), (C, D), (A, C), (B, D), (A, D), (B, C), (A, B), (C, A)]
    for i, (one, two) in enumerate(pairs):
        games = [(11, 6)] * 3 if i % 3 else [(6, 11), (11, 8), (9, 11)]
        confirm(log([one], [two], games=games), by=two)
    assert sum(store.get_player(uid)["rating"] for uid in players) == start


def test_a_doubles_result_conserves_across_all_four(fake):
    blob = confirm(log([A, B], [C, D], games=[(11, 5), (11, 7)]), by=C)
    assert sum(blob["deltas"].values()) == 0
    assert sum(blob["split_rated"]["deltas"].values()) == 0
