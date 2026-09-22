"""
Turning what someone typed into `/tt` into a match — text in, structure out.

Grammar, informally:

    /tt log  @bob  11-7 9-11 11-5                   singles, you vs Bob
    /tt log  @partner vs @dan @eve  11-7 11-9       doubles, you+partner named first
    /tt log  @a @b vs @c @d  11-7 11-9              anyone can record a match
    /tt log  @bob  11-7                             one game is a match too

`vs` splits the sides. Without it every mention is the opposition and you are
side A, which makes the common case — logging your own singles game — as short
as it can be. With it, if you never named yourself and your side is short one
player, you are added to it: `@partner vs @dan @eve` means what it reads like.

Everything raises ParseError with a message meant for the player, because nearly
every way this fails has its own fix and one generic usage dump helps nobody.
"""
import re
from datetime import date, timedelta

import elo

# Slack sends "<@U123>" or "<@U123|name>" for a mention; W-prefixed IDs are org users.
MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
# Three digits so an obvious typo ("11-100") is caught by the range check and
# explained, rather than silently not looking like a score at all.
SCORE_RE = re.compile(r"(\d{1,3})[-–—:](\d{1,3})")
VS_RE = re.compile(r"(?:vs?|versus|x)\.?", re.IGNORECASE)
# "11 - 7" and "11 : 7" mean "11-7". Both sides must be digits, which no Slack
# mention token contains around a separator, so mentions pass through untouched.
SPACED_SCORE_RE = re.compile(r"(\d)\s*[-–—:]\s*(\d)")

_TRIM = ".,;!?()[]"

SUBCOMMANDS = {
    # The words people reach for when they want the list — all of them land on
    # help, which is where the list lives.
    "commands": "help", "cmds": "help", "cheatsheet": "help", "quick": "help",
    "usage": "help",
    "log": "log", "add": "log", "result": "log", "played": "log",
    "score": "log", "record": "log", "beat": "log", "lost": "log",
    "register": "register", "join": "register", "signup": "register",
    "me": "me", "card": "me", "stats": "me", "profile": "me", "rating": "me",
    "board": "board", "leaderboard": "board", "top": "board", "rank": "board",
    "standings": "board", "ladder": "board",
    "history": "history", "recent": "history", "log-history": "history",
    "undo": "undo", "oops": "undo",
    "edit": "edit", "fix": "edit", "correct": "edit", "amend": "edit",
    "pending": "pending", "unconfirmed": "pending",
    "odds": "odds", "predict": "odds", "chance": "odds",
    "sync": "sync", "backfill": "sync",
    "intro": "intro", "welcome": "intro", "rules": "intro", "howto": "intro",
    "name": "name", "callme": "name", "rename": "name",
    "who": "who", "whois": "who", "lookup": "who", "find": "who",
    "nudge": "nudge", "askall": "nudge",
    "schedule": "schedule", "sched": "schedule", "fixture": "schedule",
    "challenge": "challenge", "chal": "challenge", "callout": "challenge",
    "vs": "challenge",
    "reschedule": "reschedule", "move": "reschedule", "postpone": "reschedule",
    "delay": "reschedule", "resched": "reschedule",
    "bet": "bet", "stake": "bet", "back": "bet",
    "accept": "accept", "yes": "accept", "on": "accept",
    "decline": "decline", "nope": "decline", "no": "decline",
    "challenges": "challenges", "callouts": "challenges",
    "shame": "shame", "wall": "shame", "hall-of-shame": "shame",
    "naughty": "shame",
    # An open call carries no DM, so its buttons aren't anywhere — taking one
    # back has to be sayable.
    "withdraw": "withdraw", "takeback": "withdraw", "unchallenge": "withdraw",
    "wallet": "wallet", "balance": "wallet", "spins": "wallet", "purse": "wallet",
    "rich": "rich", "richest": "rich", "wallets": "rich", "moneyboard": "rich",
    "titles": "titles", "title": "titles", "badges": "titles", "awards": "titles",
    "book": "book", "bets": "book", "fixtures": "book", "upcoming": "book",
    "transfer": "transfer", "pay": "transfer", "send": "transfer", "give": "transfer",
    # `form` and a bare `log` both open the guided modal.
    "form": "log", "new": "log",
    "help": "help", "h": "help", "usage": "help",
}


class ParseError(ValueError):
    """A problem worth showing the player verbatim."""


def mentions_in(text, exclude=None):
    """Mentioned user IDs, in order, deduped, minus the bot itself — @-ing the
    bot while logging a match is a mention of a player who wasn't on the table."""
    seen = [uid for uid in MENTION_RE.findall(text or "") if uid != exclude]
    return list(dict.fromkeys(seen))


# --- days ------------------------------------------------------------------

DAY_WORDS = {"today": 0, "yesterday": 1, "week": 7, "thisweek": 7, "this-week": 7}
_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DMY_DAY = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$")


def iso_day(text, now):
    """The ISO date a day expression resolves to, or "" for a range like `week`.

    `<input type="date">` only accepts YYYY-MM-DD, so echoing `16/9` straight
    back leaves the picker blank while the view is filtered — the page saying it
    isn't doing the thing it is doing.
    """
    window = parse_day(text, now)
    if not window:
        return ""
    _, start, end = window
    return start.strftime("%Y-%m-%d") if (end - start) == timedelta(days=1) else ""


def parse_day(text, now):
    """One day (or the week) named in a command → (label, start, end), or None.

    Understands `today`, `yesterday`, `week`, an ISO date `2026-09-16`, and
    `16/9` or `16/09/2026` — the words people actually type, without becoming a
    date library. Bounds are half-open [start, end) at midnight in whatever
    zone `now` carries, so a 23:59 match lands on the right side. `week` is the
    last seven days ending now, not the ISO week: "what happened this week" is a
    rolling question, and the weekly post already covers calendar weeks.
    """
    word = (text or "").strip().lower().replace("this week", "thisweek")
    if not word:
        return None
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if word in DAY_WORDS:
        back = DAY_WORDS[word]
        if back == 7:
            return "this week", midnight - timedelta(days=6), midnight + timedelta(days=1)
        start = midnight - timedelta(days=back)
        return word, start, start + timedelta(days=1)
    day = _one_day(word, now)
    if day is None:
        return None
    start = midnight.replace(year=day.year, month=day.month, day=day.day)
    if start == midnight:
        label = "today"
    elif start == midnight - timedelta(days=1):
        label = "yesterday"
    else:
        label = f"{start.day} {start.strftime('%b')}" + \
            ("" if start.year == now.year else f" {start.year}")
    return label, start, start + timedelta(days=1)


def _one_day(word, now):
    m = _ISO_DAY.match(word)
    if m:
        year, month, day = (int(g) for g in m.groups())
    else:
        m = _DMY_DAY.match(word)
        if not m:
            return None
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def split_day(text):
    """(day word, rest) — pull a day out of a command's tail, wherever it sits,
    so `history @bob today` and `history today @bob` both read. Only whole
    tokens: a score like `11-7` is never mistaken for a date."""
    # Two-word "this week" first, so the bare `week` token below doesn't leave
    # a stray `this` behind in the rest.
    text = re.sub(r"(?i)\bthis week\b", "thisweek", text or "")
    kept, found = [], ""
    for token in text.split():
        low = token.lower()
        if not found and (low in DAY_WORDS or _ISO_DAY.match(low) or _DMY_DAY.match(low)):
            found = low
        else:
            kept.append(token)
    return found, " ".join(kept)


def split_subcommand(text):
    """('log', 'rest of the text') — the leading verb and what follows.

    An unrecognised first word is not an error: `/tt @bob 11-7` is what people
    type once they know the bot, so anything carrying game scores is a log.
    """
    text = (text or "").strip()
    if not text:
        return "help", ""
    first, _, rest = text.partition(" ")
    key = first.strip(_TRIM).lower()
    if key in SUBCOMMANDS:
        return SUBCOMMANDS[key], rest.strip()
    return ("log" if SCORE_RE.search(_normalize(text)) else "help"), text


def unknown_verb(text):
    """The first word of a command nothing recognises, or "" when there is
    nothing to correct.

    Empty is not a typo, a known alias is not a typo, and anything carrying a
    scoreline is a log rather than a misspelling — `/tt @bob 11-7` is what
    people type once they know the bot. What is left is somebody who meant
    something and missed, which is worth answering with a guess instead of the
    whole manual.
    """
    text = (text or "").strip()
    if not text:
        return ""
    first, _, _ = text.partition(" ")
    key = first.strip(_TRIM).lower()
    if not key or key in SUBCOMMANDS:
        return ""
    if SCORE_RE.search(_normalize(text)):
        return ""
    return key


# Close enough to be a typo of it rather than a different word. Tuned up from
# difflib's 0.6 default, which pairs `histry` with `commands` and helps nobody.
SUGGEST_CUTOFF = 0.72


def suggest(word, limit=2):
    """The commands `word` was most likely meant to be, best first, or [].

    Matched against every alias — somebody typing `leaderbord` is reaching for
    `leaderboard`, and telling them about `board` is the useful answer — then
    folded onto canonical names, because offering four spellings of one command
    is not a shortlist.

    Returning nothing is a real answer. A wrong guess is worse than no guess:
    it sends someone off to read about a command they never wanted.
    """
    import difflib
    key = (word or "").strip(_TRIM).lower()
    if not key:
        return []
    close = difflib.get_close_matches(key, SUBCOMMANDS, n=8,
                                      cutoff=SUGGEST_CUTOFF)
    # An abbreviation scores badly and reads obviously: `chal` is four letters
    # of one command and nothing else. Only when it is unambiguous, though.
    if not close:
        prefixed = [a for a in sorted(SUBCOMMANDS) if a.startswith(key)]
        if len({SUBCOMMANDS[a] for a in prefixed}) == 1:
            close = prefixed
    out = []
    for alias in close:
        name = SUBCOMMANDS[alias]
        if name not in out:
            out.append(name)
    return out[:limit]


def _normalize(text):
    return SPACED_SCORE_RE.sub(r"\1-\2", text or "")


def _tokenize(text, exclude=None):
    """[(kind, value), …] where kind is 'mention' | 'vs' | 'score' | 'other'."""
    out = []
    for raw in _normalize(text).split():
        uids = [u for u in MENTION_RE.findall(raw) if u != exclude]
        if MENTION_RE.search(raw):
            out += [("mention", u) for u in uids]
            continue
        tok = raw.strip(_TRIM)
        m = SCORE_RE.fullmatch(tok)
        if m:
            out.append(("score", (int(m.group(1)), int(m.group(2)))))
        elif VS_RE.fullmatch(tok):
            out.append(("vs", None))
        elif tok:
            out.append(("other", tok))
    return out


def _sides(tokens, caller):
    """Mentions → (side_a, side_b), applying the `vs` rules. Not validated yet."""
    has_vs = any(kind == "vs" for kind, _ in tokens)
    side_a, side_b = [], []
    target = side_a if has_vs else side_b
    for kind, value in tokens:
        if kind == "vs":
            target = side_b
        elif kind == "mention":
            target.append(value)

    # Slack's autocomplete makes a double @mention easy; within one side that is
    # plainly a slip. The same name on *both* sides is a real mistake, so that
    # one is left for validate_sides to reject.
    side_a, side_b = list(dict.fromkeys(side_a)), list(dict.fromkeys(side_b))

    if not has_vs:
        # No separator: everyone named is the opposition and you are side A.
        side_a = [caller] if caller else []
    elif caller and caller not in side_a + side_b and len(side_a) < len(side_b):
        # "@partner vs @dan @eve" — you left yourself out of a side you're on.
        side_a.insert(0, caller)
    return side_a, side_b


def parse_match(text, caller=None, bot_id=None):
    """Text after `/tt log` → {"side_a": [uid…], "side_b": [uid…], "games": [(a,b)…]}.

    Raises ParseError, already phrased for the player, on anything unusable.
    """
    tokens = _tokenize(text, exclude=bot_id)
    side_a, side_b = _sides(tokens, caller)
    games = [v for kind, v in tokens if kind == "score"]
    validate_sides(side_a, side_b)
    validate_games(games)
    return {"side_a": side_a, "side_b": side_b, "games": normalise_games(games)}


def validate_sides(side_a, side_b):
    if not side_a or not side_b:
        raise ParseError(
            "I need to know who played. Try `/tt log @opponent 11-7 9-11 11-5`, "
            "or `/tt log @partner vs @dan @eve 11-7 11-9` for doubles."
        )
    everyone = side_a + side_b
    if len(set(everyone)) != len(everyone):
        raise ParseError("Someone is on both sides (or listed twice) — check the @mentions.")
    if len(side_a) != len(side_b):
        raise ParseError(
            f"Uneven sides: {len(side_a)} v {len(side_b)}. Use `vs` to split them — "
            "`/tt log @partner vs @dan @eve 11-7 11-9`."
        )
    if len(side_a) > 2:
        raise ParseError("Singles and doubles only — that's more than two a side.")


def validate_games(games):
    if not games:
        raise ParseError(
            "No game scores found. Add them as points, one per game: "
            "`/tt log @opponent 11-7 9-11 11-5`."
        )
    if len(games) > elo.MAX_GAMES:
        raise ParseError(f"That's {len(games)} games — more than {elo.MAX_GAMES} looks like a typo.")
    for a, b in games:
        if a == b:
            raise ParseError(f"`{a}-{b}` can't be a finished game — someone has to win it.")
        if max(a, b) > elo.MAX_POINTS:
            raise ParseError(f"`{a}-{b}` is out of range — scores are the points in one game.")


SKUNK_POINTS = 11


def normalise_games(games):
    """Fold a mis-logged skunk onto the score that actually happened.

    The house rule ends a game at 11-0, so a game the loser finished on zero
    cannot have run past 11 — `21-0` is someone typing the number they play to
    rather than the number on the table when it stopped. Recording it verbatim
    would put 10 points that were never played into their points total.

    It changes no rating: the margin is read relative to the game being played,
    so 21-0 and 11-0 already rescale to the same 11 and score identically. This
    is about the record being of a game that could have been played.
    """
    return [(SKUNK_POINTS, 0) if b == 0 and a > SKUNK_POINTS else
            (0, SKUNK_POINTS) if a == 0 and b > SKUNK_POINTS else (a, b)
            for a, b in games]


def parse_games(text):
    """Just the game scores out of a blob of text.

    What the guided form's score field hands us — players come from its people
    pickers, so there are no mentions to separate out. Same validation as the
    typed path, so the two routes can never disagree about what a legal match is.
    """
    games = [v for kind, v in _tokenize(text) if kind == "score"]
    validate_games(games)
    return normalise_games(games)


def parse_odds(text, caller=None, bot_id=None):
    """`/tt odds @bob` or `/tt odds @a @b vs @c @d` → (side_a, side_b), on the
    same side rules as a match but with no scores to give."""
    side_a, side_b = _sides(_tokenize(text, exclude=bot_id), caller)
    validate_sides(side_a, side_b)
    return side_a, side_b


# --- when a scheduled match starts ----------------------------------------

RELATIVE_RE = re.compile(
    r"\bin\s+(\d{1,3})\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\b", re.I)
CLOCK_12_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.I)
CLOCK_24_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

DEFAULT_LEAD_MINUTES = 30
MAX_LEAD_DAYS = 14


AMOUNT_RE = re.compile(r"\b(\d[\d,]*)\b")


def parse_transfer(text, caller=None, bot_id=None):
    """`@bob 500` (out of your own wallet) or `@alice @bob 500` (between two
    other people) → (sender, recipient, amount).

    Amounts are read after the mentions are stripped out, so the digits inside a
    Slack user id can never be mistaken for a number of spins.
    """
    people = mentions_in(text, exclude=bot_id)
    amounts = AMOUNT_RE.findall(MENTION_RE.sub(" ", text or ""))
    if not people:
        raise ParseError("Who to? `/tt transfer @someone 500`, or "
                         "`/tt transfer @from @to 500`.")
    if not amounts:
        raise ParseError("How many spins? `/tt transfer @someone 500`.")
    amount = int(amounts[-1].replace(",", ""))
    if len(people) == 1:
        return caller, people[0], amount
    return people[0], people[1], amount


def parse_when(text, now):
    """When a scheduled match starts. Returns (datetime, matched_text) or
    (None, "").

    Understands "in 20m", "in 2h", "6pm", "6:30pm" and "18:30". A clock time
    already past rolls to tomorrow, so `/tt schedule @bob 9am` typed in the
    evening means the morning — and the resolved time is always echoed back, so
    a wrong guess is visible rather than silent.
    """
    text = text or ""
    m = RELATIVE_RE.search(text)
    if m:
        size = int(m.group(1))
        unit = m.group(2).lower()
        delta = timedelta(hours=size) if unit.startswith("h") else timedelta(minutes=size)
        return now + delta, m.group(0)

    m = CLOCK_12_RE.search(text)
    if m:
        hour = int(m.group(1)) % 12
        if m.group(3).lower() == "p":
            hour += 12
        return _next_occurrence(now, hour, int(m.group(2) or 0)), m.group(0)

    m = CLOCK_24_RE.search(text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if hour < 24 and minute < 60:
            return _next_occurrence(now, hour, minute), m.group(0)
    return None, ""


def _next_occurrence(now, hour, minute):
    when = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return when + timedelta(days=1) if when <= now else when


def parse_schedule(text, caller=None, bot_id=None, now=None):
    """`/tt schedule @bob 6pm` → (side_a, side_b, when).

    Same side rules as logging a session, so `@partner vs @dan @eve` works here
    too. With no time given it assumes half an hour, which is about how long it
    takes to walk to the table.
    """
    when, matched = parse_when(text, now)
    without_time = text.replace(matched, " ") if matched else text
    side_a, side_b = _sides(_tokenize(without_time, exclude=bot_id), caller)
    validate_sides(side_a, side_b)
    if when is None:
        when = now + timedelta(minutes=DEFAULT_LEAD_MINUTES)
    if when <= now:
        raise ParseError("That's already past. Try `in 30m`, `6pm`, or `18:30`.")
    if when - now > timedelta(days=MAX_LEAD_DAYS):
        raise ParseError(f"That's more than {MAX_LEAD_DAYS} days out — "
                         "schedule it nearer the time.")
    return side_a, side_b, when


# --- correcting a logged match ---------------------------------------------

VOID_WORDS = ("void", "delete", "remove", "scrap")
SWAP_WORDS = ("swap", "flip", "invert", "reverse", "backwards")
MATCH_ID_RE = re.compile(r"^#?(\d{1,9})$")


def parse_edit(text, bot_id=None):
    """`33 21-19 …` → (id, games, swap, void), for `/tt edit`.

    The id comes first because a bare number would otherwise be indistinguishable
    from half a score. `swap` and `void` are words rather than flags so that a
    mistyped one fails loudly instead of being read as a score.
    """
    words = [w for w in text.replace("#", " #").split() if w]
    if not words:
        raise ParseError(
            "Which match? `/tt edit 33 21-17 21-19` to fix the scores, "
            "`/tt edit 33 swap` if the sides went in the wrong way round, "
            "`/tt edit 33 void` to throw it out. The number is on the result "
            "message — `Match #33`.")
    head, rest = words[0], words[1:]
    found = MATCH_ID_RE.match(head)
    if not found:
        raise ParseError(f"`{head}` isn't a match number. It's the `#33` on the "
                         "result message, and it comes first.")
    mid = found.group(1)

    swap = void = False
    scores = []
    for word in rest:
        low = word.lower()
        if low in SWAP_WORDS:
            swap = True
        elif low in VOID_WORDS:
            void = True
        else:
            scores.append(word)

    if void and (swap or scores):
        raise ParseError("`void` throws the whole match out, so it doesn't take "
                         "scores or `swap` as well.")
    games = None
    if scores:
        games = [v for kind, v in _tokenize(" ".join(scores)) if kind == "score"]
        unread = [w for w in scores
                  if not any(k == "score" for k, _ in _tokenize(w))]
        if unread:
            raise ParseError(
                f"I couldn't read `{unread[0]}` as a game score. Give every game "
                "of the corrected session, like `21-17 21-19`.")
        validate_games(games)
        games = normalise_games(games)
    if not (games or swap or void):
        raise ParseError("Nothing to change. Add the corrected scores, or "
                         "`swap` to turn the sides around, or `void`.")
    return mid, games, swap, void


# --- moving a scheduled match ----------------------------------------------

def parse_reschedule(text, now=None):
    """`6 7pm` → (fixture id, when), for `/tt reschedule`.

    The id comes first for the same reason it does in `/tt edit`: `18:30` read
    as an id and `18` read as a time are both plausible, and only the position
    tells them apart.
    """
    text = (text or "").strip()
    if not text:
        raise ParseError(
            "Which fixture, and when? `/tt reschedule 6 7pm`. The number is on "
            "the fixture message — `Fixture #6`.")
    head, _, rest = text.replace("#", " #").strip().partition(" ")
    found = MATCH_ID_RE.match(head.strip())
    if not found:
        raise ParseError(f"`{head}` isn't a fixture number. It's the `#6` on the "
                         "fixture message, and it comes first.")
    when, matched = parse_when(rest, now)
    if when is None:
        raise ParseError(
            f"I couldn't read `{rest.strip() or '(nothing)'}` as a time. "
            "Try `in 30m`, `6pm`, `6:30pm` or `18:30`.")
    if when <= now:
        raise ParseError("That's already past. Try `in 30m`, `6pm`, or `18:30`.")
    if when - now > timedelta(days=MAX_LEAD_DAYS):
        raise ParseError(f"That's more than {MAX_LEAD_DAYS} days out — "
                         "move it nearer the time.")
    return found.group(1), when


# --- challenging someone ---------------------------------------------------

# "matches" is what people here call games — the bot's own word is "games", but
# a parser that only accepts its own vocabulary is a parser people fight with.
GAME_WORDS = r"(?:games?|matches|match|sets?)"
BEST_OF_RE = re.compile(r"\bbe?st?[\s-]*of[\s-]*(\d{1,2})\b|\bbo[\s-]?(\d{1,2})\b", re.I)
FIRST_TO_RE = re.compile(r"\bfirst[\s-]*to[\s-]*(\d{1,2})\b|\bft[\s-]?(\d{1,2})\b", re.I)
COUNT_RE = re.compile(rf"\b(\d{{1,2}})\s*{GAME_WORDS}\b", re.I)


def parse_length(text):
    """How long a session runs → (games, first_to, matched text).

    Three ways to say it, because people do:

      best of 5 / bo5   → up to 5 games, first to 3
      first to 3 / ft3  → first to 3, so up to 5 games
      5 games / 5 matches → 5 games, nobody stops early

    (None, None, "") when the text doesn't say. The caller supplies the default,
    because "no length given" is a different fact from "they asked for three".
    """
    found = BEST_OF_RE.search(text or "")
    if found:
        games = int(found.group(1) or found.group(2))
        return games, games // 2 + 1, found.group(0)
    found = FIRST_TO_RE.search(text or "")
    if found:
        first_to = int(found.group(1) or found.group(2))
        return first_to * 2 - 1, first_to, found.group(0)
    found = COUNT_RE.search(text or "")
    if found:
        return int(found.group(1)), None, found.group(0)
    return None, None, ""


# --- open challenges --------------------------------------------------------

# "anyone around my level" — what an open call means when nobody says otherwise.
DEFAULT_BAND = 100
# Wide enough to be a real range and no wider: a band of 900 is not a band.
MAX_BAND = 400

# `1100-1250` absolute, or `+150` / `-150` / `±100` relative to the caller.
# Matched before anything is tokenised, because a hyphenated pair of numbers is
# a scoreline to every other part of this module.
_BAND_ABS = re.compile(r"\b(\d{3,4})\s*(?:-|–|to)\s*(\d{3,4})\b")
_BAND_REL = re.compile(r"(?<![\w-])(\+-|±|\+|-)\s*(\d{1,4})(?![\d-])")
_OPEN_WORD = re.compile(r"(?i)(?:^|\s)(open|anyone)(?=\s|$)")


def split_open(text):
    """(is it an open call, the rest of the text) — `open` or `anyone`, wherever
    it sits, pulled out so nothing downstream reads it as a name."""
    text = text or ""
    if not _OPEN_WORD.search(text):
        return False, text.strip()
    return True, _OPEN_WORD.sub(" ", text).strip()


def parse_band(text, rating=None):
    """((low, high), matched text) — the rating range an open call is aimed at.

    Absolute (`1100-1250`) or relative to whoever is asking (`+150` means up to
    150 above me, `±100` either way). Nothing given and it is (None, "") — the
    caller decides what no band means, because that depends on knowing their
    rating.
    """
    m = _BAND_ABS.search(text or "")
    if m:
        low, high = sorted((int(m.group(1)), int(m.group(2))))
        _check_band(low, high)
        return (low, high), m.group(0)
    m = _BAND_REL.search(text or "")
    if m:
        if rating is None:
            raise ParseError("I need to know your rating to read a range like "
                             f"`{m.group(0).strip()}` — play a game first, or "
                             "give it as `1100-1250`.")
        sign, size = m.group(1), int(m.group(2))
        rating = int(rating)
        if sign in ("+-", "±"):
            low, high = rating - size, rating + size
        elif sign == "+":
            low, high = rating, rating + size
        else:
            low, high = rating - size, rating
        _check_band(max(low, 0), high)
        return (max(low, 0), high), m.group(0)
    return None, ""


def _check_band(low, high):
    if high - low > MAX_BAND:
        raise ParseError(f"That range is {high - low} points wide — wider than "
                         f"{MAX_BAND} is everyone. Try something like "
                         "`±100`.")


def parse_open_challenge(text, caller=None, bot_id=None, now=None,
                         default_games=3, rating=None):
    """`open ±100 best of 5 at 6pm` → (side_a, (low, high), games, first_to, when).

    `side_a` is whoever is asking, plus a partner if they named one — their half
    of a doubles match is theirs to settle. The other side is whoever takes it.
    """
    band, band_text = parse_band(text, rating)
    rest = text.replace(band_text, " ") if band_text else text
    rest, games, first_to, when = _length_and_time(rest, now, default_games)

    # Every mention here is on *my* side. That is the whole difference: a
    # directed challenge reads one name as the opponent, and an open call has no
    # opponent to read — whoever takes it brings their own.
    named = [uid for uid in mentions_in(rest, exclude=bot_id) if uid != caller]
    side_a = ([caller] if caller else []) + named
    if len(side_a) > 2:
        raise ParseError("A side is one player or two. Name one partner at "
                         "most — whoever takes it brings their own.")
    if band is None:
        if rating is None:
            raise ParseError("Say who it's for — `/tt challenge open 1100-1250` "
                             "— or play a game first so I can read `±100`.")
        band = (max(int(rating) - DEFAULT_BAND, 0), int(rating) + DEFAULT_BAND)
    return side_a, band, games, first_to, when


def _length_and_time(text, now, default_games):
    """(rest of the text, games, first_to, when|None) — the two halves of a
    challenge that aren't the players. Shared with parse_open_challenge, so a
    directed call and an open one can't disagree about what `bo5 at 6pm` means.
    """
    import elo
    games, first_to, length_text = parse_length(text)
    rest = text.replace(length_text, " ") if length_text else text

    when, when_text = parse_when(rest, now)
    if when_text:
        rest = rest.replace(when_text, " ")
    # `at` is only ever glue between the two, and would read as a name otherwise.
    rest = re.sub(r"(?i)\bat\b", " ", rest)

    if games is None:
        games, first_to = default_games, default_games // 2 + 1
    if games < 1:
        raise ParseError("A session is at least one game.")
    if games > elo.MAX_GAMES:
        raise ParseError(f"{games} games is more than the {elo.MAX_GAMES} a "
                         "session can hold. Try `best of 5`.")
    if when is not None:
        if when <= now:
            raise ParseError("That's already past. Try `in 30m`, `6pm`, or `18:30`.")
        if when - now > timedelta(days=MAX_LEAD_DAYS):
            raise ParseError(f"That's more than {MAX_LEAD_DAYS} days out — "
                             "challenge them nearer the time.")
    return rest, games, first_to, when


def parse_challenge(text, caller=None, bot_id=None, now=None, default_games=3):
    """`@bob best of 5 at 6pm` → (side_a, side_b, games, first_to, when|None).

    The time is optional here in a way it isn't for `/tt schedule`: a challenge
    is an invitation, and "play me some time today" is a real thing to say. Left
    out, it is None and the fixture takes its start from whenever it's accepted.
    """
    rest, games, first_to, when = _length_and_time(text, now, default_games)
    side_a, side_b = _sides(_tokenize(rest, exclude=bot_id), caller)
    validate_sides(side_a, side_b)
    if caller and caller in side_b:
        raise ParseError("You can't challenge yourself.")
    return side_a, side_b, games, first_to, when
