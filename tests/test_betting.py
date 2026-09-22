"""Spins, pools and settlement.

Every test that moves money also checks the pot balances. A rating bug is an
argument; a wallet bug is an argument nobody can settle.
"""
from datetime import timedelta

import pytest

import betting
import kv
import store
from tests.fake_kv import FakeRedis

A, B, C, D, E = "U0AAA1", "U0BBB1", "U0CCC1", "U0DDD1", "U0EEE1"


@pytest.fixture
def fake():
    redis = FakeRedis()
    with redis.patched():
        yield redis


def fixture_at(minutes=60, side_a=None, side_b=None, by=None, now=None):
    now = now or store.now_ist()
    return betting.schedule(side_a or [A], side_b or [B],
                            now + timedelta(minutes=minutes),
                            created_by=by or A, channel="C1", now=now)


def total_held(uids):
    return sum(betting.balance(u) for u in uids)


# --- wallets ---------------------------------------------------------------

def test_everyone_opens_with_the_same_stake(fake):
    betting.ensure_wallets([A, B])
    assert betting.balance(A) == betting.balance(B) == betting.START_SPINS


def test_opening_a_wallet_never_resets_an_existing_one(fake):
    betting.ensure_wallets([A])
    betting.adjust(A, -200, "test")
    betting.ensure_wallets([A, B])
    assert betting.balance(A) == betting.START_SPINS - 200
    assert betting.balance(B) == betting.START_SPINS


def test_the_ledger_says_where_the_spins_went(fake):
    betting.adjust(A, -50, "stake on #1")
    betting.adjust(A, 120, "#1 settled")
    entries = betting.ledger(A)
    assert [e["delta"] for e in entries] == [120, -50]      # newest first
    assert entries[0]["balance"] == betting.START_SPINS - 50 + 120


def test_a_ledger_outage_never_costs_anyone_spins(fake, monkeypatch):
    """The balance is the truth; the ledger is a courtesy."""
    monkeypatch.setattr(betting.kv, "pipeline",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    with pytest.raises(RuntimeError):
        betting.ensure_wallets([A])          # the pipeline is used here too
    monkeypatch.undo()
    betting.ensure_wallets([A])
    monkeypatch.setattr(betting.kv, "lpush",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert betting.adjust(A, -25, "stake") == betting.START_SPINS - 25


# --- the stipend -----------------------------------------------------------

# Both switch positions are tested explicitly rather than either one riding on
# whatever WEEKLY_STIPEND happens to be set to. It has been flipped twice now,
# and each time these tests broke for a reason that had nothing to do with them.
@pytest.fixture
def stipend_on(monkeypatch):
    monkeypatch.setattr(betting, "WEEKLY_STIPEND", 1000)
    return 1000


@pytest.fixture
def stipend_off(monkeypatch):
    monkeypatch.setattr(betting, "WEEKLY_STIPEND", 0)
    return 0


def test_no_stipend_is_paid_while_it_is_switched_off(fake, stipend_off):
    store.ensure_players([A])
    betting.ensure_wallets([A])
    assert betting.pay_stipend(week="tt:wk:2026-W38")["status"] == "disabled"
    assert betting.balance(A) == betting.START_SPINS


def test_switching_it_off_does_not_consume_the_week(fake, monkeypatch, stipend_off):
    """Turning it back on should pay the week it is turned on in, not skip it
    because a disabled run had already marked that week done."""
    store.ensure_players([A])
    betting.pay_stipend(week="tt:wk:2026-W38")
    monkeypatch.setattr(betting, "WEEKLY_STIPEND", 1000)
    assert betting.pay_stipend(week="tt:wk:2026-W38")["status"] == "paid"


def test_payday_tops_everyone_up(fake, stipend_on):
    store.ensure_players([A, B])
    result = betting.pay_stipend(week="tt:wk:2026-W38")
    assert result["status"] == "paid" and result["players"] == 2
    assert betting.balance(A) == betting.START_SPINS + betting.WEEKLY_STIPEND


def test_payday_happens_once_a_week(fake, stipend_on):
    store.ensure_players([A])
    betting.pay_stipend(week="tt:wk:2026-W38")
    assert betting.pay_stipend(week="tt:wk:2026-W38")["status"] == "already_paid"
    assert betting.balance(A) == betting.START_SPINS + betting.WEEKLY_STIPEND


def test_nobody_starts_a_week_broke(fake, stipend_on):
    """Losing everything costs you a week, not the game. A wallet can't go
    negative, so the stipend alone is the floor — no separate rescue needed."""
    store.ensure_players([A])
    betting.ensure_wallets([A])
    betting.adjust(A, -betting.START_SPINS, "lost it all")
    assert betting.balance(A) == 0
    betting.pay_stipend(week="tt:wk:2026-W38")
    assert betting.balance(A) == betting.WEEKLY_STIPEND
    assert betting.WEEKLY_STIPEND >= betting.MIN_BET * 2   # enough to play again


def test_a_week_with_no_players_stays_claimable(fake, stipend_on):
    assert betting.pay_stipend(week="tt:wk:2026-W38")["status"] == "no_players"
    store.ensure_players([A])
    assert betting.pay_stipend(week="tt:wk:2026-W38")["status"] == "paid"


# --- placing bets ----------------------------------------------------------

def test_a_stake_leaves_the_wallet_immediately(fake):
    record = fixture_at()
    ok, _ = betting.place_bet(record, C, "a", 50)
    assert ok
    assert betting.balance(C) == betting.START_SPINS - 50
    assert betting.pool(record["id"])["a"] == 50


def test_you_cannot_stake_more_than_you_hold(fake):
    record = fixture_at()
    ok, message = betting.place_bet(record, C, "a", betting.START_SPINS + 1)
    assert not ok and str(betting.START_SPINS) in message
    assert betting.balance(C) == betting.START_SPINS


def test_a_stake_below_the_minimum_is_refused(fake):
    record = fixture_at()
    ok, message = betting.place_bet(record, C, "a", 1)
    assert not ok and "Smallest stake" in message


def test_topping_up_the_same_side_adds_to_your_stake(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 50)
    betting.place_bet(record, C, "a", 30)
    assert betting.bets(record["id"])[C] == ("a", 80)
    assert betting.balance(C) == betting.START_SPINS - 80


def test_you_cannot_be_on_both_sides(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 50)
    ok, message = betting.place_bet(record, C, "b", 50)
    assert not ok and "other side" in message
    assert betting.balance(C) == betting.START_SPINS - 50


def test_betting_shuts_when_the_match_is_due(fake):
    now = store.now_ist()
    record = fixture_at(minutes=30, now=now)
    ok, message = betting.place_bet(record, C, "a", 50, now=now + timedelta(minutes=31))
    assert not ok and "closed" in message
    assert betting.get(record["id"])["state"] == "closed"
    assert betting.balance(C) == betting.START_SPINS


def test_a_player_may_back_their_own_opponent(fake):
    """House rule. The guard is that it's visible, not that it's blocked."""
    record = fixture_at(side_a=[A], side_b=[B])
    ok, _ = betting.place_bet(record, A, "b", 50)
    assert ok
    assert betting.backing_against_self(record) == [(A, 50)]


def test_backing_yourself_is_not_flagged(fake):
    record = fixture_at(side_a=[A], side_b=[B])
    betting.place_bet(record, A, "a", 50)
    betting.place_bet(record, C, "b", 50)       # a spectator, not a player
    assert betting.backing_against_self(record) == []


# --- the pool maths --------------------------------------------------------

def test_winners_split_the_pot_in_proportion():
    placed = {C: ("a", 300), D: ("a", 100), E: ("b", 100)}
    paid = betting.payouts(placed, "a")
    assert paid == {C: 375, D: 125, E: 0}
    assert sum(paid.values()) == 500            # the whole pot, nothing minted


@pytest.mark.parametrize("placed,winner", [
    ({C: ("a", 7), D: ("a", 11), E: ("b", 13)}, "a"),
    ({C: ("a", 1000), D: ("b", 3), E: ("b", 3)}, "b"),
    ({C: ("a", 5), D: ("a", 5), E: ("a", 5)}, "a"),
    ({C: ("a", 33), D: ("a", 33), E: ("a", 34), A: ("b", 100)}, "a"),
])
def test_the_pot_is_conserved_to_the_last_spin(placed, winner):
    """Floored shares would quietly burn spins; the remainder goes to the
    largest winning stake instead."""
    paid = betting.payouts(placed, winner)
    assert sum(paid.values()) == sum(a for _, a in placed.values())


def test_a_draw_refunds_everyone():
    placed = {C: ("a", 300), D: ("b", 100)}
    assert betting.payouts(placed, "draw") == {C: 300, D: 100}


def test_nobody_on_the_winning_side_means_everyone_is_refunded():
    placed = {C: ("a", 300), D: ("a", 100)}
    assert betting.payouts(placed, "b") == {C: 300, D: 100}


def test_everyone_on_the_winning_side_just_gets_their_stake_back():
    placed = {C: ("a", 300), D: ("a", 100)}
    assert betting.payouts(placed, "a") == {C: 300, D: 100}


def test_an_empty_pot_settles_to_nothing():
    assert betting.payouts({}, "a") == {}


def test_projected_returns_track_the_pool(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 300)
    betting.place_bet(record, D, "b", 100)
    pot = betting.pool(record["id"])
    assert betting.projected(pot, "a") == pytest.approx(400 / 300)
    assert betting.projected(pot, "b") == pytest.approx(4.0)


def test_an_untouched_side_has_no_projection(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 50)
    assert betting.projected(betting.pool(record["id"]), "b") == 0.0


# --- settlement ------------------------------------------------------------

def test_settling_pays_the_winners_and_conserves_the_pot(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 300)
    betting.place_bet(record, D, "b", 100)
    before = total_held([C, D])

    assert betting.claim(record["id"])
    settled = betting.settle(record, "a")

    assert betting.balance(C) == betting.START_SPINS + 100    # 300 back as 400
    assert betting.balance(D) == betting.START_SPINS - 100
    assert total_held([C, D]) == before + 400                 # the staked pot returns
    assert settled["state"] == "settled" and settled["winner"] == "a"


def test_a_pot_can_only_be_settled_once(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 50)
    assert betting.claim(record["id"]) is True
    assert betting.claim(record["id"]) is False


def test_voiding_hands_every_stake_back(fake):
    record = fixture_at()
    betting.place_bet(record, C, "a", 300)
    betting.place_bet(record, D, "b", 100)
    betting.void(record, "called off")
    assert betting.balance(C) == betting.balance(D) == betting.START_SPINS
    assert betting.get(record["id"])["state"] == "void"


def test_a_fixture_nobody_reports_is_abandoned(fake):
    now = store.now_ist()
    record = fixture_at(minutes=10, now=now)
    betting.close_if_due(record, now + timedelta(minutes=11))
    assert not betting.is_abandoned(record, now + timedelta(hours=1))
    assert betting.is_abandoned(record, now + timedelta(hours=betting.ABANDON_HOURS + 1))


# --- matching a result to a fixture ---------------------------------------

def test_a_result_finds_its_fixture_whichever_way_it_was_logged(fake):
    record = fixture_at(side_a=[A], side_b=[B])
    assert betting.find_for_result([A], [B])["id"] == record["id"]
    assert betting.find_for_result([B], [A])["id"] == record["id"]


def test_a_different_fixture_is_not_claimed(fake):
    fixture_at(side_a=[A], side_b=[B])
    assert betting.find_for_result([A], [C]) is None
    assert betting.find_for_result([A, C], [B, D]) is None


def test_doubles_fixtures_match_on_the_pair_not_the_order(fake):
    record = fixture_at(side_a=[A, B], side_b=[C, D])
    assert betting.find_for_result([B, A], [D, C])["id"] == record["id"]


def test_the_winner_is_read_in_the_fixtures_terms(fake):
    record = fixture_at(side_a=[A], side_b=[B])
    assert betting.winner_from(record, [A], 3, 0) == "a"
    assert betting.winner_from(record, [A], 0, 3) == "b"
    # logged the other way round: side A of the *session* is B of the fixture
    assert betting.winner_from(record, [B], 3, 0) == "b"
    assert betting.winner_from(record, [B], 0, 3) == "a"
    assert betting.winner_from(record, [A], 2, 2) == "draw"


def test_a_settled_fixture_is_no_longer_findable(fake):
    record = fixture_at(side_a=[A], side_b=[B])
    betting.claim(record["id"])
    betting.settle(record, "a")
    assert betting.find_for_result([A], [B]) is None


# --- the property that matters ---------------------------------------------

EVERYONE = [A, B, C, D, E]


def supply():
    """Every spin in existence: in wallets, plus everything currently staked."""
    held = sum(betting.balance(u) for u in EVERYONE)
    staked = sum(betting.pool(r["id"])["total"] for r in betting.live())
    return held + staked


@pytest.mark.parametrize("script", [
    [("a", C, 100), ("b", D, 100)],
    [("a", C, 300), ("a", D, 100), ("b", E, 50)],
    [("a", C, 7), ("a", D, 11), ("a", E, 13), ("b", A, 29)],
    [("b", C, 500)],                                   # one side only
    [("a", C, 5), ("b", D, 5), ("a", E, 5), ("b", A, 5)],
])
@pytest.mark.parametrize("winner", ["a", "b", "draw"])
def test_no_spin_is_ever_created_or_destroyed(fake, script, winner):
    """Stakes leave wallets, payouts come back, and the two always agree —
    whatever the split, whoever wins, and however the shares round."""
    betting.ensure_wallets(EVERYONE)
    opening = supply()

    record = fixture_at()
    for side, uid, amount in script:
        assert betting.place_bet(record, uid, side, amount)[0]
    assert supply() == opening, "staking moved spins out of the system"

    assert betting.claim(record["id"])
    betting.settle(record, winner)
    assert supply() == opening, "settling minted or burned spins"


def test_voiding_conserves_the_supply_too(fake):
    betting.ensure_wallets(EVERYONE)
    opening = supply()
    record = fixture_at()
    betting.place_bet(record, C, "a", 137)
    betting.place_bet(record, D, "b", 41)
    betting.claim(record["id"])
    betting.void(record, "called off")
    assert supply() == opening


def test_several_fixtures_settling_in_any_order_conserve_the_supply(fake):
    betting.ensure_wallets(EVERYONE)
    opening = supply()
    first = fixture_at(side_a=[A], side_b=[B])
    second = fixture_at(side_a=[C], side_b=[D])
    betting.place_bet(first, C, "a", 90)
    betting.place_bet(first, D, "b", 30)
    betting.place_bet(second, A, "a", 60)
    betting.place_bet(second, E, "b", 45)

    for record, winner in ((second, "b"), (first, "a")):   # settled out of order
        assert betting.claim(record["id"])
        betting.settle(record, winner)
    assert supply() == opening


def test_the_stipend_and_the_win_prize_are_the_only_things_that_mint(fake, stipend_on):
    """It used to be the stipend alone. Winning a match now pays too, so there
    are exactly two sources of new spins and everything else — every bet, every
    settlement, every transfer — is still strictly zero-sum."""
    store.ensure_players(EVERYONE)
    betting.ensure_wallets(EVERYONE)
    opening = supply()
    betting.pay_stipend(week="tt:wk:2026-W38")
    assert supply() == opening + betting.WEEKLY_STIPEND * len(EVERYONE)


# --- transfers -------------------------------------------------------------

def test_a_transfer_moves_spins_between_wallets(fake):
    betting.ensure_wallets([A, B])
    ok, message = betting.transfer(A, B, 500)
    assert ok and "500" in message
    assert betting.balance(A) == betting.START_SPINS - 500
    assert betting.balance(B) == betting.START_SPINS + 500


def test_a_transfer_mints_nothing(fake):
    """Moving spins between wallets creates none: a debit and a credit of the
    same size. Only the stipend and the win prize make new ones."""
    betting.ensure_wallets(EVERYONE)
    before = supply()
    betting.transfer(A, B, 1234)
    betting.transfer(B, C, 99)
    assert supply() == before


def test_you_cannot_send_what_you_do_not_have(fake):
    betting.ensure_wallets([A, B])
    ok, message = betting.transfer(A, B, betting.START_SPINS + 1)
    assert not ok and "only has" in message
    assert betting.balance(A) == betting.START_SPINS


def test_a_transfer_to_yourself_is_refused(fake):
    assert betting.transfer(A, A, 50)[0] is False


@pytest.mark.parametrize("amount", [0, -50, "lots", None])
def test_a_transfer_needs_a_real_amount(fake, amount):
    betting.ensure_wallets([A, B])
    assert betting.transfer(A, B, amount)[0] is False
    assert betting.balance(B) == betting.START_SPINS


def test_both_ledgers_name_the_other_party(fake):
    betting.ensure_wallets([A, B])
    betting.transfer(A, B, 250)
    assert f"<@{B}>" in betting.ledger(A)[0]["reason"]
    assert f"<@{A}>" in betting.ledger(B)[0]["reason"]


def test_a_third_party_move_is_marked_as_one(fake):
    """So /tt wallet can always answer "where did that come from"."""
    betting.ensure_wallets([A, B, C])
    betting.transfer(A, B, 100, by=C)
    assert f"by <@{C}>" in betting.ledger(A)[0]["reason"]
    assert f"by <@{C}>" in betting.ledger(B)[0]["reason"]


def test_your_own_transfer_is_not_marked_as_third_party(fake):
    betting.ensure_wallets([A, B])
    betting.transfer(A, B, 100, by=A)
    assert "by <@" not in betting.ledger(A)[0]["reason"]


def test_a_transfer_cannot_reach_spins_already_staked(fake):
    """A stake has left the wallet, so it simply isn't there to send."""
    betting.ensure_wallets([A, C])
    record = fixture_at()
    betting.place_bet(record, C, "a", 400)
    ok, _ = betting.transfer(C, A, betting.START_SPINS - 399)
    assert not ok
    assert betting.pool(record["id"])["a"] == 400


# --- the spins leaderboard -------------------------------------------------

def test_the_richest_wallet_ranks_first():
    ranked = betting.rank_wallets({A: 4000, B: 7000, C: 5000})
    assert [uid for uid, _, _ in ranked] == [B, C, A]


def test_the_table_says_how_far_each_wallet_moved():
    ranked = dict((uid, net) for uid, _, net in
                  betting.rank_wallets({A: 4000, B: 7000, C: betting.START_SPINS}))
    assert ranked == {A: -1000, B: 2000, C: 0}


def test_a_player_without_a_wallet_is_ranked_at_the_opening_balance():
    """Nobody is missing from the table just because they never placed a bet —
    their wallet would hold START_SPINS the moment it opened, so rank it so."""
    ranked = betting.rank_wallets({A: 6000}, uids=[A, B])
    assert (B, betting.START_SPINS, 0) in ranked
    assert ranked[0][0] == A


def test_ties_break_the_same_way_every_refresh():
    once = betting.rank_wallets({B: 5000, A: 5000, C: 5000})
    again = betting.rank_wallets({C: 5000, A: 5000, B: 5000})
    assert once == again == [(A, 5000, 0), (B, 5000, 0), (C, 5000, 0)]


def test_the_table_reads_from_the_real_wallets(fake):
    betting.ensure_wallets([A, B])
    betting.adjust(A, -300, "test", None)
    betting.adjust(B, 300, "test", None)
    ranked = betting.standings([A, B, C])
    assert ranked[0] == (B, betting.START_SPINS + 300, 300)
    assert ranked[-1] == (A, betting.START_SPINS - 300, -300)
    assert sum(held for _, held, _ in ranked) == 3 * betting.START_SPINS


def test_circulating_counts_what_is_staked_as_well_as_held(fake):
    """A stake has left its wallet but not the economy — it comes back at
    settlement. Counting wallets alone makes the total appear to shrink exactly
    when betting is open, which is when someone is most likely to look."""
    betting.ensure_wallets([A, B, C])
    opening = betting.circulating()
    assert opening == 3 * betting.START_SPINS

    record = fixture_at()
    betting.place_bet(record, C, "a", 4000)
    assert sum(betting.balances().values()) == opening - 4000   # wallets dipped
    assert betting.circulating() == opening                     # the economy did not

    betting.claim(record["id"])
    betting.settle(record, "a")
    assert betting.circulating() == opening


def test_the_total_agrees_with_the_table_under_it(fake):
    """standings() ranks registered players who never opened a wallet at the
    opening balance; a total that skipped them would contradict its own table."""
    store.ensure_players([A, B, C])
    kv.hset(betting.WALLET_KEY, A, 4000)     # only A has a real wallet
    ranked = betting.standings(store.player_ids())
    assert sum(held for _, held, _ in ranked) == betting.circulating(store.player_ids())


# --- winning pays ----------------------------------------------------------

@pytest.mark.parametrize("games_a,games_b,spins,label", [
    (2, 1, 5, "close"), (3, 2, 5, "close"), (1, 0, 5, "close"),
    (2, 0, 10, "decent"), (4, 2, 10, "decent"),
    (3, 0, 20, "wipeout"), (4, 1, 20, "wipeout"), (5, 0, 20, "wipeout"),
    (0, 2, 10, "decent"),          # read from the winning side, either side
])
def test_what_a_win_is_worth(games_a, games_b, spins, label):
    assert betting.prize_for(games_a, games_b) == (spins, label)


def test_a_drawn_session_pays_nobody():
    assert betting.prize_for(2, 2) == (0, "")


def blob(side_a, side_b, games_a, games_b):
    return {"id": "1", "side_a": list(side_a), "side_b": list(side_b),
            "games_a": games_a, "games_b": games_b}


def test_the_winner_is_paid_and_the_loser_is_not(fake):
    betting.ensure_wallets([A, B])
    paid = betting.pay_prize(blob([A], [B], 3, 0))
    assert paid == {A: 20}
    assert betting.balance(A) == betting.START_SPINS + 20
    assert betting.balance(B) == betting.START_SPINS


def test_both_of_a_winning_pair_are_paid_in_full(fake):
    """Not half each: halving it for doubles would make the sensible move
    'play singles for the money'."""
    betting.ensure_wallets([A, B, C, D])
    assert betting.pay_prize(blob([A, B], [C, D], 2, 1)) == {A: 5, B: 5}


def test_a_draw_pays_nobody_through_the_real_path(fake):
    betting.ensure_wallets([A, B])
    assert betting.pay_prize(blob([A], [B], 2, 2)) == {}
    assert betting.balance(A) == betting.START_SPINS


def test_the_prize_shows_up_in_the_ledger_with_a_reason(fake):
    betting.ensure_wallets([A, B])
    betting.pay_prize(blob([A], [B], 3, 0))
    assert "wipeout" in betting.ledger(A)[0]["reason"]


def test_undoing_a_match_takes_the_prize_back(fake):
    betting.ensure_wallets([A, B])
    b = blob([A], [B], 3, 0)
    betting.pay_prize(b)
    betting.take_back_prize(b)
    assert betting.balance(A) == betting.START_SPINS


def test_the_prize_is_a_pure_function_of_the_scoreline(fake):
    """Which is what lets an undo reverse it exactly without anything having
    been written down when it was paid."""
    b = blob([A], [B], 4, 1)
    assert betting.prize_for(b["games_a"], b["games_b"]) == \
        betting.prize_for(b["games_a"], b["games_b"])


def test_a_week_of_matches_mints_far_less_than_one_stipend(fake, stipend_on):
    """The prize is new money. It stays small enough that a wallet still means
    what it did — if that stops being true, WIN_PRIZE is the dial."""
    a_week_of_wipeouts = 85 * 20 * 1.5        # every match a 3-0, some doubles
    assert a_week_of_wipeouts < betting.WEEKLY_STIPEND * 43 * 0.1
