"""
Elo maths for table tennis — pure functions, no I/O and no Slack.

**Every game is rated on its own, and they add up.** A session runs as long as
people have time for, so its length is information, not noise: winning 8 of 10
is a far stronger claim than winning 2 of 3, and rating the encounter as one
unit would throw that away. Ten games move a rating about three times as far as
three games, and a session that splits evenly moves nobody.

Each game contributes:

    K · mov · upset · (won ? 1 : 0  −  E)

  E      expected score from the rating gap — the standard logistic curve,
         fixed for the whole session so the result can't depend on the order
         the games happened to be typed in.
  mov    margin of victory for *that game*, log-damped and clamped, so 11-2
         and 11-9 are not the same evidence.
  upset  the correction below: a favourite is *expected* to win big, so their
         blowout says less than an underdog's.

Losses in a session cancel wins, so the whole thing reduces to "how much better
did you do than expected". Winning narrowly against someone far below you is
worth nothing — you were expected to win by more — but it is never worth less
than nothing: **winning a session never costs rating, and losing one never pays.**
Where the margins point the other way from the result, the session is scored as
a draw and nobody moves. See rate_match().

K is not a constant. A newcomer's 1000 is a guess, so their first games are
rated hard and the weight eases off smoothly as they play — a player brings
about four times as much to their first game as to their hundredth. One K is
used for a whole session, being the mean of the K its games would have carried,
because a per-game K would make a 2-2 split stop cancelling: the wins would be
worth more than the losses purely for having been typed first.

**The ladder is zero-sum.** Whatever one side gains, the other loses, at any
session length, in singles and in doubles, whoever is playing. That is the whole
point of a rating — it only means anything against everyone else's, and a pool
that quietly inflates makes this month's 1200 a different thing from last
month's. It is also why the two sides share one stake rather than each bringing
their own K: a system cannot move a newcomer further than their opponent in the
same game *and* balance, because the extra would have to be minted. See
match_k().

Doubles rates a team at its members' mean rating. In table tennis that is not
the compromise it is in other sports — the pair *alternates strokes*, by rule,
so each player really does play half the balls. The same logic sets the discount:
a doubles result carries about half the evidence about you, so it counts half on
your overall rating. On the doubles ladder itself it counts nearly in full,
because that ladder is a ladder of how people play in pairs; what is left of the
discount is for the partner you did not choose.
"""
import math

START_RATING = 1000
RATING_FLOOR = 100  # ratings can sink, but not to something that reads as a bug

# How hard one *game* may move a rating, and how that eases off.
#
# A newcomer's rating is a guess — 1000, the same guess everyone gets — and the
# job of their first games is to replace it. So K starts high and decays
# smoothly towards the settled value with every game played:
#
#     K(n) = K_SETTLED + (K_NEW - K_SETTLED) · e^(-n / K_DECAY)
#
# which is the shape every comparable system uses. chess.com steps 40 → 20 → 10,
# the USCF divides by (N + m), Glicko and Codeforces carry an uncertainty that
# narrows; all of them move a newcomer several times as far as a veteran. The
# curve is chosen over the steps because a step is a cliff: under the old
# 16-until-50-then-11 rule, a player's 49th game moved them 45% further than
# their 51st, for no reason anyone could see on the board.
#
# Pitched a notch above chess.com's provisional 40 rather than at Codeforces,
# where a first contest moves someone by hundreds. A first three-game session
# here moves a newcomer by something like 80 points, which is loud enough to be
# worth playing and quiet enough that one odd evening is not a verdict.
K_NEW = 55          # the very first game: a first result should be loud
K_SETTLED = 13      # a settled player. Everything on the board scales with this
K_DECAY = 12        # games for the gap between the two to shrink by 1/e
# Where the curve is close enough to settled to stop calling anyone new. Used
# for what /tt help says, never in the maths.
CALIBRATION_GAMES = 30

# In table tennis doubles the pair *alternates strokes* — it is a rule of the
# game, not a tactic — so a doubles result is about half yours and half your
# partner's, and it carries about half the evidence about you.
DOUBLES_K_FACTOR = 0.5
# Except on the doubles ladder itself, which is a ladder of how people play in
# pairs. There the result is the whole of the evidence, not half of it; the
# discount that remains is for the partner you did not choose.
DOUBLES_OWN_K_FACTOR = 0.8

# The margin curve is calibrated on a game to 11: mov == 1.0 at a 4-point margin,
# which is a normal, clearly-won 11-7.
MOV_BASELINE = 4
REFERENCE_GAME = 11
# Longer games spread scores out — winning a game to 21 by 4 is close, while the
# same 4 points in a game to 11 is comfortable. Margins are rescaled to their
# game-to-11 equivalent before the curve sees them, so the same curve serves
# 11s, 21s and first-to-7 without three sets of constants.
MIN_GAME = 7  # floor on the divisor, so a freak 2-0 can't read as a whitewash
# How much the scoreline matters. Above 1 the curve spreads out; the further
# above, the more a margin swamps the result it is supposed to be adjusting.
#
# It was 1.5, and that was too steep to survive contact with real scorelines. At
# 1.5 an ordinary 21-18 came out at 0.45 — the floor — which is also exactly what
# a 25-23 deuce got, so a comfortable win and a squeaker were the same evidence,
# while a 10-21 loss was worth 1.29, nearly three times either of them.
#
# Match #77 is what found it: the underdogs won two games of three, were expected
# to win 46% of them, and lost rating anyway. On the results alone that session
# was worth +0.61; the margin curve turned it into -0.10. A margin should adjust
# a result, not overturn it.
#
# At 1.0 an ordinary win sits clear of the floor again (21-18 → 0.59, distinct
# from a 25-23 at 0.45), a whitewash is still worth about three times a squeaker,
# and a heavy loss is worth twice an ordinary win rather than three times. Note
# that raising MOV_MIN would have been the wrong fix: a higher floor drags *more*
# games onto it, and the test that a 21-19 counts for less than an 11-9 is what
# caught that.
MOV_GAIN = 1.0
MOV_MIN, MOV_MAX = 0.45, 1.75

# A favourite is expected to win by a lot, so a big win tells us less about them
# than the same win would about an underdog. Without this, rating gaps quietly
# inflate the strong (the standard margin-of-victory autocorrelation problem).
UPSET_SCALE = 2.2
UPSET_GAP_CAP = 800  # keeps the denominator far from zero, which would flip signs

MAX_POINTS = 99  # a game score above this is a typo, not a marathon
# Sessions are any length; this is only a fat-finger guard. Set from what people
# actually play — the median session is 3 games and the longest ever recorded is
# 6 — so anything past this is a mistyped score line, not an epic evening.
MAX_GAMES = 10


def expected(rating_a, rating_b):
    """Probability-ish score side A is expected to take in one game, in [0, 1].
    A 400-point edge is the classic 10:1 favourite."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def k_factor(games_played, doubles=False, doubles_factor=None):
    """How hard one *game* may move the rating of someone who has played
    `games_played` of them.

    Smooth, and steep at the start: a player brings about four times as much to
    game 1 as to game 100. That is the whole point — a newcomer's 1000 is a
    guess, and a rating system that takes forty games to correct it has spent
    forty games telling everyone something it knew to be wrong.

    This is what one player *brings*, not what they end up moving. A match is
    played for a single stake shared by both sides, or it could not conserve;
    match_k() is where the two are reconciled.
    """
    k = K_SETTLED + (K_NEW - K_SETTLED) * math.exp(-max(0, games_played) / K_DECAY)
    if not doubles:
        return k
    return k * (DOUBLES_K_FACTOR if doubles_factor is None else doubles_factor)


def session_k(games_played, length, doubles=False, doubles_factor=None):
    """The K one player brings to a whole session: the mean of the K they would
    have carried into each of its games.

    One K for the session, not one per game, and that is deliberate. A session
    is rated as a sum of its games, and if each game carried its own K then a
    2–2 split would no longer come to nothing — the two wins would be worth more
    than the two losses purely because they were typed first. Order would start
    to matter, and the model promises it doesn't.

    Taking the mean keeps both properties and still does the work: a newcomer's
    ten-game first evening is rated at the K of about their fifth game rather
    than their first, so it converges instead of overshooting.
    """
    if length <= 0:
        return k_factor(games_played, doubles, doubles_factor)
    total = sum(k_factor(games_played + i, doubles, doubles_factor)
                for i in range(length))
    return total / length


def mov_multiplier(margin, winner_points=None):
    """Scale one game's swing by how decisively it was won.

    `winner_points` is the winning score, used to read the margin *relative to
    the game being played*: 21-17 and 11-9 are both "won by about a fifth of the
    game" and should count the same, even though one margin is 4 and the other 2.
    Omit it and the margin is taken at face value, i.e. as a game to 11.

    log damps it and the clamp bounds it, so the multiplier stays in a range a
    player can reason about — roughly 0.5 for a deuce, 1.75 for a whitewash.
    """
    m = abs(margin)
    if winner_points:
        m *= REFERENCE_GAME / float(max(abs(winner_points), MIN_GAME))
    raw = math.log(1.0 + m) / math.log(1.0 + MOV_BASELINE)
    return min(MOV_MAX, max(MOV_MIN, raw ** MOV_GAIN))


def upset_correction(winner_gap):
    """Damp a favourite's big win, amplify an underdog's.

    `winner_gap` is the game winner's rating minus the loser's — positive when
    the favourite won. Capped before use: the denominator would reach zero at a
    gap of −2200 and then go negative, which would flip the sign of the whole
    update and hand the loser the points.
    """
    gap = max(-UPSET_GAP_CAP, min(UPSET_GAP_CAP, winner_gap))
    return UPSET_SCALE / (gap * 0.001 + UPSET_SCALE)


def tally(games):
    """(games_a, games_b, points_a, points_b) for a list of (a, b) game scores."""
    games_a = sum(1 for a, b in games if a > b)
    games_b = sum(1 for a, b in games if b > a)
    return games_a, games_b, sum(a for a, _ in games), sum(b for _, b in games)


def _round_half_away(x):
    """Round to int, halves away from zero. Python's round() is banker's
    rounding, which turns a +0.5 swing into 0 and looks like nothing happened."""
    return int(x + 0.5) if x >= 0 else int(x - 0.5)


def team_rating(side):
    """A team is worth its members' mean rating. A 1200 carrying a 900 plays like
    a 1050 pair — beating two 1050s is then par, not an upset."""
    return sum(p["rating"] for p in side) / float(len(side))


def games_played(player):
    """Games, not sessions — what K is measured in, and what it decays over."""
    return int(player.get("games_won", 0)) + int(player.get("games_lost", 0))


def session_weights(rating_a, rating_b, games):
    """One `mov · upset · (result − E)` per game, from side A's point of view.

    One entry per game rather than a single total, so the caller knows how many
    games a session ran to — that length is what session_k() averages its K
    over. The session is still rated on the sum of these: every game in it
    carries the same K, which is what keeps a 2-2 split cancelling. A dead heat
    contributes 0.0 rather than being dropped, so the list stays aligned with
    the games it came from and the count stays honest.

    Side B's weights are exactly the negatives of these — same mov, same upset
    correction, and (1−result) − (1−E) == −(result − E) — which is half of what
    keeps the model zero-sum. The other half is the shared stake in match_k().
    """
    exp_a = expected(rating_a, rating_b)
    out = []
    for a, b in games:
        if a == b:
            out.append(0.0)  # a dead-even game decided nothing
            continue
        won_a = a > b
        gap = (rating_a - rating_b) if won_a else (rating_b - rating_a)
        weight = mov_multiplier(a - b, max(a, b)) * upset_correction(gap)
        out.append(weight * ((1.0 if won_a else 0.0) - exp_a))
    return out


def session_weight(rating_a, rating_b, games):
    """The whole session's signal, from side A's point of view. Informational
    now that K is applied per game — the summary blob reports it."""
    return sum(session_weights(rating_a, rating_b, games))


def match_k(players, length, doubles=False, doubles_factor=None):
    """The one stake a match is played for: the mean of what each player would
    have brought to it on their own.

    It has to be shared, because a rating system cannot both move a newcomer
    further than their opponent *in the same game* and conserve — the extra has
    to come from somewhere, and the only honest somewhere is the opponent. So
    the pair meets in the middle:

      two settled players   → K_SETTLED exactly, so the established board feels
                              nothing at all;
      two newcomers         → K_NEW, so calibration between new players is
                              untouched;
      a newcomer and a vet  → about halfway, so the newcomer still converges far
                              faster than the old rule managed, and the veteran
                              moves more than usual for that one game.

    That last line is the price of conservation, and it is the right way round:
    a settled player who loses to an unknown has learned something about
    themselves too.
    """
    ks = [session_k(p.get("games", 0), length, doubles=doubles,
                    doubles_factor=doubles_factor) for p in players]
    return sum(ks) / len(ks) if ks else K_SETTLED


def _conserve(deltas, before, after):
    """Give away only what was actually lost.

    The floor stops a rating falling below RATING_FLOOR, so a player pinned
    there drops less than the maths said — and without this, the difference
    would be handed to their opponent out of nothing. Nobody has it to give, so
    the winning side is trimmed to what the losing side really paid.

    Mutates in place: `after` has to move with `deltas` or the two would
    disagree about the same match.
    """
    gained = sum(d for d in deltas.values() if d > 0)
    lost = -sum(d for d in deltas.values() if d < 0)
    excess = gained - lost
    if excess <= 0:
        return deltas
    winners = [uid for uid, d in deltas.items() if d > 0]
    # Spread the trim evenly, with the remainder going to the biggest gains, so
    # two partners never come out of the same match a point apart for no reason.
    for i, uid in enumerate(sorted(winners, key=lambda u: -deltas[u])):
        share = excess // len(winners) + (1 if i < excess % len(winners) else 0)
        deltas[uid] -= share
        after[uid] = before[uid] + deltas[uid]
    return deltas


def rate_match(side_a, side_b, games, doubles_factor=None):
    """Rate one session and return everything needed to store and narrate it.

    side_a / side_b: [{"uid": str, "rating": int, "games": int}, …] — one entry
    for singles, two for doubles. `games`: [(a_points, b_points), …], any length.

    `doubles_factor` overrides how much a doubles result counts; the doubles
    ladder passes DOUBLES_OWN_K_FACTOR, because there the result is the whole of
    the evidence rather than half of it.

    Ratings are read from the arguments, so the caller must pass *current*
    ratings: a session is always rated at the moment it is confirmed, never at
    the moment it was typed, or two sessions confirmed out of order would apply
    stale numbers.
    """
    doubles = len(side_a) > 1
    games_a, games_b, points_a, points_b = tally(games)
    rating_a, rating_b = team_rating(side_a), team_rating(side_b)

    exp_a = expected(rating_a, rating_b)
    weights = session_weights(rating_a, rating_b, games)
    weight_a = sum(weights)
    decided = games_a + games_b

    # **Winning a session never costs you rating.** The margin maths can still
    # say it should — win two games narrowly, lose one by a mile, and the sum
    # comes out negative even though you took the session. That is defensible
    # arithmetic and an indefensible thing to show somebody who just won, and it
    # is the single complaint the ladder has actually produced (match #77).
    #
    # So the session is scored as a draw instead: nobody moves. Not "the winner
    # is floored at zero and the loser keeps their gain" — that would hand the
    # losing side rating minted out of nothing, and the ladder conserves. The
    # honest reading of a session whose scorelines point the other way from its
    # result is that it settled nothing.
    if (games_a - games_b) * weight_a < 0:
        weight_a = 0.0

    # One stake for the match, so what one side gains the other side loses. See
    # match_k() for why it cannot be per player and still balance.
    k = match_k(side_a + side_b, len(weights), doubles=doubles,
                doubles_factor=doubles_factor)

    deltas, before, after = {}, {}, {}
    for side, sign in ((side_a, weight_a), (side_b, -weight_a)):
        for p in side:
            swing = k * sign
            rating = int(p["rating"])
            # Half away from zero, on a magnitude both sides share, so the two
            # roundings are exact negatives of each other rather than nearly so.
            new = max(RATING_FLOOR, rating + _round_half_away(swing))
            before[p["uid"]] = rating
            after[p["uid"]] = new
            # Read the delta back off the floor-clamped result, so the number we
            # report is always the change that actually happened.
            deltas[p["uid"]] = new - rating

    _conserve(deltas, before, after)

    return {
        "doubles": doubles,
        "games_a": games_a, "games_b": games_b,
        "points_a": points_a, "points_b": points_b,
        "score_a": round(games_a / float(decided), 4) if decided else 0.5,
        "expected_a": round(exp_a, 4),
        "weight_a": round(weight_a, 4),
        # Mean margin multiplier across the session — informational only.
        "mov": round(sum(mov_multiplier(a - b, max(a, b)) for a, b in games)
                     / len(games), 4) if games else 1.0,
        "deltas": deltas, "before": before, "after": after,
    }


def win_probability(side_a, side_b):
    """Chance side A takes the next game — what `/tt odds` reports."""
    return expected(team_rating(side_a), team_rating(side_b))
