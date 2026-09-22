# TT Ranker

A Slack bot that keeps an Elo ladder for office table tennis. Play as many games
as you have time for, type the scores, the other side presses **Confirm**, and
everyone's rating moves.

Singles and doubles, one ladder, no spreadsheet.

```
you:       /tt log @bob 11-7 9-11 11-5

in #table-tennis                    in @bob's DM ─────────────────┐
  🏓 @you  2–1  @bob                  🏓 @you  2–1  @bob          │
  11-7   9-11   11-5                  11-7   9-11   11-5          │
  Logged by @you · Sent to @bob       @you logged this. Is it     │
  to confirm.                         right? Nothing moves until  │
                                      you say so.                 │
  (no buttons — the channel           [ ✅ Confirm ] [ ❌ Wrong ]  │
   can read it, not rule on it)      ───────────────────────────── ┘

…@bob presses Confirm, and both messages become:

  🏓 @you beat @bob — 2–1
  11-7   9-11   11-5

  @you  1000 → 1010  +10
  @bob  1000 →  990  -10
  Match #17 · confirmed by @bob
```

Every game is rated on its own, so a ten-game session counts for more than a
three-game one, and margins are read relative to the game — 21-19 is a squeaker,
11-9 slightly less so. [How the rating works](#how-your-rating-is-calculated).

---

## Commands

**`/tt help`** is the one place: how to log a session, then every command one
line each grouped by what you're trying to do, then how the rating works. The
admin commands are only listed for admins — a list of things you can't do is a
worse list. `commands`, `cheatsheet`, `quick` and `usage` all land on it, because
those are the words people reach for when they want the list.

The list is generated from the parser's own alias table and a test asserts it
covers every command with no duplicates, **and that every example on it parses
back to the command it claims to be** — so it can't fall behind what the bot
actually does. The hand-kept bullet list it replaced covered about two thirds of
the commands and had no way of telling.

Mistype one and you get a guess rather than the manual:

```
/tt boad
→ I don't know `boad`. Did you mean `/tt board`?
  `/tt help` lists everything.
```

Nothing is guessed when nothing is close — a wrong guess sends you off to read
about a command you never wanted.

Everything is one slash command, `/tt`.

| Command | What it does |
|---|---|
| **`/tt log`** · shortcuts menu → *Log a table tennis session* | **Opens a form — pick the players, type the scores** |
| `/tt log @bob 11-7 9-11 11-5` | Log singles — you against Bob, any number of games |
| `/tt log @partner vs @dan @eve 11-7 11-9` | Doubles. `vs` splits the sides |
| `/tt log @ann @bob vs @cal @dee 11-7 11-9` | Record a session you weren't in |
| `/tt board` · `/tt board singles` · `/tt board doubles` | The ladder · one format only |
| `/tt edit 33 21-17 21-19` | Correct a logged match — admins (`swap`, `void`) |
| `/tt me` · `/tt me @bob` | One player's card — rating, record, streak, peak |
| `/tt history` · `/tt history @bob` | Recent results |
| `/tt pending` | Sessions still waiting on confirmation |
| `/tt odds @bob` | Who's favoured, before you play |
| `/tt undo` | Roll back the last session *you* logged |
| `/tt register` | Join early (playing registers you anyway) |
| `/tt sync` | Put everyone already in this channel on the ladder |
| `/tt name Your Name` | How you appear on the web ladder |
| `/tt name @bob Bob Smith` | Admins only — set it for someone else |
| `/tt who ChumChum` · `/tt who @bob` | Who is that? · what are they called? |
| `/tt intro` · `/tt intro clear` | Post the how-it-works message · take it down |
| **`/tt schedule`** · shortcuts menu → *Schedule a table tennis match* | **Opens a form — pick the players and a start time** |
| `/tt schedule @bob 6pm` | Or type it — `in 30m`, `6pm`, `6:30pm` and `18:30` all work |
| `/tt reschedule 6 7pm` | Move a fixture — **Move it** on the message does the same |
| **`/tt challenge`** · shortcuts menu → *Challenge someone to table tennis* | **Opens a form — pick who, pick how long** |
| `/tt challenge @bob best of 5` | Or type it. `bo7`, `first to 3`, `5 games`, `at 6pm` |
| `/tt accept 4` · `/tt decline 4` | Answer a challenge — the DM buttons do the same |
| `/tt challenges` | Every challenge still waiting on an answer |
| `/tt shame` · `/tt shame @bob` | The wall of shame — results thrown out, challenges ducked |
| `/tt book` · `/tt book 6` | Open fixtures · one in full, with every stake |
| `/tt wallet` | Your spins and recent moves |
| `/tt transfer @bob 500` | Admins only — move spins between wallets |
| `/tt help` | All of the above, in Slack |

### The form

Two ways in, same form:

- **`/tt log`** on its own
- the **shortcuts menu** → *Log a table tennis session*. That's the `/` button at
  the right of the message toolbar, or just type `/` in the message box and
  search. (Not the `+` button — that one is files and workflows.)

A people picker for your side (you're pre-selected), one for your opponents, and
a box for the scores. Opened from the shortcuts menu it also asks which channel
to post the result in, since a global shortcut carries no channel context;
started from `/tt log` it already knows.

```
┌─ Log a session ───────────────────────────┐
│  Your side        [ @you            ▾ ]   │
│  Add a partner for doubles.               │
│                                           │
│  Opponents        [ @bob            ▾ ]   │
│                                           │
│  Game scores                              │
│  [ 11-7  9-11  11-5                   ]   │
│  The points in each game, your side       │
│  first. Log as many as you played.        │
│                                           │
│  Post the result in   [ #table-tennis ▾ ] │  ← shortcuts menu only
│                                           │
│                    [ Cancel ]  [ Log it ] │
└───────────────────────────────────────────┘
```

There's no singles/doubles switch — one name a side is singles, two is doubles,
and each goes to its own board as well as the overall one.
Mistakes come back attached to the field that's wrong, so a typo is one
correction rather than retyping the whole thing. Both routes run the same
validation and end at the same confirmation prompt.

Scores are **the points in each game**, one per game: `11-7 9-11 11-5` is three
games won 2–1. There's no fixed session length — log two games or ten, which is
the cap. Games to 11, to 21 and first-to-7 all work, and you can mix them in one
session. `11 - 7`, `11:7` and `11–7` are all read the same way. The word `log`
is optional once you know the bot — `/tt @bob 11-7` works.

**Skunked?** The house rule ends a game at 11-0, so log it as `11-0`. It scores
as the most decisive result there is — a single skunk is worth about double a
normal win, because its winning score marks it as a *finished* game-to-11
whitewash rather than a half-played game to 21.

Log it as `21-0` — the number you play to rather than the number on the table
when it stopped — and it's **recorded as `11-0`**. The rating is identical
either way, because the margin is read relative to the game being played and
`21-0` and `11-0` both rescale to the same 11. What the fold-in protects is the
*record*: without it, a skunk would put ten points into your points total that
nobody ever played. Any `X-0` past 11 folds the same way; `21-1` doesn't — the
opponent scored, so the game ran its length.

### Confirming

A logged session changes nothing until someone **on the other side** confirms
it. That's the whole integrity model: the only person who can wave a result
through is the person it costs.

**The verdict goes out by DM, not to the channel.** The channel sees the claim
and who it's waiting on — read-only. The buttons go privately to the people
whose rating is at stake:

| Who | Gets | Can |
|---|---|---|
| each opponent | a DM | **✅ Confirm** · **❌ That's wrong** |
| whoever logged it | a DM | **🗑 Cancel this** — their mistake to take back, not their result to wave through |
| everyone else | the channel post | read it |

Buttons sitting in a channel invite everyone who can see them to press, and the
ones who shouldn't only find out after clicking. Keeping them in DMs means the
question reaches exactly the people entitled to answer it.

- **Confirm** — rates the session, and rewrites the channel post *and* every DM
  so no live button is left anywhere for something already decided.
- **That's wrong** — throws it out. Nothing is rated. Log it again properly.
- **Neither** — after 24 hours a daily sweep applies it anyway. Silence past the
  window counts as agreement; the losing side had a day and a button.

In doubles both opponents are asked and either can settle it. If a bystander
logged the session, all the players are asked. If nobody could be DM'd — app DMs
switched off — whoever logged it is told, and the sweep still applies it.

**Admins skip it.** Anyone listed in `TT_ADMINS` has their sessions rated the
moment they log them, and can confirm or throw out anybody else's pending
session — the only way to clear one whose players have gone quiet, short of
waiting for the daily sweep. The result still says *recorded by @them* 🛡, so
skipping the confirmation is visible to the channel rather than silent.

### Correcting a match that was logged wrong

`/tt undo` only reaches the last match *you* logged. For anything older, or
anybody else's, an admin has `/tt edit`:

```
/tt edit 33 21-17 11-0 21-13 21-14 21-19   # the scores were wrong
/tt edit 33 swap                            # the names went in backwards
/tt edit 33 void                            # throw the match out entirely
```

`swap` moves only the names — the scores stay in the columns they were typed
in, which is what flips the result. Turning the score columns round as well
would invert it twice and leave the match exactly as it was.

**Editing an old match re-rates every match logged after it.** Those were rated
against the ratings this one produced, so patching one record and leaving the
rest would give a ladder that no sequence of matches could have produced. The
edit replays the whole history instead — the same replay `scripts/recompute.py`
uses, shared in [rerate.py](rerate.py) so the two can't disagree. Afterwards the
ladder is exactly the ladder you'd have had if the right thing had been logged
the first time, which is the property the tests actually assert: they edit a
match, then compare against a ladder that only ever saw the corrected version.

Nothing is written on the first press. `/tt edit` shows what would change —
before, after, who moves and by how much, how many matches get re-rated — and
waits for the button. Applying it **posts to the channel**: a retroactive change
to other people's ratings shouldn't be something only the admin knows about.

Two things it deliberately won't do. It refuses outright if any match is missing
from storage, because a replay on an incomplete history would invent a ladder
rather than rebuild one. And it doesn't touch **spins**: bets were paid on what
the channel was told at the time. If a correction flips who won, the preview
says so in as many words and leaves settling up to a human.

### Three ladders

| Board | Slack | Web |
|---|---|---|
| Singles | `/tt board singles` | the tab it opens on |
| Doubles | `/tt board doubles` | `?view=doubles` |
| Overall | `/tt board` | `?view=overall` |

**Singles is the one it opens on.** (Links pasted before that flip,
`?view=singles`, still work.)

Each board has its **own Elo**, not the overall rating with the other format
filtered out — the history that produced the overall number still has the other
format in it. They are updated side by side: every result moves the overall
rating and exactly one of the two format ratings, and each is rated off its own
ratings, so a singles result is judged against your singles standing and a
doubles result against your doubles one.

**Doubles is a narrower claim than singles, and the tab says so.** A doubles
result is **one number split between two people**. Both partners move by the
same amount, so what the maths actually pins down is the *pair's* combined
rating; the split between the two is never separately measured. Simulated
against the real `elo.py`, a true-700 player who always partners a 1300 settles
around **910**, while their partner is dragged down to **1210** — not points
from nowhere, a transfer from the stronger player. Play with varied partners and
it settles close to the truth; always partner the same person and the two of you
drift together, high or low, with nothing able to separate you.

So read the doubles board as *how the teams you play on do*. Singles is the
board that can tell two people apart, which is why it's the one that opens.

Both format boards qualify at **4 games** rather than 6. Each format's games are
a subset of all games, so the same bar would leave them empty while the overall
one is full — `SINGLES_PLACEMENT_GAMES` and `DOUBLES_PLACEMENT_GAMES` in
[bot.py](bot.py), to raise once volume catches up.

### Calling anyone out

A challenge normally names somebody. An **open** one doesn't — it names a rating
range, and the first person inside it who takes it gets the fixture:

```
/tt challenge open ±100 best of 5      anyone near my level
/tt challenge open 1100-1250 bo7       an explicit range
/tt challenge open +150 at 6pm         anyone up to 150 above me
/tt challenge open @ann ±100           doubles: Ann and I want a pair
```

No range given means ±100 of you. A range wider than 400 points is refused —
that isn't a range, that's everyone.

**Doubles: each side brings its own pair.** You name your teammate when you post
it, because that half of the match is yours to settle; whoever takes it names
theirs on the way in with `/tt accept 7 @dan`. Two named on one side means two on
the other, and the pair is judged on the **average** of the two ratings — so a
1400 can't take a 900–1100 call by bringing a 1000 along.

The range is tested **when somebody presses**, not when the call went up: people
drift, and the honest question is whether they're a fair match now. It's tested
against the format's own rating, so a doubles call is judged on the doubles
board. Failing it leaves the call open for somebody who doesn't — a wrong presser
never burns it.

One standing offer each. Five identical callouts from one person is a spammed
channel, not five chances of a game; `/tt withdraw 7` clears yours. An open call
carries no DM — its button is in the channel, where the people who could answer
it are — so `/tt withdraw` is the only way to take one back, which is why it now
exists.

**An open call isn't anybody's to turn down.** `/tt decline` works on a challenge
aimed *at you* — being asked is what gives you the standing to say no. An open
call is addressed to the channel, so nobody has been asked, and one uninterested
passer-by declining it would close an invitation meant for everyone. Leave it for
somebody else, or `/tt withdraw` it if it's yours. (Not even the person who
posted it declines it; taking it back is a withdrawal, which is what actually
happened.)

Accepted, it becomes an ordinary fixture: betting, `/tt reschedule` and calling
it off all work on it exactly as they already did.

### Joining

**Anyone who joins `TT_CHANNEL` is put on the ladder automatically** and gets a
DM explaining how to log a match. Nobody has to know the bot exists to end up on
it.

Deliberately scoped to that one channel rather than every channel the bot sits
in — being invited somewhere busy for a single match shouldn't enrol that
channel's entire membership.

Two things it doesn't cover, both handled by **`/tt sync`**:

- people who were already in the channel before the bot arrived
- any *other* channel where matches get played

`/tt sync` acts on the channel you run it in, which is why the one command that
enrols people in bulk always names its target explicitly. It's idempotent and
doesn't DM anyone — run it as often as you like.

You can still `/tt register` yourself, and simply playing a match registers
everyone in it.

---

## How your rating is calculated

Everyone starts at **1000**.

### Winning never costs you

**Win the session and your rating never goes down. Lose it and it never goes
up.** Where the scorelines point the other way from the result, the session is
scored as a draw and nobody moves.

This rule exists because the arithmetic could say otherwise. Win two games
narrowly, lose one by a mile, and the margins summed to less than nothing even
though you took the session — which is defensible maths and an indefensible
thing to show somebody who just won. Match #77 was the case that found it: the
underdogs won two games of three, were expected to win 46% of them, and lost a
point each.

Two things changed together. The margin curve was flattened (`MOV_GAIN` 1.5 →
1.0), because at 1.5 an ordinary 21-18 and a 25-23 deuce both bottomed out at
the same weight while a 10-21 loss was worth three times either — a margin was
overturning results rather than adjusting them. And the guarantee above was
added on top, so the case can't come back through some other door.

Nobody is *floored at zero while the other side keeps its gain* — that would
mint rating out of nothing, and [the ladder conserves](#the-books-balance). Both
sides get zero, together.

The cost, stated plainly: scraping a 2-1 past someone far below you used to
*cost* rating, and now it's merely worth nothing. Padding a record against weak
opposition is neutral rather than punished.

**Every game is rated on its own, and they add up.** A session runs as long as
you have time for — two games at lunch, fifteen on a Friday. That length is
information, not noise: winning 8 of 10 is a far stronger claim than winning 2
of 3, so the longer session moves ratings further.

Each game contributes:

```
K  ×  margin  ×  upset  ×  ( did you win it?  −  what you were expected to score )
```

Four inputs. Each one is boring on its own.

### 1 · What you were expected to score

Standard Elo. The gap between the two ratings is the whole input:

| You're rated… | …your expected score per game |
|---|---|
| level | 50% |
| 50 above | 57% |
| 100 above | 64% |
| 200 above | 76% |
| 300 above | 85% |
| 400 above | 91% |
| 600 above | 97% |

400 points is the classic 10-to-1 favourite. In doubles the pair's rating is the
**average** of the two partners, and that average goes into the table.

This expectation is worked out once from the ratings you both walked in with,
and held for the whole session — so the result can't depend on the order the
games happened to be typed in.

### 2 · Did you win the game

1 or 0. That's it. No fractions, because each game is rated separately rather
than the session being averaged into a single result.

Losses inside a session cancel wins, so the whole thing collapses to *how much
better did you do than expected*.

### 3 · How decisively you won it — the margin

This is where the point scores earn their keep. The margin is read **relative to
the game being played**, so the same curve serves games to 11, games to 21 and
first-to-7 without three sets of numbers:

| Won by | in a game to 11 | in a game to 21 |
|---|---|---|
| the minimum 2 | ×0.56 | ×0.45 (floor) |
| a close win | `11-8` ×0.80 | `21-16` ×0.71 |
| **a par win** | `11-7` **×1.00** | `21-13` **×1.04** |
| comfortable | `11-5` ×1.33 | `21-10` ×1.32 |
| a whitewash | `11-2` ×1.71 | `21-4` ×1.70 |

Two points is 18% of a game to 11 but under 10% of a game to 21, so `21-19` is
the tighter result and counts as one. Read raw, every margin in a 21-point game
would come out about twice as decisive as it really was.

An 11-2 is worth roughly **three times** an 11-9. The curve is log-damped and
clamped at both ends, because point margins are noisy — one 11-0 shouldn't
rewrite the ladder, and a single deuce shouldn't erase a win.

### 4 · How much one game may move you — K

Everyone opens at 1000, and that number is a guess. The job of your first games
is to replace it, so they are rated hard and the weight eases off smoothly as
you play:

> **K(n) = 13 + 42 · e^(−n / 12)**, where *n* is games played

| Games played | K | |
|---|---|---|
| 0 | 55 | your first game |
| 5 | 41 | |
| 10 | 31 | half the journey is done |
| 20 | 21 | |
| 30 | 16 | near enough settled |
| 100+ | 13 | settled |
| Doubles | ×0.5 | ×0.8 on the doubles ladder itself |

**That is what you bring, not what you move.** A match is played for one stake
that both sides share — the mean of what each player brought — because a ladder
cannot move you further than your opponent in the same game *and* balance; the
difference would have to be minted, and this one doesn't mint. So:

| Who's playing | Stake | |
|---|---|---|
| two settled players | 13 | exactly as before — the established board is untouched |
| two newcomers | 55 | calibration between new players is untouched too |
| a newcomer and a settled player | 34 | they meet in the middle |

The last row is the price of a closed system, and it cuts the right way: a
settled player who loses to an unknown has learned something about themselves
too. A newcomer still converges about 2.6× faster than the old rule managed.

You bring about **four times** as much to game one as to game one hundred, which
is the ratio every comparable system uses — chess.com steps 40 → 20 → 10, the USCF
divides by (N + m), Glicko and Codeforces carry an uncertainty that narrows. The
opening 55 is pitched a notch above chess.com's provisional 40 and well short of
Codeforces, where a first contest moves someone by hundreds: a first three-game
session here moves a newcomer around 80 points, which is loud enough to be worth
playing and quiet enough that one odd evening is not a verdict.

A *curve*, not steps, because a step is a cliff. The old rule was 16 for fifty
games and 11 after, so your 49th game moved you 45% further than your 51st for
no reason anyone could see on the board.

Counted in games rather than sessions, because a session can be any length —
and counted **per format**, so someone settled at singles is still a newcomer at
doubles and the doubles board moves them properly.

One K is used for a whole session: the mean of the K its games would have
carried. That does two things at once — a newcomer's ten-game first evening is
rated at about the K of its fifth game, so it converges rather than overshooting
on game one's K; and a 2–2 split still comes to exactly nothing, which a per-game
K would have quietly broken by making the wins worth more than the losses purely
for being typed first.

**What it's worth.** A player whose true strength is 1400, starting from 1000,
playing threes against a normal field (simulated, 300 runs, median):

| After | Old rule | New | Gap closed, old → new |
|---|---|---|---|
| 3 games | 1021 | 1067 | 5% → 17% |
| 6 games | 1043 | 1120 | 11% → 30% |
| 12 games | 1079 | 1172 | 20% → 43% |
| 21 games | 1123 | 1212 | 31% → 53% |
| 45 games | 1208 | 1263 | 52% → 66% |
| 90 games | 1270 | 1306 | 68% → 76% |

More than twice as much of the gap closed in the first dozen games. The long
tail is a property of Elo itself rather than of K — you close the last of it by
playing people who aren't already below you.

### Plus one correction: the favourite's blowout counts for less

A strong player is *expected* to win by a lot, so their 11-2 says less about
them than the same 11-2 would say about an underdog. Without correcting for
this, margin-of-victory quietly inflates the already-strong — a well-known flaw
in naive MOV systems.

So the margin multiplier is scaled by the rating gap **of that game's winner over
its loser**: a 400-point favourite winning gets ×0.85, a 400-point underdog
winning gets ×1.22. It applies identically to both sides, so the books still
balance.

---

### What this looks like in practice

**Three games against an equal player:**

| Result | Change |
|---|---|
| 3–0 whitewash `11-2 11-4 11-3` | **+26** |
| 3–0 normal `11-7 11-9 11-8` | **+13** |
| 3–0 every game a deuce `12-10 11-9 13-11` | **+9** |
| 2–1 `11-7 9-11 11-5` | **+10** |

Yes — a 2–1 of comfortable wins (+10) edges out a 3–0 of three deuces (+9). A
3–0 where every game went to deuce genuinely *is* a closer session than winning
two games easily and dropping one, and the model is allowed to say so.

**Session length matters** (winning every game 11-7, against an equal):

| Games | Change |
|---|---|
| 1 | +6 |
| 3 | +17 |
| 5 | +28 |
| 10 | +55 |
| 20 | +110 |

**A 10-game session against an equal:**

| You won | Change |
|---|---|
| 10 of 10 | +55 |
| 8 of 10 | +33 |
| 7 of 10 | +22 |
| **5 of 10** | **0** |
| 3 of 10 | −22 |
| 0 of 10 | −55 |

**The same 3–0 `11-7 11-9 11-8`, against different opposition:**

| Opponent | You win | You lose 0–3 |
|---|---|---|
| 400 above you | **+29** | −2 |
| 200 above you | **+22** | −6 |
| level | **+13** | −13 |
| 200 below you | **+6** | −22 |
| 400 below you | **+2** | **−29** |

**The big upset** — a 1000 beating a 1400:

| | |
|---|---|
| 3–0 whitewash | **+58** |
| 3–0 normal | **+29** |
| 2–1 | **+28** |
| 7 of 10 games | **+83** |

### Doubles

The pair is rated at the **average** of the two partners, and both partners take
the **same** change.

The average is not the compromise here that it is in other sports: in table
tennis the pair **alternates strokes**, by rule, so each player really does play
half the balls. That is also what sets the discount — a doubles result is half
yours, so it counts at **half** K towards your overall rating.

On the **doubles ladder itself** it counts at ×0.8, not ×0.5. That board is a
ladder of how people play in pairs, so a doubles result is the whole of the
evidence rather than half of it; what's left of the discount is for the partner
you didn't choose.

> Alice (1200) and Ben (900) — a 1050 pair on paper.

| They beat | Each of them gets |
|---|---|
| two 1050s (par — exactly what's expected) | a little |
| two 1200s (an upset) | a lot |

Carrying a weaker partner past a pair you should beat is worth little; doing it
against a pair you shouldn't is worth plenty. Neither partner is punished for
who they were drawn with.

---

### Questions people ask

**I won and my rating went DOWN. Is that broken?**
No, and this is the one that surprises people. If you're rated 1400 and beat a
1000 by 2–1, you lose **5 points** — you were expected to take about 9 games in
10, and 2–1 is well short of that. Beating them 3–0 normally gains +2. Against
someone far below you, only a convincing win is worth anything, and a scrappy
one is evidence the gap isn't as wide as your rating claims.

**Can I farm a weak player to climb?**
Not really. Rated 1400 beating a 1000 3–0 gains **+2**. Then less. Then less
again — each win narrows the gap you have left to prove, and once you're ~750
ahead a win gains literally nothing. Grinding the ceiling out takes over a
thousand games, and every one of them drags your victim's rating down toward
you, closing the gap from the other side too. Meanwhile a single loss to them
costs you −29. And `/tt history` shows everyone the same two names over and over.

**Does playing more games get me more rating?**
Only if you keep winning them. More games means more movement in *whichever*
direction you earned — a 20-game session you lose 6–14 costs far more than a
3-game one. It cuts exactly as hard both ways.

**Is the total rating in the system conserved?**
Yes, exactly — the winner gains precisely what the loser drops, at any session
length, in singles and in doubles, whoever is playing. Every match sums to zero
and there is a test that says so. Nothing mints rating and nothing burns it,
which is what makes a 1200 today the same claim as a 1200 last month.

That is why the two sides share one stake rather than each bringing their own K
(see below). A player pinned on the rating floor is the other half of it: they
have nothing left to lose, so their opponent is trimmed to what was actually
paid rather than handed the difference.

**Why is a nail-biting 3–0 worth less than a comfortable 2–1?**
Because the points say the first session was closer. See the table above.

**What stops someone logging a result that never happened?**
They can't confirm their own session — only the other side can, and either
player can throw it out with one button. Ratings only move on a result someone
it *costs* has signed off on.

**Someone confirmed a typo. Now what?**
Whoever logged it runs `/tt undo`. That restores a snapshot of every player
taken just before the session, so it's exact. It's refused once any player in it
has played again — rewinding them would silently erase the later result too. At
that point, just play a correcting session.

**Can my rating go below zero?**
It floors at 100.

**Why don't I appear on the board?**
Six games to qualify. Before that you're in the *Still placing* line — your
rating exists and moves, it just isn't ranked yet.

### Changing the numbers

Every constant above is a named value at the top of [elo.py](elo.py) —
`START_RATING`, `K_NEW`, `K_SETTLED`, `K_DECAY`, `DOUBLES_K_FACTOR`,
`DOUBLES_OWN_K_FACTOR`, `MOV_BASELINE`, `MOV_GAIN`, `MOV_MIN`/`MOV_MAX`,
`UPSET_SCALE`, `RATING_FLOOR` — plus `PLACEMENT_GAMES` in [bot.py](bot.py).
Change one, run `pytest`, redeploy.

To apply a change to **matches already played**, run
`python scripts/recompute.py` — it replays every stored match in the order they
were applied and rewrites ratings, counters, undo snapshots and the weekly
figures as if the new numbers had always been in force. Dry run by default, and
it refuses outright if any match has aged out of history, since a replay on
partial history would be wrong rather than merely incomplete. It never touches
spins or settled bets.

Two knobs do most of the tuning:

- **`MOV_GAIN`** — how much the scoreline matters. At the current 1.0 a whitewash
  is worth ~2× a deuce-fest; at 1.5 it's ~2.9×; at 2.0, ~4.3×. It was 1.5, and
  that was steep enough to let one heavy loss outweigh two wins — see
  [Winning never costs you](#winning-never-costs-you).
- **`K_SETTLED`** — overall volatility once people have played. Everything
  scales with it.
- **`K_NEW`** and **`K_DECAY`** — how hard a newcomer's first games count, and
  over how many games that eases off. `K_DECAY` is the games for the gap between
  the two to shrink by 1/e, so half the journey is done in about `0.7 × K_DECAY`
  games.

---

## How it works

```
Slack ──▶ /slack/events ──▶ api/index.py (Flask on Vercel)
                                 │
                                 ├─▶ bot.py        /tt, the buttons, all the Slack text
                                 ├─▶ parsing.py    what someone typed → a match
                                 ├─▶ elo.py        the rating maths, pure functions
                                 ├─▶ store.py      players, pending queue, apply & undo
                                 ├─▶ kv.py         Upstash Redis REST — no SDK
                                 └─▶ standings.py  weekly post + the auto-confirm sweep
                                          ▲
                                   Vercel Cron ──┘
```

| File | Purpose |
|---|---|
| [elo.py](elo.py) | The rating maths. Pure functions, no I/O — everything above is here. |
| [parsing.py](parsing.py) | `/tt` grammar: mentions, the `vs` separator, scores, validation. |
| [store.py](store.py) | Persistence: players, the pending queue, applying a match, undo. |
| [bot.py](bot.py) | Slack handlers, the log form, message blocks, who may confirm. |
| [betting.py](betting.py) | Spins, fixtures, pools and settlement. No I/O beyond the store. |
| [page.py](page.py) | The public ladder page — pure rendering, no database. |
| [standings.py](standings.py) | Weekly standings post, payday, and the daily sweeps. |
| [kv.py](kv.py) | Minimal Upstash Redis REST client, with pipelining. |
| [api/index.py](api/index.py) | Vercel entry point; also serves `/debug` and `/cron/*`. |
| [socket_mode.py](socket_mode.py) | Socket Mode entry point for local dev (no public URL). |
| [manifest.yaml](manifest.yaml) | Slack app manifest (scopes, command, events, interactivity). |

**Two rules the rest of the code depends on**

1. **A match is rated when it's confirmed, never when it's typed.** Pending
   records hold players and scores only. Two matches confirmed out of the order
   they were logged would otherwise apply stale ratings.
2. **Every applied match stores a full before-snapshot of each player.** Undo
   restores those records verbatim rather than running the Elo backwards, which
   isn't invertible once a floor clamp or a streak is involved.

**Storage**

| Key | Type | Holds |
|---|---|---|
| `tt:players` | set | every registered uid |
| `tt:player:<uid>` | hash | rating + the counters behind `/tt me` |
| `tt:seq` | string | `INCR` — match and pending ids |
| `tt:pending` | set | ids awaiting confirmation (and the atomic claim) |
| `tt:pending:<id>` | string | JSON of an unrated match, 7-day TTL |
| `tt:match:<id>` | string | JSON of a rated match, including the undo snapshot |
| `tt:history` | list | applied match ids, newest first |
| `tt:hist:<uid>` | list | applied match ids that player was in |
| `tt:wk:<YYYY-Www>:delta` / `:played` | hash | this week's movement, for the weekly post |
| `tt:standings:posted` | set | weeks already announced |
| `tt:wallet` | hash | uid → spins |
| `tt:sched:<id>` | string | JSON of a fixture |
| `tt:sched:live` | set | fixtures not yet settled (and the settlement claim) |
| `tt:bets:<id>` | hash | uid → `side:amount` |
| `tt:ledger:<uid>` | list | recent wallet movements, for `/tt wallet` |
| `tt:stipend:paid` | set | weeks payday has run |

Races are handled with atomic claims rather than locks: `SADD` returning 1
registers a player exactly once, and `SREM` returning 1 means exactly one of two
people hitting **Confirm** at the same instant gets to rate the match.

---

## Setup

### 1. Slack app

1. <https://api.slack.com/apps> → **Create New App** → **From a manifest** → pick
   the workspace → paste [manifest.yaml](manifest.yaml).
   Leave the placeholder URLs for now; you'll come back once Vercel is live.
2. **Install to Workspace**, then copy:
   - **OAuth & Permissions** → *Bot User OAuth Token* → `SLACK_BOT_TOKEN` (`xoxb-…`)
   - **Basic Information** → *Signing Secret* → `SLACK_SIGNING_SECRET`
3. Get the channel id for the weekly post: open the channel in Slack → click its
   name → the id (`C…`) is at the bottom of the About tab. That's `TT_CHANNEL`.

### 2. Database

Vercel project → **Storage** → **Upstash for Redis** → Create. It sets
`KV_REST_API_URL` and `KV_REST_API_TOKEN` on the project for you. Using Upstash
directly instead, the `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` pair
works too. The free tier is far more than an office ladder needs.

### 3. Vercel

Import the repo, then set under **Settings → Environment Variables**:

| Variable | Needed for |
|---|---|
| `SLACK_BOT_TOKEN` | always |
| `SLACK_SIGNING_SECRET` | always — verifies requests really came from Slack |
| `KV_REST_API_URL` / `KV_REST_API_TOKEN` | always — set by the Upstash integration |
| `TT_CHANNEL` | the ladder's home channel — weekly standings land here, and joining it registers you |
| `CRON_SECRET` | authenticates `/cron/*`; Vercel sends it automatically once set |
| `TT_ADMINS` | optional — ids who can record a result without confirmation |
| `TT_PUBLIC_URL` | optional — your deployment URL, so the bot can link the ladder page |
| `TT_CHANNEL_NAME` | optional — e.g. `#table-tennis`, shown on the ladder page |

Deploy. `vercel.json` rewrites every path to `api/index.py` and registers both
cron jobs. **Environment variable changes need a redeploy to take effect.**

### 4. Point Slack at it

Back in the Slack app, replace the three placeholder URLs with your deployment:

- **Slash Commands** → `/tt` → `https://<your-app>.vercel.app/slack/events`
- **Interactivity & Shortcuts** → on → same URL
  (required — the Confirm buttons and the log form don't work without it)
- **Event Subscriptions** → on → same URL, and subscribe the bot to
  **`member_joined_channel`**
  (required for auto-registration; Slack verifies the URL when you save)

Then invite the bot wherever people will log matches: `/invite @tt-ranker`. With
`chat:write.public` it can post in public channels uninvited, but inviting it is
tidier and it's required in private channels.

Finally, run **`/tt sync`** in the channel to put everyone already there on the
ladder — auto-registration only catches people who join from now on.

> **Upgrading an existing install?** `channels:read`, `groups:read` and the
> `member_joined_channel` subscription were added after the first release.
> Slack does not grant new scopes to an app that's already installed — go to
> **OAuth & Permissions → Reinstall to Workspace**. Until you do, `/tt sync`
> reports a missing scope and nobody is auto-registered; everything else keeps
> working.

### 5. Check it

```
GET  https://<your-app>.vercel.app/               → "TT Ranker is running."
GET  https://<your-app>.vercel.app/debug          → what's configured, init status
GET  https://<your-app>.vercel.app/debug?ladder=1 → players, pending, cron history
```

Then in Slack: `/tt help`, `/tt register`, and log a match against a colleague.

---

## Running

**Vercel (production).** Push to the default branch. Two cron jobs are registered:

| Job | Schedule (UTC) | What |
|---|---|---|
| `/cron/sweep` | `30 3 * * *` daily | applies matches nobody confirmed in 24h |
| `/cron/standings` | `0 4 * * 1` Mondays | posts last week's ladder to `TT_CHANNEL` |

Both are safe to call by hand — the weekly post claims its week and the sweep
claims each match, so a retry can't double-post or double-rate. Add `?dry=1` to
either to see what it *would* do without doing it.

**Local (Socket Mode).** No public URL needed; enable Socket Mode on the app and
add an app-level token with `connections:write`.

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env     # fill it in
.venv/bin/python socket_mode.py
```

Behind a TLS-intercepting corporate proxy, local runs also need
`REQUESTS_CA_BUNDLE=vmock-ca.crt` — the proxy's CA is committed here for that.
(Vercel isn't behind it, so production needs nothing.)

**Tests.** 259 of them, no network, no database.

```sh
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`tests/fake_kv.py` fakes only the HTTP transport, so every test exercises the
real command construction, the real hash unflattening and the real pipelining.

## Notes

- `socket_mode.py` must **not** be renamed to `app.py` / `main.py` / `index.py` /
  `server.py` — Vercel's zero-config Python detection would serve it instead of
  `api/index.py`.
- The corporate TLS proxy re-signs certificates without an Authority Key
  Identifier, which Python 3.13+ rejects; `bot.build_app()` keeps full
  verification but clears `VERIFY_X509_STRICT`.
- The match message is posted with `chat_postMessage`, not the slash command's
  response URL, because a confirmation can arrive hours later and a response URL
  expires after 30 minutes.
- The sweep's real wait is between 24 and 48 hours, since cron runs daily. The
  message promises "auto-confirms in 24h", which is the half that matters — it
  will never apply *sooner* than the window.

---

## The ladder page

`https://<your-app>.vercel.app/ladder` — a live, public, read-only page. Put it in
the channel topic so people can check where they stand without running a command.

It answers one question, in this order: **did I move?** The rating is the loudest
thing on the page, this week's change sits beside it, and your row is reachable
without scrolling past a hero. Before anyone has qualified it counts down to the
first ranked player instead of showing an empty table.

No login and no secrets — it shows names and ratings, which everyone in the
channel can already see. It refreshes itself every minute, but only while the tab
is actually being looked at.

**Sessions.** Under the ladder, the recent results — and a filter bar to answer
"what did Bob play today?" Pick a player, tap *Today*, *Yesterday* or *This
week*, or choose a date; the two combine. The filters live in the address bar
(`/ladder?player=<uid>&day=today`), so a view can be pasted into the channel,
and they are plain links and a form — no script needed for them to work. The
same filters are in Slack: `/tt history @bob today`, `/tt history week`,
`/tt history 2026-09-16`. Days are read in IST, like everything else here.

**Whose league it is.** The VMock mark leads the bar, ahead of RALLY's own
wordmark, so a stranger opening the link can tell in one look that this is ours.

It is the only image on the site, and it is served from `/mark.png` rather than
inlined. Both would keep the page off the network in the sense that matters — no
CDN, no font, nothing third-party, nothing blocking first paint — but 3 KB of
base64 would ride along on every page of every request, and it would sit *inside*
the document, where a blob of base64 quietly contains almost any short string a
test asks about. So the bytes are served once, cached immutably, and the document
carries a nine-character path. The favicon goes out the same way, at
`/favicon.ico`, which browsers ask for on their own — which is how the document
still contains no `<link>` at all.

The asset is the official logo cropped to the badge, at 56px for a 28px slot. It
is a PNG because the official SVG is 100 KB with a raster embedded in it: the
texture inside that badge has no vector we have. See
[web/brand.py](web/brand.py) — if Brand ever hands over a true vector, that
module is the only thing that changes.
**Themes.** Five tables to play on: the blue tournament top it was drawn from,
a green one, a neutral *Slate*, a light *Daylight* for a bright desk or a
projector, and a near-black *Midnight* for a dim room. The picker is the swatch
in the top bar; the choice is kept in the browser, so it follows you around the
site but is yours alone — nothing about it is stored on the server or shared
with the channel. Someone who has never touched it gets the blue table, unless
their machine is set to a light appearance, in which case they get Daylight.

Adding a sixth is choosing eleven colours in [web/tokens.py](web/tokens.py) and
nothing else: everything derived from them — the tints behind chips, the
hairlines, the avatar colours, the bar's translucency — is worked out from those
eleven, and there is a test that the stylesheet names no colour of its own.
Every theme clears WCAG AA on body text, muted text and text on a filled
control, and that is asserted rather than eyeballed.

**Titles.** A rating says how good you are; it says nothing about who turned up
four nights running, who cannot lose at the moment, who cannot win at the moment,
or who has quietly built the biggest pile of spins. Those get names:

| Title | What it takes |
|---|---|
| **On Fire** | best win rate over the rolling seven days |
| **The Machine** | most matches played in those seven days |
| **Untouchable** | best win rate on the ladder, all time |
| **Moneybags** | the fattest wallet |
| **Ice Cold** | worst win rate over the seven days |

The weekly ones need 3 matches in the week before they'll rank you and the
all-time one needs 6 games — a title is a claim about quality, not about who
happened to play once. Level on win rate *and* on matches played and nobody holds
it: joint On Fire is not a thing anyone says. Nobody is ever both On Fire and Ice
Cold, which they otherwise would be in a week only one person qualified for.

A title isn't a section on one page — it follows the player. The chip appears on
the ladder rungs, the featured panel, the player cards, the match cards on both
sides, the profile, the compare page, and in Slack on `/tt me`.
[`/titles`](web/pages/titles.py) lists them all, including the ones going spare,
and `/tt titles` says the same in the channel.

**Nothing about a title is stored.** Every one is recomputed from matches and
player records, so there's nothing to migrate, nothing to backfill, and no way
for a title to drift out of step with the ladder it came from. What *is* stored
is the answer, for five minutes: the weekly figures need a walk over the week's
matches and no page should pay for that per request. Applying or undoing a match
drops the cache in the same pipeline that writes the result, so a title never
survives the match that took it away.
**A player's own page.** `/player/<uid>` — their rating line per format, their
record, their head-to-head against whoever they've played most, their matches,
and **Turning up**: a square per day, darker the more they played, the way a
contributions graph reads.

The graph is drawn from the oldest session still on record rather than from a
fixed year ago, because a player's history is trimmed to the last
`PLAYER_HISTORY_LIMIT` matches. Every square on it is then a day we genuinely
know about — an empty one means nobody played, never "that was thrown away", and
the note above it says exactly what it covers. No chart library and no canvas: a
heatmap is a table of squares and CSS already draws those, which is also what
keeps the page making zero external requests. Every square carries its date and
its count in words, so the graph is readable without seeing a single shade.

**And a name goes to the person it names.** The ladder rungs, the featured
panel, the still-placing list, the spins board, both sides of every match card,
the player grid, the stats leaders and the compare tray all link to that page,
through one helper — so nobody's name is a dead end on one page and a link on
the next. The format tab you're reading travels with you
(`/player/<uid>?view=doubles`) rather than dumping you back on Singles.

**Releases.** The footer of every page says which build you're looking at —
a date and a name, linked to [`/releases`](web/pages/releases.py), which is what
changed and when. One entry per major change, which in practice means per pull
request; a bug fix nobody noticed doesn't get one. If a change didn't alter what
you see or what your rating does, it isn't there.

Dated rather than numbered: a version number implies a promise about
compatibility that an office ladder doesn't make, and a date answers the question
people actually have. The notes live in [releases.py](releases.py) as data and
ship with the code, because the page makes no external requests and can't fetch
them. Adding one is prepending a `Release(...)`; the footer follows the top of
the list on its own, and a test holds the two together.

It is in the footer rather than the top bar on purpose — a page you read once
when you notice something is different, not one you check.

**Names.** The page can't render a Slack mention, so it needs something to call
people. Three tiers, best first:

1. what they set with `/tt name Sagnik`
2. the Slack handle their slash commands revealed
3. the tail of their user id — a stub, and a visible prompt to set one

`/tt nudge` (admins only) DMs everyone still on tier 2 or 3. New players are
asked when they join.

Most people never get round to setting their own, so an admin can do it for
them: `/tt name @bob Bob Smith`. The player is DM'd that it happened and how to
change it — a name is how you're shown to the whole office, and a leaderboard is
no way to find out it changed.

**`/tt who`** goes the other way. The page can't render a Slack mention, so it
shows chosen names and a reader has no way back from *ChumChum* to a person:

```
/tt who ChumChum   →  ChumChum is @bob
/tt who chum       →  same — case-insensitive, partial matches count
/tt who @bob       →  @bob is ChumChum on the ladder
/tt who            →  everyone, names first
```

Matching is tiered — exact, then prefix, then substring — so *Ram* doesn't lose
to *Ramesh*, which is precisely when you need the lookup.


---

## Betting

Fixtures can be scheduled, and the channel bets on them in **spins** — play
money, no real stakes.

```
/tt schedule                   →  a form: players, and a start time
/tt schedule @bob 6pm          →  or type it
/tt book                       →  what's open
/tt wallet                     →  your balance and recent moves
/tt bet 12 a 50                →  the typed route; the buttons are the usual one
```

The form uses a native **date-and-time picker** rather than a text box. `6pm` has
to be parsed, guessed at across midnight and echoed back to be checked; a picker
is unambiguous the moment it's set. It defaults to an hour out, rounded up to
the next quarter.

```
┌─ Schedule a match ────────────────────────┐
│  Your side        [ @you            ▾ ]   │
│  Add a partner for doubles.               │
│                                           │
│  Opponents        [ @bob            ▾ ]   │
│                                           │
│  First serve      [ 17 Sep  18:00     ]   │
│  Betting shuts at this moment — until     │
│  then anyone in the channel can back      │
│  either side.                             │
│                                           │
│  Put the fixture in   [ #table-tennis ▾ ] │  ← shortcuts menu only
│                                           │
│                   [ Cancel ]  [ Put it up]│
└───────────────────────────────────────────┘
```

The fixture message carries a **Back _____** button for each side. Unlike a
match verdict, those buttons belong in the channel: anyone may bet, and only the
players may rule on a result.

### How a pot pays

**Pari-mutuel** — every stake goes into one pot, and whoever backed the winner
splits it in proportion to what they staked.

```
💰 11,120 spins in the pot
danger — 1,120 spins · pays 9.93×
   Deepanshu 1,020 · Praneat 50 · danger 50
ChumChum — 10,000 spins · pays 1.11×
   KK 5,000 · Akchansh 4,000 · Shashank 900 · ChumChum 100
```

Backers are **named, not counted**. On a ladder this size who backed you is most
of the point, and it's also what turns an odd-looking stake into something the
room notices rather than something only the database knows.

`/tt book 6` gives one fixture in full — every stake and what it would return —
for once the message has scrolled away.

Nobody is the bookmaker, so **no spin is ever created or destroyed by betting**.
Everything paid out came from someone else's stake. That's asserted directly:
the test suite runs whole fixtures across every split, winner and rounding case
and checks the total supply is unchanged to the last spin. Floored shares would
quietly burn a few, so the rounding remainder goes to the largest winning stake.

The consequence worth knowing: backing the obvious favourite pays least,
because everyone else did too.

| Situation | What happens |
|---|---|
| Draw | Every stake refunded |
| Nobody backed the winner | Every stake refunded |
| Everyone backed the winner | Everyone gets their own stake back |
| Nobody logs the result within 48h | Fixture voided, every stake refunded |
| Called off (players, organiser or an admin) | Every stake refunded |

### The window

It shuts the moment the match is due to start. That's enforced when a bet is
placed, not by the cron — crons run daily, so a window left open because nothing
had swept yet would let people bet on a match already under way. The daily sweep
only tidies the message afterwards.

The resolved start time is always echoed back (`today 18:00`, `tomorrow 09:00`),
so `/tt schedule @bob 9am` typed in the evening visibly means tomorrow morning
rather than silently meaning it.

### Spins

| | |
|---|---|
| Everyone starts with | **5,000** |
| Top-ups | **1,000 a week**, every player — `WEEKLY_STIPEND` |
| Smallest stake | **5** |

A wallet can never go negative — stakes leave when the bet is placed and
settlement only ever credits.

**Nothing mints spins.** The supply is fixed at what everyone opened with, so a
spin won is a spin somebody else lost and the currency is worth something.
Betting and transfers are both zero-sum, and there's a test that says so.

Which also makes a wallet balance a real standing. **`/tt rich`** ranks every
wallet, richest first, with how far each has moved from the 5,000 it opened
with, and the same table sits on the ladder page under *Spins* once anyone has
moved. Players who never placed a bet are ranked at 5,000 rather than left off
— that is what their wallet would hold the moment it opened.

Busting out used to be permanent until an admin moved some across with
`/tt transfer`, and people did bust out. So every player is now topped up by
`WEEKLY_STIPEND` at the start of each week — both cron jobs pay it, claimed once
a week so it can't be paid twice. Losing everything costs you a week, not the
game. Set the constant to zero in [betting.py](betting.py) to close the tap
again and make the pool finite.

### Moving spins

`/tt transfer @bob 500` moves spins out of your own wallet;
`/tt transfer @alice @bob 500` moves them between two other people. **Admins
only** — a wallet you didn't agree to empty isn't something any player should be
able to reach.

Both forms are **zero-sum**: a debit and a credit of the same size, so the
Monday stipend is still the only thing in the system that mints. An admin
handing out a prize is giving away their own spins, not printing new ones.

Everyone whose balance moved is DM'd, and a move made by a third party says so
in both ledgers — `/tt wallet` can always answer *where did that come from*.

### Challenging someone

`/tt schedule` states a fact — it's happening, back it if you like. A challenge
is the step before that, where the other person still gets a say:

Two ways in, same challenge: **`/tt challenge`** on its own opens a form, or the
**shortcuts menu** → *Challenge someone to table tennis*. Or type it:

```
/tt challenge @bob best of 5          # bo7, first to 3, 5 games, 4 matches
/tt challenge @bob 5 games at 6pm     # a time, if you want one
/tt challenge @partner vs @dan @eve   # doubles, same vs rule as logging
```

```
┌─ Challenge someone ───────────────────────┐
│  Your side        [ @you            ▾ ]   │
│  Add a partner for doubles.               │
│                                           │
│  Who you're calling out                   │
│                   [ @bob            ▾ ]   │
│                                           │
│  How long    [ Best of 5 — first to 3 ▾ ] │
│  Agreed up front, so it isn't an          │
│  argument afterwards.                     │
│                                           │
│  Start time (optional)   [           ▾ ]  │
│  Leave it out and it starts shortly        │
│  after they accept.                       │
│                                           │
│               [ Cancel ]  [ Call them out ]│
└───────────────────────────────────────────┘
```

The length is a **menu** rather than a text box — it's the one field with a
small, known set of right answers, and picking from them means nobody has to
learn that `bo5` is a thing the bot understands. Every option is labelled with
the same phrase the challenge, the DM and the fixture all use, so the menu can't
promise *Best of 5* and post something else.

The start time is **genuinely optional here**, unlike the schedule form: a
required picker would turn every challenge into a commitment nobody made.

**The length is the other half of the invitation.** "Play me" and "play me, best
of five" are different questions, and the second is the one people argue about
afterwards — so it's agreed up front and both sides see it before anyone walks
to the table. `best of 5` means first to 3; `first to 3` means up to 5 games;
`5 games` means five games with nobody stopping early. Left out, it's a
best-of-three, which is about twenty minutes.

**Both ratings are on it**, along with who that makes the favourite — the same
expectation `/tt odds` reports, said at the moment people care about it most:

```
⚔️ @harsh 1177
   challenges
   @danger 958
   Best of 5 — first to 3
   @harsh favoured — 78% on the ratings.
```

**The buttons go by DM, not to the channel** — the same rule as confirming a
result. The channel sees the callout and who owes an answer; **Accept** and
**Not today** go to the people being challenged, and the challenger gets **Take
it back**. A challenge nobody answers expires after 24 hours, and only one can
stand between the same two sides at a time, so a pair can't stack up five
identical invitations.

**Accepting puts up an ordinary fixture** — so betting, moving it and calling it
off are all the machinery that already exists, and a challenge never becomes a
second kind of scheduled match to keep in step. If a time was agreed it's kept;
if it went by while the challenge sat unanswered, the fixture starts shortly
after the yes rather than opening already due.

The agreed length is **a statement of intent, not a constraint**. It rides along
onto the fixture, but `/tt log` still takes whatever was really played — a
best-of-five that stopped at 2-0 is logged as two games. Enforcing it would mean
rejecting true results to protect a plan, which is the wrong way round.

### The wall of shame

`/tt shame`. Four things go on it:

| | |
|---|---|
| :wastebasket: **Thrown out** | results they pressed *That's wrong* on |
| :turtle: **Ducked** | challenges they turned down |
| :ghost: **Ghosted** | challenges they never answered at all |
| :no_entry_sign: **Bailed** | fixtures called off, or left without a result |

**Counted as it happens, never derived.** Most of these destroy the record they
happened to — throwing a result out deletes its pending record, which is the
point of throwing it out, and a challenge ages out of Redis within the week. So
each bumps a counter at the moment it happens and the counter *is* the record.
A miscount can only be undone with `shame.clear()`, since there is no history to
replay it from.

A few things deliberately don't count. Taking back **your own** logged result is
cancelling your own typo, not refusing somebody else's. **Withdrawing** your own
challenge isn't ducking one. And an **open call** nobody takes shames nobody —
it was addressed to the channel, so nobody was asked and nobody ignored it.

**A caveat worth keeping in view.** Throwing out a wrong scoreline is the
integrity model working — it is the only thing standing between the ladder and
whatever anybody feels like typing. A board that shames people for pressing
*That's wrong* pushes them toward confirming results they believe are wrong, and
that is a worse problem than the one the board is for. So the wall says out loud
that it is a joke, and the honest move if it ever stops reading as one is to
drop the *Thrown out* column — or the board — rather than to keep score more
quietly.

### Winning pays

Take a session and the spins follow, scaled to how convincing it was — by
**games**, because that's what *close* and *wipeout* mean to whoever played it:

| Won by | | Pays |
|---|---|---|
| 1 game | 2–1, 3–2, 1–0 | **5 spins** |
| 2 games | 2–0, 4–2 | **10 spins** |
| 3 or more | 3–0, 4–1 | **20 spins** |

A drawn session pays nobody. **Both of a winning pair are paid in full** rather
than splitting one prize — halving it for doubles would make the sensible move
"play singles for the money". The result message says what it paid.

It's paid on every route a match can be rated by — a confirmation, an admin
logging their own, and the sweep applying one nobody answered — because all
three go through one payout. `/tt undo` takes it back with the rating; the prize
is a pure function of the scoreline, so it reverses exactly without anything
having been written down when it was paid. A `recompute` deliberately doesn't
touch it: replaying ratings is not a reason to reach into wallets.

**This mints, and that's new.** The weekly stipend used to be the only thing
that created spins; there are now two, and everything else — every bet, every
settlement, every transfer — is still strictly zero-sum. The prize is small on
purpose: a whole week of matches, every one of them a 3–0, pays out under a
tenth of one week's stipend. `WIN_PRIZE` in [betting.py](betting.py) is the dial
if the pool ever starts outrunning what a wallet is supposed to mean.

### Running late

`/tt reschedule 6 7pm`, or press **Move it** on the fixture. The players,
whoever set it up, and admins can all do it — the same people who can call it
off.

**Every stake stands.** The bet was on who wins, not on when they played, so
moving the time keeps the pool. Before this the only way to shift a match was to
call it off and put it up again, which hands all the money back and loses the
betting the fixture had already attracted.

**A window that has already shut stays shut.** If the original start time has
passed, the match may have begun — and someone who watched two games of it knows
something the pool doesn't. Reopening betting on the strength of a postponement
is the one way this could be used to steal spins, so a closed fixture moves its
time and keeps its pool frozen at whatever was in it. An open one stays open and
keeps taking bets until the *new* start time. The channel is told which of the
two happened, rather than left to work it out.

A moved fixture is also abandoned from its **new** time, so the daily sweep
can't refund a match that has been postponed into the future because the old
time was long enough ago.

Changing *who is playing* isn't offered. That's a different match with the same
pot sitting on it — call it off and put the right one up.

### Betting on your own match

Allowed, including against yourself. That's a deliberate house rule, so the only
guard is daylight: if a player backs the side they aren't playing for, the
fixture message names them and the amount.

Worth being aware of what that permits — the result is self-reported, so
someone can profit from a game whose score they also type in. The office is
expected to police that, which is exactly what the visibility is for.

