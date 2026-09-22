"""The rating maths. This is the part players will argue about, so the
properties they'd argue from are asserted directly."""
import pytest

import elo


def P(uid, rating=1000, games=200):
    """A player. `games` drives K — 200 is comfortably out of the provisional
    period, so most tests here compare established players."""
    return {"uid": uid, "rating": rating, "games": games}


def rate(a, b, games):
    return elo.rate_match([a] if isinstance(a, dict) else a,
                          [b] if isinstance(b, dict) else b, games)


def gain(a, b, games, who=None):
    r = rate(a, b, games)
    return r["deltas"][who or (a if isinstance(a, dict) else a[0])["uid"]]


SWEEP = [(11, 2), (11, 4), (11, 3)]          # 3-0, decisive
NORMAL = [(11, 7), (11, 9), (11, 8)]         # 3-0, ordinary
TIGHT = [(12, 10), (11, 9), (13, 11)]        # 3-0, every game a deuce
CLOSE_WIN = [(11, 7), (9, 11), (11, 5)]      # 2-1


# --- expectation -----------------------------------------------------------

def test_equal_ratings_are_a_coin_flip():
    assert elo.expected(1000, 1000) == pytest.approx(0.5)


def test_four_hundred_points_is_the_classic_ten_to_one():
    assert elo.expected(1400, 1000) == pytest.approx(10 / 11, abs=1e-6)


def test_expectations_sum_to_one():
    assert elo.expected(1180, 1247) + elo.expected(1247, 1180) == pytest.approx(1.0)


# --- margin of victory -----------------------------------------------------

def test_mov_is_one_at_a_normal_game_margin():
    assert elo.mov_multiplier(elo.MOV_BASELINE) == pytest.approx(1.0)


def test_mov_rises_with_the_margin_and_stays_clamped():
    assert elo.mov_multiplier(2) < elo.mov_multiplier(4) < elo.mov_multiplier(9)
    assert elo.mov_multiplier(1) == elo.MOV_MIN
    assert elo.mov_multiplier(99) == elo.MOV_MAX


def test_mov_ignores_which_side_won():
    """It scales the size of the swing; `expected` decides the direction."""
    assert elo.mov_multiplier(-7) == elo.mov_multiplier(7)


def test_a_whitewash_moves_about_twice_a_deuce_fest():
    """The margin knob, stated as the ratio players will actually notice.

    It was about 3x, at MOV_GAIN 1.5. That curve was steep enough to let one
    heavy loss outweigh two wins — see the note on MOV_GAIN — so it is 1.0 now
    and the ratio is about 2x. The scoreline still plainly matters; what it no
    longer does is decide a session on its own.
    """
    sweep, tight = gain(P("a"), P("b"), SWEEP), gain(P("a"), P("b"), TIGHT)
    assert 1.8 < sweep / tight < 2.5


# --- the upset correction --------------------------------------------------

def test_the_upset_correction_is_neutral_between_equals():
    assert elo.upset_correction(0) == pytest.approx(1.0)


def test_a_favourites_big_win_counts_for_less_than_an_underdogs():
    assert elo.upset_correction(400) < 1.0 < elo.upset_correction(-400)


def test_the_correction_can_never_flip_the_sign_of_an_update():
    """Its denominator reaches zero at a gap of -2200; unclamped, anything past
    that would hand the points to the loser."""
    assert elo.upset_correction(-100000) > 0
    assert elo.upset_correction(100000) > 0


# --- every game is rated on its own ----------------------------------------

def test_more_games_move_a_rating_further():
    """The point of per-game scoring: a long session is more evidence, so it
    counts for more. Sessions are whatever length people had time for."""
    three = gain(P("a"), P("b"), [(11, 7)] * 3)
    ten = gain(P("a"), P("b"), [(11, 7)] * 10)
    assert ten > three > 0
    assert 3.0 < ten / three < 3.7          # roughly linear in games played


def test_a_session_that_splits_evenly_moves_nobody():
    r = rate(P("a"), P("b"), [(11, 7)] * 5 + [(7, 11)] * 5)
    assert r["deltas"] == {"a": 0, "b": 0}


def test_losses_inside_a_session_cancel_wins():
    ten_nil = gain(P("a"), P("b"), [(11, 7)] * 10)
    seven_three = gain(P("a"), P("b"), [(11, 7)] * 7 + [(7, 11)] * 3)
    assert ten_nil > seven_three > 0


def test_a_swingy_session_is_read_as_the_close_thing_it_was():
    """11-1 / 1-11 / 11-1 is a close session, not three blowouts — the lost game
    cancels most of what the won ones earned."""
    swingy = gain(P("a"), P("b"), [(11, 1), (1, 11), (11, 1)])
    consistent = gain(P("a"), P("b"), SWEEP)
    assert 0 < swingy < consistent


def test_a_single_game_is_a_valid_session():
    r = rate(P("a"), P("b"), [(11, 6)])
    assert (r["games_a"], r["games_b"]) == (1, 0)
    assert r["deltas"]["a"] > 0


# --- singles ---------------------------------------------------------------

def test_winner_gains_exactly_what_the_loser_drops():
    r = rate(P("a"), P("b"), CLOSE_WIN)
    assert r["deltas"]["a"] == -r["deltas"]["b"] > 0


@pytest.mark.parametrize("games", [SWEEP, NORMAL, TIGHT, CLOSE_WIN, [(11, 7)] * 12])
@pytest.mark.parametrize("ra,rb", [(1000, 1400), (1000, 1000), (1300, 900), (700, 1500)])
def test_the_pool_is_conserved_whatever_the_result(games, ra, rb):
    assert sum(rate(P("a", ra), P("b", rb), games)["deltas"].values()) == 0


def test_a_whitewash_beats_a_squeaker():
    assert gain(P("a"), P("b"), SWEEP) > gain(P("a"), P("b"), TIGHT) > 0


def test_winning_three_nil_beats_winning_two_one_at_the_same_margins():
    """Like for like. A 3-0 of three deuces is a genuinely closer session than a
    2-1 of comfortable wins, and the model is allowed to say so."""
    assert gain(P("a"), P("b"), NORMAL) > gain(P("a"), P("b"), CLOSE_WIN) > 0


def test_beating_someone_stronger_is_worth_more():
    assert gain(P("a", 900), P("b", 1300), SWEEP) > gain(P("a", 1300), P("b", 900), SWEEP) > 0


def test_losing_to_someone_stronger_costs_less():
    to_better = gain(P("a", 900), P("b", 1300), [(2, 11), (4, 11)])
    to_worse = gain(P("a", 1300), P("b", 900), [(2, 11), (4, 11)])
    assert to_worse < to_better < 0


def test_scraping_past_someone_far_below_you_pays_nothing():
    """It used to *cost* rating — you were expected to take about 9 games in 10,
    and 2-1 is well short of that, so the arithmetic said you had gone backwards.

    That is defensible and it is no longer what happens: winning a session never
    costs rating now, so a scrape past someone far below you is worth exactly
    nothing instead. The disincentive is softer — padding your record against
    weak opposition is neutral rather than punished — and the trade is that
    nobody is ever shown a loss next to a win they earned."""
    assert gain(P("a", 1400), P("b", 1000), CLOSE_WIN) == 0


def test_a_newcomer_moves_far_further_than_a_veteran():
    new = gain(P("a", games=0), P("b", games=0), NORMAL)
    old = gain(P("a", games=500), P("b", games=500), NORMAL)
    assert new > 3 * old > 0
    assert elo.k_factor(0) == elo.K_NEW
    assert elo.k_factor(10_000) == pytest.approx(elo.K_SETTLED)


def test_k_falls_smoothly_and_never_steps():
    """The old rule dropped from 16 to 11 the moment a player's 50th game
    landed, so game 49 moved them 45% further than game 51 for no reason they
    could see. Nothing here may jump."""
    ks = [elo.k_factor(n) for n in range(0, 120)]
    assert ks == sorted(ks, reverse=True)
    steps = [a - b for a, b in zip(ks, ks[1:])]
    # No single game may account for more than a tenth of the whole journey.
    assert max(steps) < (elo.K_NEW - elo.K_SETTLED) / 10
    assert all(step > 0 for step in steps)       # and it is always falling


def test_the_first_games_are_the_ones_that_move():
    """What the whole change is for: a newcomer's opening 1000 is a guess, and
    their first games have to be able to replace it."""
    assert elo.k_factor(0) / elo.k_factor(100) > 3.5
    # Half the journey from new to settled is done inside the first ten games.
    halfway = (elo.K_NEW + elo.K_SETTLED) / 2
    assert elo.k_factor(5) > halfway > elo.k_factor(10)


def test_the_calibration_period_is_counted_in_games():
    assert elo.games_played({"games_won": 12, "games_lost": 9}) == 21
    assert elo.games_played({}) == 0


def test_a_session_is_rated_at_the_k_of_its_middle_game():
    """One K for the session, being the mean of the K each of its games would
    have carried — so a newcomer's long first evening converges instead of
    overshooting on the K of game one."""
    k = elo.session_k(0, 10)
    assert elo.k_factor(9) < k < elo.k_factor(0)
    assert k == pytest.approx(sum(elo.k_factor(n) for n in range(10)) / 10)
    # A single game is just that game's K.
    assert elo.session_k(4, 1) == elo.k_factor(4)


def test_a_long_first_session_does_not_overshoot():
    """Ten games at game-one's K would move a newcomer about a third further
    than the curve says they have earned."""
    ten = [(11, 6)] * 10
    damped = gain(P("a", games=0), P("b", games=200), ten)
    if_k_never_fell = damped * elo.k_factor(0) / elo.session_k(0, 10)
    assert damped < if_k_never_fell * 0.8


def test_the_order_games_were_typed_in_changes_nothing():
    """K is per session and E is fixed for it, so a 2-1 is a 2-1 however it is
    written down."""
    one = gain(P("a", games=3), P("b", games=3), [(11, 7), (9, 11), (11, 5)])
    two = gain(P("a", games=3), P("b", games=3), [(9, 11), (11, 5), (11, 7)])
    assert one == two


def test_an_even_session_still_moves_nobody_however_new_they_are():
    """The property a per-game K would have quietly broken: the wins would have
    been worth more than the losses purely for being typed first."""
    for games in (0, 3, 40, 300):
        r = rate(P("a", games=games), P("b", games=0),
                 [(11, 7), (7, 11), (11, 9), (9, 11)])
        assert r["deltas"]["a"] == 0 and r["deltas"]["b"] == 0


def test_rating_never_falls_through_the_floor():
    r = rate(P("a", elo.RATING_FLOOR), P("b", 2000), [(0, 11), (0, 11)])
    assert r["after"]["a"] == elo.RATING_FLOOR
    # the reported drop is the drop that happened, not the one we wanted
    assert r["deltas"]["a"] == 0


# --- doubles ---------------------------------------------------------------

def test_doubles_rates_the_pair_at_their_average():
    assert elo.team_rating([P("a", 1200), P("b", 900)]) == 1050


def test_a_doubles_result_moves_all_four_players():
    r = rate([P("a1", 1200), P("a2", 900)], [P("b1", 1030), P("b2", 1010)], SWEEP)
    assert set(r["deltas"]) == {"a1", "a2", "b1", "b2"}
    assert r["deltas"]["a1"] == r["deltas"]["a2"] > 0
    assert r["deltas"]["b1"] == r["deltas"]["b2"] < 0
    assert r["doubles"] is True


def test_doubles_conserves_the_rating_pool():
    r = rate([P("a1", 1200), P("a2", 900)], [P("b1", 1030), P("b2", 1010)], CLOSE_WIN)
    assert sum(r["deltas"].values()) == 0


def test_the_doubles_ladder_rates_a_doubles_result_at_nearly_full_weight():
    """Half-weight is right for your overall rating — half of a doubles result
    is your partner. It is wrong for the doubles ladder, where the result is the
    whole of the evidence about how you play in pairs."""
    pair = ([P("a1"), P("a2")], [P("b1"), P("b2")])
    overall = elo.rate_match(*pair, SWEEP)["deltas"]["a1"]
    own = elo.rate_match(*pair, SWEEP,
                         doubles_factor=elo.DOUBLES_OWN_K_FACTOR)["deltas"]["a1"]
    assert own > overall > 0
    assert elo.DOUBLES_K_FACTOR < elo.DOUBLES_OWN_K_FACTOR < 1


def test_a_doubles_result_still_counts_for_less_than_a_singles_one():
    """Even on its own ladder: you did not pick your partner."""
    doubles = elo.rate_match([P("a1"), P("a2")], [P("b1"), P("b2")], SWEEP,
                             doubles_factor=elo.DOUBLES_OWN_K_FACTOR)
    singles = rate(P("a1"), P("b1"), SWEEP)
    assert doubles["deltas"]["a1"] < singles["deltas"]["a1"]


def test_doubles_counts_for_less_than_singles():
    doubles = gain([P("a1"), P("a2")], [P("b1"), P("b2")], SWEEP, who="a1")
    singles = gain(P("a1"), P("b1"), SWEEP)
    assert 0 < doubles < singles


def test_carrying_a_weaker_partner_is_worth_little():
    """1200+900 beating two 1050s is par, so it barely moves; the same pair
    beating two 1200s is an upset and moves plenty."""
    par = gain([P("a1", 1200), P("a2", 900)], [P("b1", 1050), P("b2", 1050)], SWEEP, "a1")
    upset = gain([P("a1", 1200), P("a2", 900)], [P("b1", 1200), P("b2", 1200)], SWEEP, "a1")
    assert upset > par > 0


# --- tallying --------------------------------------------------------------

def test_tally_counts_games_and_points():
    assert elo.tally(CLOSE_WIN) == (2, 1, 31, 23)


def test_score_is_the_share_of_games_won():
    assert rate(P("a"), P("b"), CLOSE_WIN)["score_a"] == pytest.approx(2 / 3, abs=1e-3)


# --- deuce and game length ------------------------------------------------

def test_every_deuce_game_lands_near_the_floor():
    """Won by the minimum two, whatever the format and however long it ran."""
    for hi, lo in ((11, 9), (13, 11), (18, 16), (21, 19), (25, 23), (31, 29)):
        assert elo.mov_multiplier(hi - lo, hi) <= elo.mov_multiplier(2, elo.REFERENCE_GAME)


def test_the_same_margin_is_closer_in_a_longer_game():
    """Two points is 18% of a game to 11 but under 10% of a game to 21, so
    21-19 is the tighter result and has to count as one."""
    assert elo.mov_multiplier(2, 21) < elo.mov_multiplier(2, 11)
    assert elo.mov_multiplier(4, 21) < elo.mov_multiplier(4, 11)


def test_proportionally_equal_games_score_alike():
    """A game to 21 is rated on the same curve as a game to 11 once its margin
    is read relative to the game being played — no second set of constants."""
    for (a1, b1), (a2, b2) in (((11, 7), (21, 13)), ((11, 9), (21, 17)),
                               ((11, 2), (21, 4))):
        assert abs(elo.mov_multiplier(a1 - b1, a1)
                   - elo.mov_multiplier(a2 - b2, a2)) < 0.06


def test_the_eleven_point_calibration_is_untouched():
    """Rescaling must not have quietly moved the numbers everything else was
    tuned against."""
    assert elo.mov_multiplier(elo.MOV_BASELINE, 11) == pytest.approx(1.0)
    assert elo.mov_multiplier(4) == elo.mov_multiplier(4, 11)


def test_a_freak_short_score_cannot_read_as_a_whitewash():
    """Without a floor on the divisor, a 2-0 would rescale to an 11-0."""
    assert elo.mov_multiplier(2, 2) < elo.MOV_MAX
    assert elo.mov_multiplier(2, 2) == elo.mov_multiplier(2, elo.MIN_GAME)


def test_a_session_of_deuce_battles_barely_moves_anyone():
    deuces = gain(P("a"), P("b"), [(12, 10), (15, 13), (18, 16)])
    routine = gain(P("a"), P("b"), NORMAL)
    assert 0 < deuces < routine


def test_points_totals_are_recorded_but_do_not_drive_the_rating():
    """The maths reads per-game margins; the totals are for the player card."""
    r = rate(P("a"), P("b"), [(21, 19)])
    assert r["points_a"] == 21 and r["points_b"] == 19
    assert r["deltas"]["a"] > 0


def test_twenty_one_point_games_are_rated_sensibly_end_to_end():
    """The format actually being played: a 2-1 nets to about one clean win, and
    a 3-0 to roughly three."""
    two_one = gain(P("a"), P("b"), [(21, 19), (21, 14), (16, 21)])
    three_nil = gain(P("a"), P("b"), [(21, 19), (21, 14), (21, 16)])
    one_nil = gain(P("a"), P("b"), [(21, 17)])
    assert 0 < two_one < three_nil
    assert three_nil > 2 * one_nil


# --- the skunk rule (11-0 ends the game) ----------------------------------

def test_a_skunk_is_the_most_decisive_result_there_is():
    """House rule: reach 11-0 and the game is over. Its winning score is 11, so
    it reads as a complete game-to-11 whitewash rather than a half-played game
    to 21 — which is what it is."""
    # Asserted as "nothing beats it" rather than "it equals MOV_MAX": hitting
    # the ceiling was an artefact of the old steeper curve, and the claim worth
    # holding is that no real scoreline is more decisive than a skunk.
    skunk = elo.mov_multiplier(11, 11)
    for margin, winner_points in ((19, 21), (16, 21), (9, 11), (13, 21)):
        assert skunk >= elo.mov_multiplier(margin, winner_points)
    assert skunk > elo.mov_multiplier(4, 11)      # and well clear of a normal win


def test_a_skunk_beats_a_normal_win_by_about_double():
    assert gain(P("a"), P("b"), [(11, 0)]) > gain(P("a"), P("b"), [(21, 13)]) > 0


def test_a_skunk_mixes_into_a_longer_session(fake=None):
    """One game ending early doesn't disturb the others in the same session."""
    with_skunk = gain(P("a"), P("b"), [(21, 14), (11, 0), (21, 16)])
    without = gain(P("a"), P("b"), [(21, 14), (21, 13), (21, 16)])
    assert with_skunk > without > 0


def test_losing_a_skunk_costs_the_most():
    assert gain(P("a"), P("b"), [(0, 11)]) < gain(P("a"), P("b"), [(13, 21)]) < 0


def test_the_two_spellings_of_a_skunk_rate_identically():
    """21-0 is a mis-logged 11-0, and parsing folds it onto one. Even unfolded
    it rates the same, because the margin is read relative to the game being
    played and both rescale to 11 — which is what makes the fold a
    record-keeping fix rather than a scoring change."""
    assert gain(P("a"), P("b"), [(21, 0)]) == gain(P("a"), P("b"), [(11, 0)])
    assert elo.mov_multiplier(21, 21) == elo.mov_multiplier(11, 11)


def test_a_skunk_still_conserves_the_pool():
    r = rate(P("a", 1200), P("b", 900), [(11, 0)])
    assert sum(r["deltas"].values()) == 0


# --- the books balance -----------------------------------------------------

CONSERVATION_CASES = {
    "two settled players": ([P("a", 1100)], [P("b", 1000)], CLOSE_WIN),
    "two newcomers": ([P("a", games=0)], [P("b", games=0)], SWEEP),
    "a newcomer beating a veteran": ([P("a", games=0)], [P("b", games=400)], SWEEP),
    "a newcomer losing to one": ([P("a", games=0)], [P("b", games=400)],
                                 [(4, 11)] * 3),
    "mid-calibration, either way": ([P("a", games=7)], [P("b", games=90)], TIGHT),
    "a long session": ([P("a", games=0)], [P("b", games=300)], [(11, 6)] * 9),
    "a single game": ([P("a", games=2)], [P("b", games=250)], [(11, 9)]),
    "a dead-even session": ([P("a", games=0)], [P("b", games=300)],
                            [(11, 7), (7, 11)]),
    "doubles, mixed experience": ([P("a1", 1200, 0), P("a2", 900, 300)],
                                  [P("b1", 1030, 50), P("b2", 1010, 400)], SWEEP),
    "doubles, one newcomer on each side": ([P("a1", 1100, 0), P("a2", 1000, 200)],
                                           [P("b1", 1050, 0), P("b2", 990, 200)],
                                           CLOSE_WIN),
    "a big rating gap": ([P("a", 1600, 0)], [P("b", 800, 500)], SWEEP),
}


@pytest.mark.parametrize("name", sorted(CONSERVATION_CASES))
def test_a_match_mints_nothing_and_burns_nothing(name):
    """The property the whole ladder rests on: a rating is only a claim against
    everyone else's, so every point that appears has to come from somebody."""
    side_a, side_b, games = CONSERVATION_CASES[name]
    assert sum(rate(side_a, side_b, games)["deltas"].values()) == 0


@pytest.mark.parametrize("name", sorted(CONSERVATION_CASES))
def test_what_was_paid_is_what_the_ratings_did(name):
    """The reported delta and the stored rating can never disagree — a match
    that says +9 has to leave the player 9 higher."""
    side_a, side_b, games = CONSERVATION_CASES[name]
    rated = rate(side_a, side_b, games)
    for uid, delta in rated["deltas"].items():
        assert rated["after"][uid] - rated["before"][uid] == delta


def test_the_two_sides_share_one_stake():
    """Not each their own: a newcomer cannot move further than their opponent in
    the same game *and* have the books balance. The extra would be minted."""
    assert elo.match_k([P("a", games=0), P("b", games=0)], 3) == \
        pytest.approx(elo.session_k(0, 3))
    assert elo.match_k([P("a", games=900), P("b", games=900)], 3) == \
        pytest.approx(elo.session_k(900, 3))
    # A newcomer and a veteran meet in the middle.
    mixed = elo.match_k([P("a", games=0), P("b", games=900)], 3)
    assert elo.session_k(900, 3) < mixed < elo.session_k(0, 3)


def test_the_settled_board_does_not_feel_the_change():
    """Two established players are the common case, and their stake is exactly
    K_SETTLED, so conserving cost them nothing."""
    assert elo.match_k([P("a", games=500), P("b", games=500)], 1) == \
        pytest.approx(elo.K_SETTLED)


def test_a_newcomer_still_converges_far_faster_than_the_old_rule():
    """Sharing the stake costs a newcomer some speed against a veteran. It must
    not cost so much that calibration stops being worth having: the old rule's
    provisional K was 16."""
    assert elo.match_k([P("a", games=0), P("b", games=900)], 3) > 2 * 16


def test_nothing_is_created_when_the_loser_is_on_the_floor():
    """They have nothing left to give, so their opponent cannot be handed it."""
    rated = rate(P("w", 150), P("l", elo.RATING_FLOOR), SWEEP)
    assert rated["deltas"]["l"] == 0
    assert rated["deltas"]["w"] == 0
    # And on the way down to it, the winner takes only what was really paid.
    near = rate(P("w", 150), P("l", elo.RATING_FLOOR + 5), SWEEP)
    assert sum(near["deltas"].values()) == 0
    assert near["after"]["l"] == elo.RATING_FLOOR


def test_a_floored_partner_does_not_cost_their_opponents_unevenly():
    """Two winners trimmed by an odd number still come out within a point of
    each other, rather than one of them absorbing the whole correction."""
    rated = rate([P("w1", 300), P("w2", 300)],
                 [P("l1", elo.RATING_FLOOR), P("l2", elo.RATING_FLOOR)], SWEEP)
    gains = [rated["deltas"]["w1"], rated["deltas"]["w2"]]
    assert abs(gains[0] - gains[1]) <= 1
    assert sum(rated["deltas"].values()) == 0


# --- winning never costs you ----------------------------------------------

def test_winning_a_session_never_costs_rating():
    """The one complaint the ladder actually produced. Match #77: the underdogs
    won two games of three, got blown out in the third, and lost rating."""
    a = [{"uid": "a", "rating": 956, "games": 50}]
    b = [{"uid": "b", "rating": 982, "games": 50}]
    out = elo.rate_match(a, b, [(10, 21), (25, 23), (21, 18)])
    assert out["deltas"]["a"] >= 0, "the side that won the session lost rating"
    assert out["deltas"]["b"] <= 0


@pytest.mark.parametrize("games", [
    [(10, 21), (25, 23), (21, 18)],      # two narrow wins, one thrashing
    [(2, 11), (11, 9), (11, 9)],         # the same shape, games to 11
    [(0, 21), (21, 19), (21, 19)],       # a whitewash against, two squeakers
    [(1, 11), (12, 10), (11, 9), (3, 11), (11, 9)],   # 3-2 with two maulings
])
def test_the_side_that_won_more_games_never_goes_down(games):
    for ra, rb in ((1000, 1000), (800, 1200), (1200, 800)):
        out = elo.rate_match([{"uid": "a", "rating": ra, "games": 50}],
                             [{"uid": "b", "rating": rb, "games": 50}], games)
        won_a = sum(1 for x, y in games if x > y) > sum(1 for x, y in games if y > x)
        winner = "a" if won_a else "b"
        assert out["deltas"][winner] >= 0, (games, ra, rb, out["deltas"])


def test_a_session_that_settles_nothing_moves_nobody():
    """Zeroed rather than floored: flooring the winner at zero would leave the
    loser holding a gain minted out of nothing, and the ladder conserves."""
    out = elo.rate_match([{"uid": "a", "rating": 956, "games": 50}],
                         [{"uid": "b", "rating": 982, "games": 50}],
                         [(10, 21), (25, 23), (21, 18)])
    assert sum(out["deltas"].values()) == 0


def test_the_guarantee_does_not_touch_an_ordinary_win():
    """It only bites when the margins point the other way from the result."""
    out = elo.rate_match([{"uid": "a", "rating": 1000, "games": 50}],
                         [{"uid": "b", "rating": 1000, "games": 50}],
                         [(21, 15), (21, 17)])
    assert out["deltas"]["a"] > 0


def test_losing_a_session_can_still_cost_nothing_but_never_pays():
    """The mirror: the losing side is never handed rating either."""
    out = elo.rate_match([{"uid": "a", "rating": 1000, "games": 50}],
                         [{"uid": "b", "rating": 1000, "games": 50}],
                         [(21, 19), (10, 21), (12, 21)])
    assert out["deltas"]["a"] <= 0 and out["deltas"]["b"] >= 0


def test_a_drawn_session_is_untouched_by_the_guarantee():
    out = elo.rate_match([{"uid": "a", "rating": 1000, "games": 50}],
                         [{"uid": "b", "rating": 1000, "games": 50}],
                         [(21, 10), (10, 21)])
    assert out["deltas"] == {"a": 0, "b": 0}
