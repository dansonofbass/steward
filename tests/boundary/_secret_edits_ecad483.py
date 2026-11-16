"""ecad483's secret rule, frozen: a verbatim copy of steward_boundary/text.py's secret_edits and its helpers as they were
at ecad483 (2026-11-01), the last version before the rule was made linear on glued words. test_text.py's differential
test runs it beside the live rule on thousands of generated inputs and fails if the live rule ever leaves visible a
character this one redacts: a speed or refactoring change must never send a secret the old rule kept back. Don't edit
it. A change that redacts less on purpose (a false positive fixed) narrows the differential test, not this file."""
# ruff: noqa
from __future__ import annotations

import re
from bisect import bisect_left

from steward_boundary.normal import View, as_view
from steward_boundary.spans import Edit, merge

_DIGIT_WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine".split())} | {"oh": "0"}


# A PIN, password or code is never sent, however short (click-through feedback, 2026-10-25): the question rule lets 4
# digits leave, so "my pin for my debit card 1111" went out as written. Three reviews shaped the rule (two adversarial
# rounds and Argon's, 2026-10-25):
# - A strong secret word (PIN, password, CVV, a door, two-factor or one-time code, an SSN's last four...) takes every
#   number of 3 or more digits in its sentence after it (up to 40 words) and in the 12 words before it, and every
#   number of any length in the value's place: right after the word, or after "is", ":", "=", "of", "from" or "ends
#   in". Spaced, hyphenated or spoken digits are one number ("1 - 1 - 1 - 1", "one then one then one").
# - A weak word (a bare "code", "combination", "SSN") takes only the value: "the code is 482913", "SSN: 3456", and
#   "4821 is the code". "Decline code 05" and "SSN at age 65" stay.
# - A password word's value goes, a word or several ("correct horse battery staple"), after a marker ("changed to"
#   too), in quotes, or as the word right after it ("pw fluffy"); and so does the value in "fluffy is my password" or
#   "is fluffy my password?". A word that makes it something else ("password manager", "password reset") ends that.
# - If the word ends its sentence ("My PIN? It's 1111."), the next sentence is read; if nothing comes before it in
#   its sentence ("1111. That's my pin."), the end of the one before is.
# - A masked SSN ("xxx-xx-3456") goes wherever it is.
# Real PINs and codes have 3 digits or more, so outside the value's place a lone number of 1 or 2 digits stays ("3
# times", "age 65", "Q3", "1Password"), and so do money, percents, ordinals, a 3-digit count with its unit ("150
# entries"), a year after "in" or "since", a tax form named as one ("the 1099", "401(k)"), and a bank's "PIN
# purchase", "PIN-less" or "PIN debit". The text is split into tokens once, so the rule is linear in it.
_PASS_WORD = (r"pas{1,2}(?:w{1,2}(?:or|ro|o|r)?d|owrd)s?|pass\s(?:word|code|phrase)s?|passcodes?|passphrases?|pwd|pw"
              r"|pass(?=\s?[:=]|\s(?:is|was)(?![\w]))")
_CODE_KIND = (r"(?:security|access|verification|confirmation|one[\s-]time|2fa|two[\s-]factor|auth(?:entication)?|login"
              r"|log[\s-]in|sign[\s-]?in|text|sms|gate|door|alarm|garage|lock|keypad|entry|secret)")
_SOCIAL = r"(?:ssn|ss#|ss\s?(?:number|no\.?|#)|soc\.?\s?sec(?:urity)?|social(?:\s+security)?(?:\s+(?:number|no\.?|#))?)"
_STRONG = (r"(?:pinn?|p1n)s?(?![\s-]+(?:purchase|debit|transaction|pad|point|less|based)s?(?![\w]))(?:\s?(?:number|code)s?)?"
           r"|p\.\s?i\.\s?n\.?|p\si\sn|cvv2?|cvc2?|csc|otp|secret\s+(?:number|word)s?"
           rf"|{_CODE_KIND}\s+(?:pass)?codes?|(?:safe|lock|locker|padlock|gate|door)\s+combinations?"
           rf"|last\s+(?:4|four)(?:\s+digits)?\s+(?:of\s+)?(?:\S+\s+){{0,2}}?{_SOCIAL}"
           rf"|{_SOCIAL}(?:'s)?\s+(?:\S+\s+){{0,3}}?(?:ends?\s+(?:in|with)|ending\s+(?:in|with)|last\s+(?:4|four))")
_NOT_A_CODE = ("zip", "area", "tax", "postal", "country", "promo", "discount", "coupon", "error", "status", "source",
               "category", "bar", "qr", "dress", "reason", "billing", "swift", "sort", "decline", "return", "response",
               "reject", "rejection", "merchant", "sic", "naics", "diagnosis", "zoning", "building", "fire", "referral",
               "offer", "invite", "revenue", "irs", "transaction")
_WEAK = ("".join(rf"(?<!{w}\s)" for w in _NOT_A_CODE) + r"codes?(?!\s(?:section|of)(?![\w]))"
         r"|combinations?|ssn|ss#|ss\s?(?:number|no\.?|#)|social\s+security\s+(?:number|no\.?|#)"
         r"|social(?!\s+(?:security|media|life|worker|workers|club|event|events|studies|services|network|networks))")
SECRET_RE = re.compile(rf"(?<![\w])(?:(?P<pass>{_PASS_WORD})|(?P<strong>{_STRONG})|(?P<weak>{_WEAK}))"
                       r"(?![^\W\d_])", re.IGNORECASE)      # digits may follow at once: "PIN1111"
_MASKED_SSN_RE = re.compile(r"(?<![\w•*#])[x*•#]{2,3}[\s-]?[x*•#]{2,3}[\s-]?\d{4}(?!\d)", re.IGNORECASE)
SECRET_PLACEHOLDER = "[secret]"
_AFTER, _BEFORE = 40, 12            # words read after and before a secret word
_VALUE_WORDS = 6                    # words a password's value may run to
_IS = frozenset("is was are it's it’s its that's that’s".split())
_PREPS = frozenset("of from as be into".split())         # markers only right after the word: "a PIN of 1984"
_MARKERS = _IS | _PREPS                                   # and "in" or "with" after "ends", "to" after "changed"
_CHANGE = frozenset("change changed changing set reset update updated make made switch switched".split())
_FILLER = frozenset("the a an still now also really just currently actually probably my our your his her their "
                    "i think guess believe maybe".split())          # between a marker and the value
_MODIFIES = frozenset("manager managers reset resets hint hints field fields recovery policy policies requirements "
                      "rules strength protected protection change changes app apps generator vault list sharing "
                      "reuse expiry expiration length screen".split())       # "password manager" isn't a password
_NOT_A_VALUE = _MODIFIES | frozenset(
    "not wrong broken expired expires expiring expire locked same too working changed fine ok okay weak strong saved "
    "stored incorrect invalid required case long short secure safe compromised leaked hacked very here there it this "
    "that what which where who how why when written keeps keep needs need has have had got gets for on at in with "
    "about by you we they he she me him them yesterday today again 1password bitwarden lastpass dashlane keeper "
    "cheaper better must may might cost costs costing screen old older doesn't don't didn't isn't wasn't won't "
    "can't couldn't hasn't haven't wouldn't shouldn't aren't doesn’t don’t didn’t isn’t wasn’t won’t can’t "
    "work works worked stopped stops failed fails failing".split())
_KILL = frozenset("and but so or did does do can could should would will because if when how what why where "
                  "then".split())          # a new clause: a password word's value isn't after one
_KILL_AFTER_COMMA = frozenset("and but so or".split())   # "for checking and savings is ..." is one clause
_GIVE = frozenset("use try type enter".split())         # "My password. Use fluffy."
_JOINERS = frozenset("then and dash".split())                        # inside a spoken number
_DETERMINERS = frozenset("my the our your his her their a".split())
_BEFORE_STOP = _NOT_A_VALUE | _KILL | _FILLER | _MARKERS | frozenset("use used using chose picked made set".split())
_AFTER_OK = frozenset("for on at with to now too everywhere right".split())
_CONTENTLESS = _IS | _DETERMINERS | frozenset("this that which as mine".split())
_JOINING = _IS | _DETERMINERS | frozenset("for as new old debit atm card bank".split())   # "1984 for my debit PIN"
_ABBREVIATIONS = frozenset("no nr mr mrs ms dr st jr sr inc co corp ltd vs etc approx acct ave apt dept est jan feb mar "
                           "apr jun jul aug sep sept oct nov dec mon tue wed thu fri sat sun".split())
_NUMBER_WORDS = frozenset([*_DIGIT_WORDS, "o", *"ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
                           "nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand".split()])
_UNITS = frozenset("time times day days week weeks month months year years digit digits character characters chars "
                   "letter letters number numbers minute minutes min mins hour hours attempt attempts tries atm atms "
                   "entry entries word words account accounts card cards people kids apps devices sites websites factor "
                   "percent dollars bucks".split())
_UNIT_HYPHEN_RE = re.compile(r"\d+-(?:digit|character|letter|day|week|month|year|hour|minute)s?")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_YEAR_AFTER = frozenset("in since from until till before after by of during for through thru and".split())
_FORMS = frozenset("1099 1098 1040 1095 1065 1120 1031 529 401k 403b 457 457b w-2 w2 w-4 w4 w-9 w9".split())
_FORM_BEFORE = frozenset("form forms the a my our your schedule file filed on for".split())
_FORM_AFTER = frozenset("form forms return returns exchange plan plans account accounts".split())
_STRIP = "\"'()[]{}<>.,;:!?=#“”‘’«»"
_QUOTES = "\"'(“‘«"
_TOKEN_RE = re.compile(r"[^\s=:]+[=:]*|[=:]+")      # "chase=1111" is "chase=" and "1111"
_ORDINAL_RE = re.compile(r"\d+(?:st|nd|rd|th)")
_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?")      # "10/12": never a PIN
_DECIMAL_RE = re.compile(r"\d*\.\d+")                     # "2.50": a PIN only in the value's place
_HYPHENS = re.compile(r"[-./]")


def _tokens(n: str, start: int, end: int) -> list[tuple[re.Match, int, int]]:
    """Each token of n[start:end] with the bounds of its core: the token less its leading and trailing punctuation.
    A token with no letter or digit ("-", "/", "&", "...", "=") has an empty core."""
    out = []
    for m in _TOKEN_RE.finditer(n, start, end):
        s, e = m.start(), m.end()
        while s < e and n[s] in _STRIP:
            s += 1
        while e > s and n[e - 1] in _STRIP:
            e -= 1
        if not any(c.isalnum() for c in n[s:e]):
            s = e
        out.append((m, s, e))
    return out


def _core(n: str, toks: list, i: int) -> str:
    return n[toks[i][1]:toks[i][2]] if 0 <= i < len(toks) else ""


def _cores(n: str, toks: list) -> list[str]:
    return [n[s:e] for _, s, e in toks if e > s]


def _number(n: str, toks: list, i: int, place: int) -> tuple[int, int] | None:
    """(digits, number words) a token adds to a secret number, or None. `place` is 0 for anywhere in the sentence, 1
    right after the secret word, 2 in the value's place (after a marker)."""
    m, s, e = toks[i]
    core = n[s:e]
    if not core or core.startswith("$") or core.endswith("%") or _ORDINAL_RE.fullmatch(core):
        return None
    if _UNIT_HYPHEN_RE.fullmatch(core) or _DATE_RE.fullmatch(core) or (place < 2 and _DECIMAL_RE.fullmatch(core)):
        return None                                 # "a 4-digit pin", "declined on 10/12", "a fee of 2.50"
    digits = sum(c.isdigit() for c in core)
    if digits:
        letters = any(c.isalpha() for c in core)
        before, after = _core(n, toks, i - 1), _core(n, toks, i + 1)
        if (digits <= 3 and after in _UNITS and e == m.end() and i + 1 < len(toks)
                and toks[i + 1][0].start() == toks[i + 1][1]):
            return None                             # "3 times", "150 entries"; not "1234, try" or "1234 (card"
        if letters and digits < 3:
            return None                             # "Q3", "1Password": a password value is the value rule's
        if place < 2:
            if "(k)" in m.group() or "(b)" in m.group():
                return None                         # "401(k)"
            if place == 0 and core in _FORMS and (before in _FORM_BEFORE or after in _FORM_AFTER):
                return None
            if place == 0 and _YEAR_RE.fullmatch(core) and before in _YEAR_AFTER:
                return None
        return (max(digits, 3) if letters else digits), 0
    parts = _HYPHENS.split(core)
    if len(parts) > 1 and all(p in _NUMBER_WORDS for p in parts):
        return 0, len(parts)
    return (0, 1) if core in _NUMBER_WORDS else None


class _Runs:
    """Runs of secret tokens. Punctuation alone ("-", "/") and a spoken joining word ("then", "and") don't end one. A
    run is a secret when it holds 3 digits or more, two number words, or a value."""

    def __init__(self) -> None:
        self.spans: list[tuple[int, int]] = []
        self.run: list[tuple[int, int]] = []
        self.digits = self.words = 0
        self.forced = False

    def add(self, s: int, e: int, digits: int = 0, words: int = 0, forced: bool = False) -> None:
        self.run.append((s, e))
        self.digits, self.words, self.forced = self.digits + digits, self.words + words, self.forced or forced

    def close(self) -> None:
        if self.run and (self.forced or self.digits >= 3 or self.words >= 2):
            self.spans.append((self.run[0][0], self.run[-1][1]))
        self.run, self.digits, self.words, self.forced = [], 0, 0, False


def _ends_sentence(n: str, m: re.Match, s: int, e: int) -> bool:
    tail = n[e:m.end()] if e > s else m.group()
    if any(c in "!?" for c in tail):
        return True
    if "." not in tail or ".." in tail:             # an ellipsis doesn't end one
        return False
    core = n[s:e]                                   # nor do "U.S.", "no." and "i.e."
    return not ("." in core or core in _ABBREVIATIONS or (len(core) == 1 and core.isalpha()))


def _secret_after(n: str, toks: list, kind: str, marker: bool, changing: bool) -> list[tuple[int, int]]:
    """The secrets in the tokens after one secret word: kind is "strong", "pass" (a password word) or "weak"."""
    runs = _Runs()
    pass_word = kind == "pass"
    in_value = False
    value = words = 0
    before = ""
    crossed = False                                 # into the next sentence, once, when the word ends its own
    comma = giving = False
    for i, (m, s, e) in enumerate(toks):
        core, head = n[s:e], n[m.start():s]
        marker = marker or any(c in ":=" for c in head)
        if core == "s" and head[-1:] in ("'", "’"):    # "code's 4821", "password's expired": the word's "is"
            marker, before = True, "is"
            continue
        if core:
            words += 1
            if words > _AFTER:
                break
            if pass_word and words == 1 and not head and core in _MODIFIES:
                pass_word = False                   # "password manager", "password reset fee"
            quoted = pass_word and words == 1 and any(c in _QUOTES for c in head)     # my password "fluffy"
            bare = pass_word and words == 1 and not head and not crossed and any(c.isalpha() for c in core)  # pw fluffy
            if in_value and core == "or":
                in_value, pass_word, marker = False, True, True     # "fluffy or fluffy2"
                before = core
                continue
            if in_value and (core in _KILL or core in _IS or value == _VALUE_WORDS):
                in_value = False
            elif not in_value and core in _KILL and (comma or core not in _KILL_AFTER_COMMA):
                pass_word = False                   # "I forgot my password, so what is my balance?"
            if (pass_word and not in_value and (marker or quoted or bare) and core not in _NOT_A_VALUE
                    and core not in _FILLER and core not in _MARKERS and core not in _KILL and core != "to"
                    and core not in _UNITS
                    and not core.startswith("$") and not core.endswith("%")
                    and not (any(c.isdigit() for c in core) and _core(n, toks, i + 1) in _UNITS)):
                in_value, pass_word, value = True, False, 0
            if in_value:
                runs.add(s, e, forced=True)
                value += 1
            else:
                place = 2 if marker else 1 if words == 1 else 0
                num = _number(n, toks, i, place) if kind != "weak" or marker or words == 1 or runs.run else None
                if num:
                    runs.add(s, e, *num, forced=place == 2)
                elif not (core in _JOINERS and runs.run):
                    runs.close()
            counting = core in _UNITS or core in ("one", "long") or _UNIT_HYPHEN_RE.fullmatch(core) or (
                core.isdigit() and len(core) <= 2 and _core(n, toks, i + 1) in _UNITS)  # "is a 4-digit one, 5821"
            if not (marker and (core in _FILLER or counting)):    # "is still ...", "is the ...", "is my ..."
                marker = (core in _IS or (core in _PREPS and (kind == "pass" or (kind == "strong" and (words == 1 or marker))))
                          or (core in ("in", "with") and before in ("end", "ends", "ending"))
                          or (core == "to" and kind == "pass" and (changing or before in _CHANGE))
                          or (giving and words == 1 and core in _GIVE))
            before = core
        tail = n[e:m.end()] if e > s else m.group()
        marker = marker or any(c in ":=" for c in tail)
        comma = any(c in ",;" for c in tail)
        if comma or (e == s and not marker):
            in_value = False
        if _ends_sentence(n, m, s, e):
            # The next sentence, when the word ends its own ("My PIN? It's 1111.", "My CVV. Use 1111.") or the next
            # one points back ("... yesterday. The new one is 1111."). A password's value there follows a question
            # mark, is the whole of a short sentence ("My password. Sunshine.") or follows a word that gives it ("My
            # password. Use fluffy."), so "I forgot my password. Please check my savings." keeps its words.
            if not crossed and (words == 0 or _points_back(_cores(n, toks[i + 1:i + 4]))):
                crossed, giving = True, kind == "pass" and words == 0
                marker = marker or (giving and (any(c in "?!" for c in tail) or _short_sentence(n, toks[i + 1:])))
                continue
            break
    runs.close()
    return runs.spans


_BACK = (("it",), ("it's",), ("its",), ("it’s",), ("that's",), ("this",), ("mine",), ("the", "new"), ("the", "old"),
         ("new", "one"), ("old", "one"), ("the", "code"), ("the", "pin"), ("the", "number"))


def _short_sentence(n: str, toks: list, most: int = 4) -> bool:
    """The sentence at the start of `toks` has at most `most` words."""
    words = 0
    for m, s, e in toks:
        words += e > s
        if words > most:
            return False
        if _ends_sentence(n, m, s, e):
            break
    return words > 0


def _points_back(cores: list[str]) -> bool:
    """The next sentence starts by pointing back at the secret: "It's 1111", "The new one is 1111"."""
    return any(tuple(cores[:len(b)]) == b for b in _BACK)


def _sentence_start(n: str, toks: list, skip_last: bool = False) -> int:
    """Where in `toks` the last sentence begins: after the last token that ends one (not counting the very last
    token when `skip_last`), or 0."""
    for j in range(len(toks) - 1 - skip_last, -1, -1):
        if _ends_sentence(n, *toks[j]):
            return j + 1
    return 0


def _secret_before(n: str, toks: list, after: list, kind: str) -> list[tuple[int, int]]:
    """The secrets in the tokens before one secret word (`toks`, the last few dozen of them)."""
    begins = _sentence_start(n, toks)
    prev, toks = toks[:begins], toks[begins:]
    words = [k for k, (_, s, e) in enumerate(toks) if e > s][-_BEFORE:]
    cores = [_core(n, toks, k) for k in words]
    runs = _Runs()
    if kind == "weak":                              # "4821 is the code"
        for w in range(len(words) - 1):
            if cores[w + 1] in _IS and all(c in _DETERMINERS for c in cores[w + 2:]):
                num = _number(n, toks, words[w], 1)
                if num:
                    runs.add(*toks[words[w]][1:], *num, forced=True)
                    runs.close()
        return runs.spans
    for w, k in enumerate(words):
        place = 1 if all(c in _JOINING for c in cores[w + 1:]) or cores[w + 1] in _MARKERS else 0
        num = _number(n, toks, k, place)
        if num:
            runs.add(*toks[k][1:], *num)
        elif not (cores[w] in _JOINERS and runs.run):
            runs.close()
    runs.close()
    if kind == "pass":
        runs.spans += _value_before(n, toks, words, cores, after)
    if prev and all(c in _CONTENTLESS for c in cores):     # "1111. That's my pin."
        prev = prev[_sentence_start(n, prev, skip_last=True):]
        last = _Runs()
        for k in [k for k, (_, s, e) in enumerate(prev) if e > s][-6:]:
            num = _number(n, prev, k, 1)
            last.add(*prev[k][1:], *num) if num else last.close()
        last.close()
        runs.spans += last.spans
    return runs.spans


def _value_before(n: str, toks: list, words: list[int], cores: list[str], after: list) -> list[tuple[int, int]]:
    """A password's value written before its word: "fluffy is my password", "correct horse battery staple is my
    online banking password", "is fluffy my password?", "I use fluffy as my password". Only when the password word
    ends the clause, so "the problem is my password keeps expiring" keeps its words."""
    if after:
        m, s, e = after[0]
        if m.start() == s and e > s and _core(n, after, 0) not in _AFTER_OK | _KILL:
            return []
    tail_is = [w for w in range(len(cores)) if cores[w] in ("is", "was", "as", "'s")
               or (cores[w] == "for" and w > 1 and cores[w - 2] in ("use", "used", "using"))]
    if not tail_is:
        owned = [w for w in range(len(cores) - 1) if cores[w].endswith(("'s", "’s")) and cores[w + 1] in _DETERMINERS]
        if owned and cores[owned[-1]][:-2] not in _BEFORE_STOP:         # "fluffy's my password"
            _, s, e = toks[words[owned[-1]]]
            return [(s, e - 2)]
        return []
    j = tail_is[-1]
    between = cores[j + 1:]
    if len(between) > 4:
        return []
    if between and between[0] in _DETERMINERS and not any(c in _KILL or c in _MARKERS for c in between):
        value, k = [], j - 1                        # "<value> is my password"
        while k >= 0 and cores[k] not in _BEFORE_STOP and len(value) < _VALUE_WORDS:
            value.append(words[k])
            k -= 1
        return [(toks[value[-1]][1], toks[value[0]][2])] if value else []
    if (len(between) >= 2 and cores[j] in ("is", "was") and between[0] not in _BEFORE_STOP
            and between[1] in _DETERMINERS):        # "is fluffy my password?"
        return [toks[words[j + 1]][1:]]
    return []


def secret_edits(text: str | View) -> list[Edit]:
    """Edits that replace each PIN, password or code written next to its word with "[secret]", found on the normal
    form (so case, full-width digits and odd spacing don't hide one) and made on the plain text."""
    v = as_view(text)
    n = v.norm
    toks = _tokens(n, 0, len(n))
    starts = [m.start() for m, _, _ in toks]
    spans = [(m.start(), m.end()) for m in _MASKED_SSN_RE.finditer(n)]
    for w in SECRET_RE.finditer(n):
        kind = "weak" if w.group("weak") else "pass" if w.group("pass") else "strong"
        i = bisect_left(starts, w.end())
        after = toks[i:i + 2 * _AFTER + 2]
        if i and toks[i - 1][0].end() > w.end():    # the word ends inside a token: "PIN1111", "pin#1111"
            after = _tokens(n, w.end(), toks[i - 1][0].end()) + after
        k = bisect_left(starts, w.start())
        before = [t for t in toks[max(0, k - 3 * _BEFORE):k] if t[0].end() <= w.start()]
        prior = _cores(n, before[_sentence_start(n, before):])[-_BEFORE:]
        asked = kind == "pass" and bool(prior) and (prior[-1] in ("is", "was") or (
            len(prior) > 1 and prior[-2] in ("is", "was") and prior[-1] in _DETERMINERS))    # "is my password fluffy?"
        changing = kind == "pass" and any(c in _CHANGE for c in prior)              # "changed my password to ..."
        spans += _secret_after(n, after, kind, asked, changing) + _secret_before(n, before, after, kind)
    return merge(Edit(*v.to_plain(s, e), SECRET_PLACEHOLDER, "steward") for s, e in spans)
