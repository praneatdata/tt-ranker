"""What changed, in words a player understands.

Release notes, not a commit log. "Your first games now move you harder" is a
note; "refactor session_k to take length" is not, and a generated list of commit
subjects would be worse than nothing — most commits are invisible from the table.

**One entry per major change, which in practice means per pull request.** Not
every PR earns one: a bug fix nobody noticed, a tidy-up or a test does not change
what anybody sees. The `prs` field says which ones an entry was, so a note can
always be traced back to the thing that did it — as plain numbers, because the
page is not allowed to contain a URL.

**Dates, not semver.** A version number implies a contract about compatibility
that an office ladder does not have. A date and a name is what people actually
want — "am I looking at the new one?" — and needs no ceremony to keep true.

Newest first. `CURRENT` is whatever is at the top, which is what the footer
shows; there is a test that the two cannot disagree.
"""
from collections import namedtuple

Release = namedtuple("Release", "date name summary changes prs")

RELEASES = (
    Release(
        "2026-09-22", "Winning pays, and a wall of shame",
        "Spins for taking a session, and a board for everyone who wouldn't play.",
        (
            "Win a session and the spins follow: 5 for a close one, 10 for a "
            "decent win, 20 for a wipeout. Scaled by games — 2-1 is close, 2-0 "
            "decent, 3-0 a wipeout. A draw pays nobody.",
            "Both of a winning pair are paid in full, not half each.",
            "`/tt shame` — results thrown out, challenges ducked, challenges "
            "ghosted, fixtures bailed on. It's a joke, and it says so.",
            "Taking back your own logged result doesn't count against you, and "
            "an open call nobody takes shames nobody — it was addressed to the "
            "channel, so nobody was asked.",
        ),
        (),
    ),
    Release(
        "2026-09-22", "Winning never costs you",
        "Win the session and your rating can't go down. Lose it and it can't go up.",
        (
            "Match #77 found it: two games won of three against a higher-rated "
            "pair, and the winners each lost a point. The scorelines were "
            "outweighing the result instead of adjusting it.",
            "The margin curve is flatter now. A 21-18 and a 25-23 used to count "
            "the same — both bottomed out — while a 10-21 loss counted three "
            "times either. A whitewash is still worth about twice a deuce-fest.",
            "Where the scorelines point the other way from the result, the "
            "session is now scored as a draw and nobody moves at all.",
            "The trade: scraping a 2-1 past somebody far below you used to cost "
            "rating, and is now simply worth nothing.",
        ),
        (),
    ),
    Release(
        "2026-09-22", "Open calls",
        "Call out a level rather than a person, and let the channel answer.",
        (
            "`/tt challenge open ±100 bo5` — anyone rated near you can take it, "
            "first come. Also an explicit range, `1100-1250`, or `+150` for "
            "anyone above you.",
            "Doubles brings a pair each side: you name yours when you post it, "
            "whoever takes it names theirs, and the pair is judged on the "
            "average of the two ratings.",
            "The band is checked when somebody presses, not when the call went "
            "up — people drift, and the honest question is whether you are a "
            "fair match now.",
            "An open call is nobody's to turn down: leave it for somebody else, "
            "or `/tt withdraw` it if it is yours.",
        ),
        (23,),
    ),
    Release(
        "2026-09-22", "Every command, and a guess when you mistype one",
        "`/tt help` is the whole list now, and a typo gets a suggestion.",
        (
            "Every command, grouped by what you are trying to do. It used to "
            "list about two thirds of them with no way of noticing.",
            "`/tt boad` answers *did you mean `/tt board`* instead of printing "
            "the manual at you — and says nothing when nothing is close.",
            "Admin commands are listed only for admins.",
        ),
        (21,),
    ),
    Release(
        "2026-09-22", "Release notes",
        "This page, and a line in every footer saying what you are looking at.",
        (
            "What changed and when, newest first — written for players rather "
            "than generated from commits.",
            "The footer of every page names the current release and links here.",
        ),
        (22,),
    ),
    Release(
        "2026-09-18", "Closed books",
        "Every match conserves now: whatever one side gains, the other loses.",
        (
            "Ratings drifted upward before this. A newcomer beating a settled "
            "player gained more than their opponent lost, and the difference was "
            "invented — about eighty-five points on a 3–0.",
            "Both sides of a match now play for one shared stake, so nothing "
            "mints rating and nothing burns it.",
            "A player on the rating floor has nothing left to lose, so their "
            "opponent is no longer handed it.",
        ),
        (17,),
    ),
    Release(
        "2026-09-18", "Challenges",
        "Call someone out, agree how long it runs, and let them answer.",
        (
            "`/tt challenge @bob best of 5` — or bare, for a form. Also `bo7`, "
            "`first to 3`, and `at 6pm` if you want a time.",
            "The length is what you agreed, not a rule: log whatever was really "
            "played and nothing argues with you.",
            "Accepting turns it into an ordinary fixture, so betting and "
            "`/tt reschedule` work on it exactly as they already did.",
        ),
        (),
    ),
    Release(
        "2026-09-18", "Turning up",
        "A player page worth visiting, and a way to reach it.",
        (
            "A contributions graph on every player's page: a square per day, "
            "darker the more they played.",
            "Names are links now — on the ladder, in match cards, on the players "
            "grid, in the stats — so a name is no longer a dead end.",
        ),
        (15,),
    ),
    Release(
        "2026-09-18", "Titles",
        "Five things to hold besides a rating.",
        (
            "On Fire, The Machine, Untouchable, Moneybags and Ice Cold. Each is "
            "worked out from the results and none of them is stored.",
            "A title follows you wherever your name appears, and the Titles tab "
            "lists them all — including the ones going spare.",
        ),
        (14,),
    ),
    Release(
        "2026-09-18", "A real calibration curve",
        "Your first games move you much harder than they used to.",
        (
            "K decays smoothly from 55 to 13 instead of stepping from 16 to 11 "
            "after fifty games, so a newcomer reaches their level in a dozen "
            "games rather than forty.",
            "Counted per format: settled at singles still means new at doubles.",
            "No cliff anywhere. Under the old rule your 49th game moved you 45% "
            "further than your 51st.",
        ),
        (13,),
    ),
    Release(
        "2026-09-18", "A table to play on",
        "The site picked a look, and said whose league it is.",
        (
            "Five colour themes — blue, green, Slate, Daylight and Midnight — "
            "with a picker in the bar. Your choice is yours alone.",
            "The VMock mark leads the bar.",
        ),
        (11, 12),
    ),
    Release(
        "2026-09-17", "Spins, and a ladder that filters",
        "Play money to bet with, and a way to find one person's matches.",
        (
            "`/tt rich` ranks every wallet, and the ladder page gained a Spins "
            "board.",
            "Filter the session list by player and by day, on the page and in "
            "`/tt history @bob today`.",
            "Singles and doubles each got their own ladder and their own rating.",
        ),
        (3, 4),
    ),
    Release(
        "2026-09-16", "The ladder",
        "Where it started: Elo for the office table, run from Slack.",
        (
            "`/tt log` a session, your opponent confirms it, both ratings move.",
            "Every game is rated on its own, so a long session counts for more "
            "than a short one.",
            "A public page to put in the channel topic.",
        ),
        (),
    ),
)

CURRENT = RELEASES[0]


def current_label():
    """What the footer says: the date and name of the newest release."""
    return f"{CURRENT.date} · {CURRENT.name}"
