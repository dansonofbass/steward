"""Plain wording for amounts, dates and items, shared by the inventory's API answers and the change record.
Money reads like a bank statement ("$8,214.55", "−$1,182.40"); dates like "Mar 1" or "Feb 14, 2025"."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import date, datetime

from steward import clock as steward_clock

MINUS = "−"
DOTS = "••"
_SPELLED = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten")


def usd(cents: int) -> str:
    c = abs(int(cents))
    return f"{MINUS if cents < 0 else ''}${c // 100:,}.{c % 100:02d}"


def short_usd(cents: int) -> str:
    """"$480" for whole dollars, "$15.99" otherwise: amount ranges in Known payees (watching ruling 24)."""
    return usd(cents)[:-3] if abs(int(cents)) % 100 == 0 else usd(cents)


def ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def day_label(d: date, today: date) -> str:
    return f"{d:%b} {d.day}" if d.year == today.year else f"{d:%b} {d.day}, {d.year}"


def long_date(d: date) -> str:
    return f"{d:%B} {d.day}, {d.year}"


def month_year(d: date) -> str:
    return f"{d:%b} {d.year}"


def clock(local: datetime) -> str:
    """"6:12 AM" for a time already in the household's zone."""
    return f"{local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}"


def when_label(t: datetime, today: date) -> str:
    local = t.astimezone(steward_clock.household_tz())
    day = "today" if local.date() == today else day_label(local.date(), today)
    return f"{day}, {clock(local)}"


def at_label(t: datetime, today: date) -> str:
    """"today at 6:12 AM" or "Oct 17 at 6:12 AM", in the household's time zone."""
    local = t.astimezone(steward_clock.household_tz())
    day = "today" if local.date() == today else day_label(local.date(), today)
    return f"{day} at {clock(local)}"


def _plain(text: str) -> str:
    """NFKC, with invisible format characters (zero-width spaces and joiners, direction marks) dropped, so what is
    counted as a digit or a separator is what a reader sees."""
    return "".join(c for c in unicodedata.normalize("NFKC", text) if unicodedata.category(c) != "Cf")


def clean_account(name: str, last4: str | None = None) -> str:
    """A name from the bank or the inventory under the same rule as mask_numbers: at most 4 digits in all, earlier
    digits become "•" ("Way2Save savings" is unchanged). With the stored `last4`, a trailing number group that only
    repeats it is dropped: "Checking 123456789" with "6789" is "Checking", shown next to "••6789"."""
    text = mask_numbers(name)
    if not any(c.isdigit() for c in text):
        return text.strip()
    text = re.sub(r"(?<![\w])(?:[xX*#]+|\.{2,})\s?(?=[\d•])", "", text)          # "x4417", "...4417", "#4417"
    want = re.sub(r"\D", "", last4 or "")
    if want:
        m = re.search(r"[\s,;:\-–(\[]*•?(\d{1,4})[)\]]?$", text)
        if m and m.group(1) == want:
            text = text[:m.start()]
    text = re.sub(r"\(\s*\)|\[\s*\]", "", text)
    text = re.sub(r"[^\w\s()\[\]•]{2,}", " ", text)                 # punctuation left holding nothing
    text = re.sub(r"\s{2,}", " ", text)
    return re.sub(r"^[^\w(\[•]+|[^\w)\]]+$", "", text).strip()


def mask_numbers(text: str) -> str:
    """Text from the bank with at most 4 digits in all, whatever separates them: only the last 4 digit characters are
    kept, and every digit before them becomes "•" ("1234 5678 9012" is "•9012"). A string with 4 or fewer digits is
    unchanged. Amounts and dates are shown from structured fields, never from this text (spec 4.3)."""
    text = _plain(text)
    total = sum(c.isdigit() for c in text)
    if total <= 4:
        return text
    seen, out = 0, []
    for c in text:
        if c.isdigit():
            seen += 1
            out.append(c if seen > total - 4 else "•")
        else:
            out.append(c)
    return re.sub(r"•(?:[^\w•]*•)*", "•", "".join(out))


_KEEP = re.compile(r"[−-]?\$\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}(?:, \d{4})?(?!\d)")


def safe_line(text: str) -> str:
    """A stored summary or title made safe to show: amounts ("$1,234.56") and dates ("Oct 17", "Feb 14, 2025") stay as
    they are, every other stretch has at most 4 digits (mask_numbers). New rows are built safe; this covers older ones."""
    text = _plain(text)
    out, at = [], 0
    for m in _KEEP.finditer(text):
        out.append(mask_numbers(text[at:m.start()]))
        out.append(m.group())
        at = m.end()
    out.append(mask_numbers(text[at:]))
    return "".join(out)


_ADDRESS = re.compile(r"[\w.+%'-]+@[\w-]+(?:\.[\w-]+)+")


def scrub_text(text: str | None) -> str | None:
    """Text from a mail server or an exception made safe for logs and the book: no email address (SMTP prints them
    as "<a@b.com>", "RCPT TO:<a@b.com>" or "5.1.1 a@b.com") and at most 4 digits."""
    return None if text is None else mask_numbers(_ADDRESS.sub("(address)", _plain(text)))


def log_safe(e: BaseException) -> str:
    """What may go to the server log about a failure, never a traceback (which can carry recipients, subjects, bodies
    and SQL parameters). A mail server's or the network's (OSError, which smtplib's errors are): its type and its
    first line, scrubbed. Anything else: its type only, since its message can carry a description, an amount or a
    name (release spec 2026-11-05, section 6)."""
    if not isinstance(e, OSError):
        return f"{type(e).__name__} (message not logged)"
    first = (str(e).splitlines() or [""])[0][:200]
    return f"{type(e).__name__}: {scrub_text(first)}"


def mask(last4: str | None) -> str | None:
    return f"{DOTS}{last4}" if last4 else None


def last4_of(number: str) -> str | None:
    chars = re.sub(r"[^0-9A-Za-z]", "", number)
    return chars[-4:].upper() if chars else None


def size_label(n: int) -> str:
    return f"{max(1, round(n / 1024))} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def article(word: str) -> str:
    if word[:1].isupper() and word.isupper():   # an acronym is read letter by letter: "an RMD", "a CD"
        return "an" if word[0] in "AEFHILMNORSX" else "a"
    return "an" if word[:1].lower() in "aeiou" else "a"


def joined(words: Sequence[str]) -> str:
    words = [w for w in words if w]
    if len(words) <= 1:
        return words[0] if words else ""
    return f"{', '.join(words[:-1])} and {words[-1]}"


def spelled(n: int) -> str:
    return _SPELLED[n] if 0 <= n < len(_SPELLED) else str(n)


def parent_name(owner_names: Iterable[str]) -> str:
    """The parent's first name: the first word of the book's first owner label (ledger ruling 1)."""
    for label in owner_names:
        words = label.split()
        if words:
            return words[0]
    return "this person"


def possessive(name: str) -> str:
    return f"{name}'s"


def long_label(name: str, institution: str | None, last4: str | None, kind: str | None = None) -> str:
    """"Fidelity Traditional IRA ••3390": the institution is left out when the name already says it. A contact is
    "Linda Park, Park & Reyes Law"."""
    if kind == "contact":
        return f"{name}, {institution}" if institution else name
    parts = [name] if not institution or institution.lower() in name.lower() else [institution, name]
    return " ".join(parts + ([mask(last4)] if last4 else []))


def short_ref(name: str, institution: str | None, last4: str | None) -> str:
    """"Wells Fargo ••4417", for lines like "into Wells Fargo ••4417"."""
    return " ".join([institution or name] + ([mask(last4)] if last4 else []))
