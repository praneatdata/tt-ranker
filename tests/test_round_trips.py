"""How many times each flow goes to Redis — a budget, asserted.

Every trip to Upstash is an HTTPS request from a serverless function, and every
command in it is billed. Those costs used to be invisible until a page got slow,
so they are pinned here the way the help list is pinned to the parser: a change
that adds a trip to a hot path has to say so by changing a number below.

Counted on the transport, under the same FakeRedis every other test uses, so
what is measured is the real command construction.
"""
import itertools
import json
from collections import Counter
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

import awards
import betting
import bot
import kv
import rerate
import store
from tests.fake_kv import FakeRedis


class Counted(FakeRedis):
    """FakeRedis that remembers every HTTP request it was sent."""

    def __init__(self):
        super().__init__()
        self.trips = []   # [(path, [command names])]

    def post(self, path, payload, timeout=10):
        batch = payload if path in ("/pipeline", "/multi-exec") else [payload]
        self.trips.append((path or "/", [str(c[0]).upper() for c in batch]))
        return super().post(path, payload, timeout)

    def reset(self):
        self.trips = []

    @property
    def commands(self):
        return Counter(name for _, names in self.trips for name in names)


@pytest.fixture
def fake():
    redis = Counted()
    with redis.patched():
        yield redis


def seed(n_players=12, n_matches=40, fixtures=2):
    """A ladder with history, names, wallets, and live fixtures with stakes."""
    uids = [f"U0{i:04d}" for i in range(n_players)]
    now = store.now_ist()
    store.ensure_players(uids)
    store.remember_names({u: f"Name {u}" for u in uids})
    store.mark_names_fetched()
    betting.ensure_wallets(uids)
    for i in range(n_matches):
        when = now - timedelta(hours=(n_matches - i) * 2)
        a, b = uids[i % n_players], uids[(i * 7 + 1) % n_players]
        if a == b:
            b = uids[(i + 1) % n_players]
        record = store.create_pending([a], [b], [(11, 7), (9, 11), (11, 5)],
                                      logged_by=a, now=when)
        store.claim_pending(record["id"])
        store.apply_match(record, confirmed_by=b, now=when)
    for k in range(fixtures):
        fx = betting.schedule([uids[k]], [uids[k + 1]], now + timedelta(hours=1),
                              created_by=uids[k])
        for bettor in uids[-3:]:
            betting.place_bet(fx, bettor, "a", 10)
    awards.current(fresh=True)
    return uids


@pytest.fixture
def app():
    from api import index
    index.app.config["TESTING"] = True
    return index.app.test_client()


# --- pages -----------------------------------------------------------------

PAGE_BUDGETS = {
    "/ladder": 2,
    "/ladder?board=spins": 2,
    "/players": 2,
    "/player/U00000": 2,
    "/player/U00000?view=overall": 2,
    "/matches": 2,
    "/stats": 2,
    "/titles": 2,
    "/shame": 1,
    # Picks are validated against the ladder before their histories are read.
    "/compare?p=U00000&p=U00001&p=U00002": 4,
}


@pytest.mark.parametrize("path,budget", PAGE_BUDGETS.items())
def test_a_page_render_stays_inside_its_trip_budget(app, fake, path, budget):
    seed()
    fake.reset()
    assert app.get(path).status_code == 200
    assert len(fake.trips) == budget, fake.trips


@pytest.mark.parametrize("path", ["/ladder", "/players", "/matches", "/stats"])
def test_a_page_costs_the_same_trips_however_big_the_ladder(app, fake, path):
    """The whole point of batching: trips must not grow with players,
    matches or fixtures."""
    seed(n_players=4, n_matches=5, fixtures=1)
    fake.reset()
    app.get(path)
    small = len(fake.trips)
    fake.data.clear()
    seed(n_players=20, n_matches=60, fixtures=3)
    fake.reset()
    app.get(path)
    assert len(fake.trips) == small


def test_the_ladder_reads_its_matches_as_one_command(app, fake):
    """Upstash bills per command, pipelined or not: 120 GETs is 120 bills."""
    seed(n_matches=60)
    fake.reset()
    app.get("/ladder")
    assert fake.commands["GET"] <= 2           # names:fetched and the titles cache
    assert fake.commands["MGET"] == 2          # the matches, and the fixtures
    assert fake.commands["LRANGE"] == 1


def test_a_cold_title_cache_costs_one_write_not_a_second_read(app, fake):
    """Once the history the page read reaches back past the week (here 100
    matches, two hours apart), nothing is read twice."""
    seed(n_matches=100)
    fake.data.pop(store.TITLES_KEY)
    fake.reset()
    app.get("/ladder")
    assert len(fake.trips) == 3
    assert fake.trips[-1][1] == ["SET"]


def test_the_page_is_cacheable_at_the_edge(app, fake):
    """Vercel only caches a function's response on its CDN with s-maxage."""
    seed()
    header = app.get("/ladder").headers["Cache-Control"]
    assert "s-maxage=" in header and "public" in header


# --- slack flows -----------------------------------------------------------

def _client():
    c = MagicMock()
    n = itertools.count(1)
    c.chat_postMessage.side_effect = lambda **kw: {"channel": kw.get("channel", "C1"),
                                                   "ts": f"1.{next(n)}"}
    return c


def _press(fn, value, user):
    fn({"user": {"id": user}, "actions": [{"value": value}],
        "container": {"channel_id": "C1", "message_ts": "1"}}, _client(), MagicMock())


def test_confirming_a_match_stays_inside_its_budget(fake):
    uids = seed(fixtures=0)
    record = store.create_pending([uids[1]], [uids[2]], [(11, 7), (11, 9)],
                                  logged_by=uids[1], channel="C1")
    fake.reset()
    _press(bot.handle_confirm, record["id"], uids[2])
    # read, claim, read players, one atomic write, prize (2), fixture lookup
    assert len(fake.trips) <= 7, fake.trips
    assert sum(1 for path, _ in fake.trips if path == "/multi-exec") == 1


def test_the_rating_write_is_one_transaction(fake):
    """Ratings, history and the match land together or not at all."""
    uids = seed(fixtures=0)
    record = store.create_pending([uids[1]], [uids[2]], [(11, 7)], logged_by=uids[1])
    store.claim_pending(record["id"])
    fake.reset()
    store.apply_match(record)
    atomic = [names for path, names in fake.trips if path == "/multi-exec"]
    assert len(atomic) == 1
    assert {"HSET", "SET", "LPUSH", "DEL"} <= set(atomic[0])


def test_settling_a_fixture_does_not_grow_with_bettors(fake):
    uids = seed(fixtures=0)
    now = store.now_ist()

    def settle_with(bettors):
        fx = betting.schedule([uids[0]], [uids[1]], now + timedelta(hours=1),
                              created_by=uids[0])
        for bettor in bettors:
            betting.place_bet(fx, bettor, "a", 10)
        blob = {"id": "x", "side_a": [uids[0]], "side_b": [uids[1]],
                "games_a": 2, "games_b": 0}
        fake.reset()
        bot.settle_fixture_for(blob, _client())
        return len(fake.trips)

    assert settle_with(uids[4:6]) == settle_with(uids[4:11])


def test_the_weekly_stipend_is_four_trips_for_any_ladder(fake):
    seed(n_players=25, n_matches=0, fixtures=0)
    fake.reset()
    assert betting.pay_stipend(week="W-test")["status"] == "paid"
    assert len(fake.trips) == 4


def test_an_edit_reads_all_of_history_in_one_trip(fake):
    seed(n_matches=40, fixtures=0)
    fake.reset()
    rerate.load_history()
    assert [names for _, names in fake.trips] == [["LRANGE"], ["MGET"]]


# --- the pieces those budgets rest on ---------------------------------------

def test_mget_splits_big_reads_but_keeps_one_trip(fake, monkeypatch):
    monkeypatch.setattr(kv, "MGET_CHUNK", 2)
    for i in range(5):
        kv.set_(f"k{i}", str(i))
    fake.reset()
    assert kv.mget([f"k{i}" for i in range(5)] + ["nope"]) == ["0", "1", "2", "3", "4", None]
    assert fake.trips == [("/pipeline", ["MGET", "MGET", "MGET"])]


def test_a_discarded_transaction_is_an_error_not_an_empty_success(monkeypatch):
    monkeypatch.setattr(kv, "_post", lambda path, payload, timeout: {"error": "EXECABORT"})
    with pytest.raises(RuntimeError, match="EXECABORT"):
        kv.pipeline([["SET", "a", "1"]], atomic=True)


def test_the_undo_snapshot_lives_beside_the_match(fake):
    uids = seed(n_matches=0, fixtures=0)
    record = store.create_pending([uids[0]], [uids[1]], [(11, 7)], logged_by=uids[0])
    store.claim_pending(record["id"])
    store.apply_match(record)
    stored = json.loads(fake.data[store.match_key(record["id"])])
    assert "snapshot" not in stored
    assert set(json.loads(fake.data[store.snap_key(record["id"])])) == {uids[0], uids[1]}
    assert set(store.get_match(record["id"])["snapshot"]) == {uids[0], uids[1]}


def test_undo_works_from_a_listed_match_without_its_snapshot(fake):
    """recent_matches() doesn't carry snapshots; undo fetches it and then
    removes it with the match."""
    uids = seed(n_matches=0, fixtures=0)
    before = store.get_player(uids[0])
    record = store.create_pending([uids[0]], [uids[1]], [(11, 7)], logged_by=uids[0])
    store.claim_pending(record["id"])
    store.apply_match(record)
    listed = store.recent_matches(limit=1)[0]
    assert "snapshot" not in listed
    store.undo_match(listed)
    assert store.get_player(uids[0])["rating"] == before["rating"]
    assert store.snap_key(record["id"]) not in fake.data


def test_a_match_stored_before_the_split_still_undoes(fake):
    uids = seed(n_matches=0, fixtures=0)
    before = store.get_player(uids[0])
    record = store.create_pending([uids[0]], [uids[1]], [(11, 7)], logged_by=uids[0])
    store.claim_pending(record["id"])
    blob = store.apply_match(record)
    # Rewrite it the old way: snapshot inline, no tt:snap key.
    fake.data[store.match_key(blob["id"])] = json.dumps(blob)
    del fake.data[store.snap_key(blob["id"])]
    store.undo_match(store.recent_matches(limit=1)[0])
    assert store.get_player(uids[0])["rating"] == before["rating"]


def test_titles_fall_back_to_a_walk_when_history_is_too_short(fake):
    """Handing the page's history over is only safe when it reaches back past
    the start of the week; otherwise the week is read as before."""
    seed(n_matches=10, fixtures=0)
    start, end = awards.week_window()
    recent = store.recent_matches(limit=2)
    assert awards._week_from(recent, start, end) is None
    everything = store.recent_matches(limit=500)
    older = dict(everything[-1], id="0", applied_at=store.stamp(start - timedelta(days=1)))
    assert awards._week_from(everything + [older], start, end) == \
        store.matches_in(start, end)


def test_the_page_loader_sweeps_expired_fixtures_like_live_does(fake):
    import prefetch
    seed(n_matches=0, fixtures=1)
    kv.sadd(betting.LIVE_KEY, "999")          # indexed, but its record is gone
    data = prefetch.load(fixtures=True)
    assert [r["id"] for r in data.fixtures] == [r["id"] for r in betting.live()]
    assert "999" not in kv.smembers(betting.LIVE_KEY)


def test_a_name_refresh_is_rendered_straight_away(app, fake):
    """The names are read before the refresh now, so a refresh that found
    anyone is re-read rather than showing up a render late."""
    seed(n_matches=0, fixtures=0)

    def refresh(*args, **kwargs):
        store.remember_names({"U00000": "Fresh Name"})
        return 1

    with patch("bot.refresh_names", side_effect=refresh):
        assert "Fresh Name" in app.get("/players").data.decode()
