import random
import re

import pytest

from steward_boundary.spans import apply
from steward_boundary.text import (
    is_outgoing_safe, is_question_safe, is_stored_safe, luhn, mask_numbers, outgoing_edits, outgoing_text, plain,
    question_edits, question_text, stored_edits, stored_text, typed_ok,
)

ISSUED = frozenset({"Account 12", "Account 13", "Person 2", "Payee 1000", "Account 3", "Person 1"})

# Ordinary questions pass the question path unchanged (Task 2.5: they must keep working).
KEPT = [
    "Are we spending more than $12,345.67 a year, or $1,200,000 in all?",
    "About $12k, or 12,000 dollars, at 12.5% and 4.25 %",
    "Between 2025 and 2026, and in 1999. Since 2020.",
    "Account 12, Account 13 and Person 2 paid Payee 1000",
    "If I put $500 more a month into the 401(k), when can we retire?",
    "We have 3 kids aged 7, 9 and 12",
    "Net worth 1,234,567 against 987,654",
    "If we save $1,500 a month until 2035 with $250,000 saved, can we retire at 62?",
    "Can Person 1 retire at 60 if we spend $6,000 a month and the market drops 20%?",
    "What if Account 3 earns 6% from 2027 to 2040?",
    "ages 7, 9, 12 and 15, born in 2011",
]


@pytest.mark.parametrize("text", KEPT)
def test_the_keep_list_survives(text):
    assert question_text(text, issued=ISSUED) == text
    assert is_question_safe(text, issued=ISSUED)


@pytest.mark.parametrize("text, want", [
    ("card 4111 1111 1111 1111", "card • 1111"),
    ("SSN 900-12-3456 please", "SSN •-3456 please"),
    ("acct 4111\u200b1111 1111 1111", "acct • 1111"),           # a zero-width space hides nothing
    ("call 714 555 0102", "call • 0102"),                          # small groups joined by spaces are one number
    ("number \uff11\uff12\uff13\uff14\uff15\uff16", "number •3456"),                      # full-width digits are digits
    ("Account 123456789 and $500.00", "Account •6789 and $500.00"),  # an alias needs 1 to 4 digits
])
def test_extra_digits_are_masked(text, want):
    assert question_text(text, issued=ISSUED) == want
    assert not is_question_safe(plain(text), issued=ISSUED)


# Every bypass the Task 3 security review named: a long number sent in kept pieces.
@pytest.mark.parametrize("text", [
    "Person 1234 Person 5678 Person 9012",          # alias digits that the NAS never issued
    "$4111 $1111 $1111 $1111",                      # dollar amounts joined only by spaces
    "2026 2027 2028 2029",                          # years joined only by spaces
    "12, 34, 56, 78",                               # small numbers joined by commas
    "1,234, 5,678, 9,012",                          # comma groups joined by commas
    "714,555,0102",                                 # a phone number with commas
    "714\u2010555\u20110102",                      # a phone number with Unicode hyphens
    "714\u2028555\u20280102",                      # a phone number with line separators
    "$41111111",                                    # a long number behind a dollar sign
    "Account 1;234;567",                            # an issued alias with digits after it
    "12% 34% 56% 78%",                              # percentages joined only by spaces
])
def test_numbers_sent_in_kept_pieces_are_masked(text):
    out = question_text(text, issued=frozenset({"Account 1"}))
    assert out != text
    assert sum(c.isdigit() for c in out) <= 4


def test_a_luhn_valid_card_is_masked_even_in_two_kept_pieces():
    card = "$4,111,111 $111,111,111"           # 4111111111111111 split into two dollar amounts
    assert luhn("4111111111111111")
    assert sum(c.isdigit() for c in question_text(card)) <= 4
    assert question_text("$4,111,111 $111,111,112") == "$4,111,111 $111,111,112"   # not a card number


def test_a_known_identifier_is_masked_whatever_the_keep_list_says():
    text = "is $90,012,345 the number?"
    assert question_text(text) == text
    assert sum(c.isdigit() for c in question_text(text, known=frozenset({"90012345"}))) <= 4


def test_issued_aliases_keep_their_digits_and_others_count():
    text = "Account 12, Account 13 and Person 2 paid Payee 1000"
    assert question_text(text, issued=ISSUED) == text
    assert question_text(text) == "Account 12, Account 13 and Person 2 paid Payee 1000"   # small numbers anyway
    big = "Account 1234 and Account 5678"
    assert question_text(big, issued={"Account 1234", "Account 5678"}) == big
    assert question_text(big) == "Account • and Account 5678"           # nothing issued: 8 digits count


def test_the_stored_path_has_no_keep_list():
    """Bank, inventory and stored text: at most 4 digits in all, whatever they look like (Task 3 ruling)."""
    for text in ("$1,500.00 at 2026", "Person 1234", "12, 34, 56", "Payee 7 on 03/14"):
        out = stored_text(text)
        assert sum(c.isdigit() for c in out) <= 4, text
        assert out == mask_numbers(text)
    assert stored_text("Way2Save savings") == "Way2Save savings"
    assert is_stored_safe("VTI") and not is_stored_safe("$12,345")


def test_the_stored_path_is_mask_numbers():
    rng = random.Random(20261022)
    alphabet = "0123456789" + "abcAB" + "  -./#$,%•" + "\u2010\u2028ß\u0663é"
    for _ in range(3000):
        s = plain("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 30))))
        assert apply(s, stored_edits(s))[0] == mask_numbers(s), repr(s)


def test_both_paths_are_idempotent():
    rng = random.Random(20261023)
    alphabet = "0123456789" * 3 + "abcPerson " + "  -./,$%•k" + "\u2010\u2028"
    for _ in range(3000):
        s = plain("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 40))))
        q = question_text(s, issued=ISSUED)
        assert question_edits(q, issued=ISSUED) == [], (s, q)
        assert sum(c.isdigit() for c in stored_text(s)) <= 4
        assert stored_edits(stored_text(s)) == []


def test_edits_are_computed_on_plain_text_only():
    with pytest.raises(ValueError):
        question_edits("Mar\u200bgaret 12345")
    with pytest.raises(ValueError):
        stored_edits("\uff11\uff12\uff13\uff14\uff15")


def test_a_date_of_birth_in_free_text_loses_its_year():
    out = question_text("she was born 1950-03-14")
    assert "1950" not in out and out.count("•") == 1


def test_numbers_joined_only_by_spaces_are_one_number():
    assert question_text("1234 $5.00 5678 $6.00 9012") == "• 9012"


def test_the_edits_reproduce_the_text():
    t = plain("call 714 555 0102 about Account 3 and $1,250.00")
    new, chips = apply(t, question_edits(t, issued=ISSUED))
    assert new == question_text(t, issued=ISSUED) == "call • 0102 about Account 3 and $1,250.00"
    assert [new[c["start"]:c["end"]] for c in chips] == ["•"]


def test_small_numbers_on_their_own_are_kept_but_not_when_letters_touch_them():
    assert question_text("a1b2c3d4e5f6") == "a•b•c3d4e5f6"


def test_mask_numbers_matches_present():
    assert mask_numbers("1234 5678 9012") == "• 9012"
    assert mask_numbers("Way2Save savings") == "Way2Save savings"


def test_the_old_names_are_the_question_path():
    assert outgoing_text is question_text and outgoing_edits is question_edits
    assert is_outgoing_safe("Since 2020, $1,500 a month.")


@pytest.mark.parametrize("kind, value, ok", [
    ("date", "2026-10-19", True), ("date", "2026-13-01", False), ("date", "2026-10-19T00:00", False),
    ("date", "\uff12\uff10\uff12\uff16-\uff11\uff10-\uff11\uff19", False), ("month", "2026-10", True), ("month", "2026-00", False),
    ("month", "\uff12\uff10\uff12\uff16-\uff11\uff10", False), (None, "Person 1", True), ("free_text", "VTI", True),
    ("free_text", "123456", False), ("free_text", "$12,345", False), (None, "$12,345 since 2020", True),
])
def test_typed_strings(kind, value, ok):
    assert typed_ok(kind, value) is ok


def test_typed_question_text_keeps_only_issued_alias_digits():
    assert typed_ok(None, "Account 1234 and Account 5678") is False
    assert typed_ok(None, "Account 1234 and Account 5678", issued=frozenset({"Account 1234", "Account 5678"}))


def test_a_string_that_isnt_plain_is_not_safe():
    assert not is_question_safe("Mar\u200bgaret")
    assert not is_stored_safe("Mar\u200bgaret")


def test_look_alike_letters_fold_to_latin_without_moving_offsets():
    from steward_boundary.text import fold
    disguised = "M" + chr(0x430) + "rg" + chr(0x430) + "r" + chr(0x435) + "t " + chr(0x41E) + "rtiz"
    assert fold(disguised) == "Margaret Ortiz" and len(fold(disguised)) == len(disguised)


@pytest.mark.parametrize("text, want", [
    ("she was born 03/14/1941 in Ohio", "she was born [date of birth] in Ohio"),
    ("DOB: 1950-03-14.", "DOB: [date of birth]."),
    ("date of birth is March 14, 1941", "date of birth is [date of birth]"),
    ("birthday 14 Mar 1941", "birthday [date of birth]"),
    ("paid on 03/14/2026", "paid on 03/14/2026"),
    ("she was born in 1941", "she was born in [date of birth]"),
    ("born 1941 in Ohio", "born [date of birth] in Ohio"),
    ("born March 1941", "born [date of birth]"),
    ("born in March, 1941.", "born in [date of birth]."),
    ("birth year 1941", "birth year [date of birth]"),
    ("born in '41", "born in [date of birth]"),
    ("since 2020", "since 2020"),
    ("paid in 2026", "paid in 2026"),
    ("she was born 03\u201014\u20101941", "she was born [date of birth]"),      # Unicode hyphens
    ("BORN   \uff10\uff13/\uff11\uff14/\uff11\uff19\uff14\uff11", "BORN   [date of birth]"),                     # case, spacing, full width
])
def test_a_date_of_birth_is_replaced_by_a_placeholder(text, want):
    from steward_boundary.text import dob_edits
    t = plain(text)
    assert apply(t, dob_edits(t))[0] == want


# A PIN, password or code is never sent, however short (click-through feedback, 2026-10-25: "Here's my pin for my
# debit card 1111" went out as written, because the question rule lets 4 digits leave).
@pytest.mark.parametrize("text, want", [
    ("Here's my pin for my debit card 1111", "Here's my pin for my debit card [secret]"),
    ("My PIN is 4821.", "My PIN is [secret]."),
    ("PIN: 0042, is that weak?", "PIN: [secret], is that weak?"),
    ("pin number 12 34", "pin number [secret]"),
    ("my pin is one one one one", "my pin is [secret]"),
    ("the CVV is 123", "the CVV is [secret]"),
    ("CVC 0987 on the Visa", "CVC [secret] on the Visa"),
    ("the security code on the back is 4410", "the security code on the back is [secret]"),
    ("access code 7731", "access code [secret]"),
    ("the access code is 77", "the access code is [secret]"),
    ("verification code: 551 902", "verification code: [secret]"),
    ("the one-time code was 8812", "the one-time code was [secret]"),
    ("the last four of my social are 3456", "the last four of my social are [secret]"),
    ("last 4 of Mom's SSN is 6789", "last 4 of Mom's SSN is [secret]"),
    ("my password is hunter2", "my password is [secret]"),
    ("Password: Tr0ub4dor&3, did I use it for Chase?", "Password: [secret], did I use it for Chase?"),
    ("the passcode is fluffy.", "the passcode is [secret]."),
    ("1111 is my PIN", "[secret] is my PIN"),
    ("4821 was the code for the debit card's PIN", "[secret] was the code for the debit card's PIN"),
    ("MY ＰＩＮ IS １１１１", "MY ＰＩＮ IS [secret]"),   # full width
    ("PIN=1111", "PIN=[secret]"),
    ("PIN#1111 for the Chase card", "PIN#[secret] for the Chase card"),
    ("PIN1111", "PIN[secret]"),
    ("password=hunter2", "password=[secret]"),
    ("my pin is 1-1-1-1", "my pin is [secret]"),
    ("my pin is 1 1 1 1", "my pin is [secret]"),
    ("my PIN for account 4417 is 8812", "my PIN for account [secret] is [secret]"),
])
def test_a_pin_password_or_code_is_replaced_by_a_placeholder(text, want):
    from steward_boundary.text import secret_edits
    t = plain(text)
    assert apply(t, secret_edits(t))[0] == plain(want)


# The adversarial review of the first rule (2026-10-25): each of these sent its secret, or part of it.
@pytest.mark.parametrize("text, secrets", [
    ("my pin for the debit card at chase bank is 1111", ["1111"]),
    ("the PIN I use at the ATM, which I set in 2019, is 1111", ["1111"]),
    ("my pin, which I have never changed since then, is 1111", ["1111"]),
    ("my pin for the debit card at the chase bank branch downtown is 1111", ["1111"]),
    ("PIN for debit card ending in 4567 is 1111", ["1111"]),
    ("the pin to my debit card ending in 4567 is 1111", ["1111"]),
    ("pin 1111 and 2222 and 3333 and 4444 and 5555 and 6666 and 7777", ["1111", "4444", "7777"]),
    ("my pin: 1111 / wife's: 2222 / kid's: 3333 / mom's: 4444", ["1111", "2222", "3333", "4444"]),
    ("the pin is either 1111 or maybe 1121 or possibly 1211 but could be 2111", ["1111", "1121", "1211", "2111"]),
    ("my pin is 1111 and my wife's is 2222", ["1111", "2222"]),
    ("my pin is 1 1 1 1 and the other is 2 2 2 2", ["1 1 1 1", "2 2 2 2"]),
    ("I use 1111 as my pin", ["1111"]),
    ("I use 1111 for my pin", ["1111"]),
    ("1111, my pin", ["1111"]),
    ("is 1111 my pin?", ["1111"]),
    ("hunter2 is my password", ["hunter2"]),
    ("I use hunter2 as my password", ["hunter2"]),
    ("fluffy is my password", ["fluffy"]),
    ("my password is correct horse battery staple", ["correct", "horse", "battery", "staple"]),
    ("my password is New York", ["New", "York"]),
    ("my password is My Dog", ["Dog"]),
    ("my pin is 1 - 1 - 1 - 1", ["1 - 1 - 1 - 1"]),
    ("pin is 1 1 - 1 1", ["1 1 - 1 1"]),
    ("pin is 1 o 1 o", ["1 o 1 o"]),
    ("pin is 1 1 1 1 1 1 1", ["1 1 1 1 1 1 1"]),
    ("my pin is one-one-one-one", ["one-one-one-one"]),
    ("pin is one–one–one–one", ["one"]),
    ("my pin? 1111", ["1111"]),
    ("my pin!! 1111", ["1111"]),
    ("pin... 1111", ["1111"]),
    ("my ssn ends in 3456", ["3456"]),
    ("ssn last 4: 3456", ["3456"]),
    ("SSN last 4 is 3456", ["3456"]),
    ("last 4 ssn 3456", ["3456"]),
    ("my SSN last four are 3456", ["3456"]),
    ("my social ends in 3456", ["3456"]),
    ("my ssn is xxx-xx-3456", ["3456"]),
    ("my social is ***-**-3456", ["3456"]),
    ("the 3-digit code on the back is 317", ["317"]),
    ("the code on the back of the card is 317", ["317"]),
    ("the code is 482913", ["2913"]),
    ("the two-factor code is 482913", ["2913"]),
    ("the authentication code is 482913", ["2913"]),
    ("the auth code is 482913", ["2913"]),
    ("the signin code is 482913", ["2913"]),
    ("the text code was 482913", ["2913"]),
    ("my gate code is 4821", ["4821"]),
    ("the door code is 4821", ["4821"]),
    ("the alarm code is 4821", ["4821"]),
    ("the safe combination is 12-34-56", ["12-34-56", "56"]),
    ("my pwd is hunter2", ["hunter2"]),
    ("my pw is hunter2", ["hunter2"]),
    ("pw: hunter2", ["hunter2"]),
    ("pin is eleven eleven", ["eleven"]),
    ("my pin is twelve thirty four", ["twelve", "thirty"]),
    ("p.i.n. is 1111", ["1111"]),
    ("P I N is 1111", ["1111"]),
    # Argon's review of the second rule (2026-10-25).
    ("My debit card PIN is 1099.", ["1099"]),
    ("My debit card has a PIN of 1984.", ["1984"]),
    ("My PIN ends in 1984", ["1984"]),
    ("I changed my PIN from 1984 to 5678", ["1984", "5678"]),
    ("I changed my bank password to correct horse battery staple.", ["correct", "horse", "battery", "staple"]),
    ("My bank password is still correct horse battery staple.", ["correct", "horse", "battery", "staple"]),
    ("My passphrase is the quick brown fox.", ["quick", "brown", "fox"]),
    ("My ATM PIN is one - one - one - one.", ["one"]),
    ("My PIN for U.S. Bank is 1234.", ["1234"]),
    ("My PIN no. is 1234.", ["1234"]),
    ("My debit card PIN is 1234, try checking why the charge failed.", ["1234"]),
    ("My PIN is 1234 (card ending in 5678)", ["1234"]),
    ("sunshine is my online banking password.", ["sunshine"]),
    ("correct horse battery staple is my password.", ["correct", "horse", "battery", "staple"]),
    # The second adversarial round (2026-10-25).
    ("My PIN? It's 1111.", ["1111"]),
    ("Here's my pin. It's 1111.", ["1111"]),
    ("My pin? I think 1111", ["1111"]),
    ("My pin? Probably 1111 or 1121", ["1111", "1121"]),
    ("pin... it's 1111", ["1111"]),
    ("Password? fluffy.", ["fluffy"]),
    ("I have a new password. It's fluffy.", ["fluffy"]),
    ("the code? 4 digits: 5821", ["5821"]),
    ("my pin no. 1111", ["1111"]),
    ("PIN No. 1111 for the Chase card", ["1111"]),
    ("the pin for my chase acct. is 1111", ["1111"]),
    ("my pin, i.e. the 4 digits, is 1111", ["1111"]),
    ("my pin is ... 1111", ["1111"]),
    ("my pin is… 1111", ["1111"]),
    ("my pins: 1111; 2222; 3333", ["1111", "2222", "3333"]),
    ("codes: chase=1111; bofa=2222", ["1111", "2222"]),
    ("I changed my password to fluffy", ["fluffy"]),
    ("set my password to Fluffy", ["fluffy"]),
    ("the password was reset to fluffy", ["fluffy"]),
    ("is my password fluffy?", ["fluffy"]),
    ("is my password still fluffy or fluffy2?", ["fluffy"]),
    ("is fluffy my password?", ["fluffy"]),
    ("I use fluffy as my password", ["fluffy"]),
    ('my password "fluffy" is weak', ["fluffy"]),
    ("my password (fluffy) is weak", ["fluffy"]),
    ("my password fluffy got leaked", ["fluffy"]),
    ("username jr password fluffy", ["fluffy"]),
    ("Password\nfluffy", ["fluffy"]),
    ("pw fluffy", ["fluffy"]),
    ("User: jr\nPass: fluffy", ["fluffy"]),
    ("my pass is fluffy", ["fluffy"]),
    ("my pin is 1040", ["1040"]),
    ("pin 1040", ["1040"]),
    ("my pin is 1099", ["1099"]),
    ("the code is 1120", ["1120"]),
    ("my pin is 1984 year I was born", ["1984"]),
    ("my pin is 0507 month and day", ["0507"]),
    ("pin is 1111 dollars", ["1111"]),
    ("my pin 2580 card", ["2580"]),
    ("my pin is from 1984", ["1984"]),
    ("my pin of 1984", ["1984"]),
    ("my pin is one then one then one then one", ["one then one"]),
    ("my pin is one, then one, then one, then one", ["one, then one"]),
    ("my pin is one thousand one hundred and eleven", ["eleven", "hundred"]),
    ("pin first 1 then 2 then 3 then 4", ["1 then 2 then 3 then 4"]),
    ("I use 1111 for the chase debit card as my pin", ["1111"]),
    ("1111 is what I use at the ATM for my pin", ["1111"]),
    ("I've used 1111 on all three cards as the pin", ["1111"]),
    ("1111. That's my pin.", ["1111"]),
    ("1111; my pin", ["1111"]),
    ("pincode 1111", ["1111"]),
    ("my pincode is 1111", ["1111"]),
    ("my passwrod is fluffy", ["fluffy"]),
    ("my pasword is fluffy", ["fluffy"]),
    ("my passowrd is fluffy", ["fluffy"]),
    ("SS number ends in 3456", ["3456"]),
    ("my soc sec ends in 3456", ["3456"]),
    ("my secret number is 1111", ["1111"]),
    ("my social is xx-xxx-3456", ["3456"]),
    # The harness rerun (2026-10-25).
    ("I changed my pin yesterday. The new one is 1111.", ["1111"]),
    ("I use fluffy for my password", ["fluffy"]),
    ("fluffy's my password", ["fluffy"]),
    ("my pinn is 1111", ["1111"]),
    ("my p1n is 1111", ["1111"]),
    ("my social is 3456", ["3456"]),
    ("the code is 4 digits 5821", ["5821"]),
    ("the code is a 4-digit one, 5821", ["5821"]),
    ("the four digit code 5821 for the door", ["5821"]),
    ("ssn 123-45-6789", ["6789"]),
    ("SSN: 123 45 6789", ["6789"]),
    ("my pin is 1111.5", ["1111"]),
    # Argon's review of the third rule (2026-10-25).
    ("I typed in 1984 for my PIN on the checking account.", ["1984"]),
    ("My password for checking and savings is Summer26.", ["summer26"]),
    ("I changed my online banking account password to Summer26.", ["summer26"]),
    ("My debit card PIN is 12.34 for ATM withdrawals.", ["12.34"]),
    ("The code's 4821 for my safe deposit box.", ["4821"]),
    ("1 1 1 1. That's my PIN.", ["1 1 1 1"]),
    ("CorrectHorse is my password and I still can't log into my account.", ["correcthorse"]),
    # The security review of that change (2026-10-25): the next sentence is read again after a full stop.
    ("My CVV. Use 1111.", ["1111"]),
    ("The access code. Try 1111.", ["1111"]),
    ("Our garage code. We use 1111.", ["1111"]),
    ("My PIN. Mine is 1111.", ["1111"]),
    ("My password. Try fluffy2024.", ["fluffy2024"]),
    ("My password. Value: 1111.", ["1111"]),
    ("My password. Use fluffy.", ["fluffy"]),
    ("My password. Sunshine.", ["sunshine"]),
    ("My pw. hunter2.", ["hunter2"]),
    ("Login password. Fluffy for both.", ["fluffy"]),
    ("My passcode. Probably fluffy.", ["fluffy"]),
    ("my password for the card of sunshine", ["sunshine"]),
])
def test_no_pin_password_or_code_survives(text, secrets):
    from steward_boundary.text import secret_edits
    t = plain(text)
    out = apply(t, secret_edits(t))[0].casefold()
    for s in secrets:
        assert s.casefold() not in out, out


class _Counted:
    """A compiled pattern that adds the characters each call hands it to a tally."""

    def __init__(self, rx: re.Pattern, tally: list[int]) -> None:
        self._rx, self._tally = rx, tally

    def __getattr__(self, name: str):
        method = getattr(self._rx, name)

        def counted(*args, **kwargs):
            if name in ("search", "match", "fullmatch", "finditer", "findall"):
                string = args[0] if args else kwargs["string"]
                pos = args[1] if len(args) > 1 else kwargs.get("pos", 0)
                end = args[2] if len(args) > 2 else kwargs.get("endpos", len(string))
                self._tally[0] += max(0, min(end, len(string)) - pos)
            else:
                self._tally[0] += sum(len(a) for a in (*args, *kwargs.values()) if isinstance(a, str))
            return method(*args, **kwargs)
        return counted


def _secret_work(text: str) -> int:
    """The work secret_edits does on `text`, counted instead of timed: the calls into the boundary's own code (a
    generator counts each step, so reading a word letter by letter counts too), the characters handed to its
    patterns, and the characters it reads out of the text."""
    import cProfile
    import dataclasses
    import pstats

    from steward_boundary import text as T
    from steward_boundary.normal import view
    tally = [0]

    class Read(str):
        def __getitem__(self, key):
            got = str.__getitem__(self, key)
            tally[0] += len(got)
            return got
    v = view(text)
    v = dataclasses.replace(v, norm=Read(v.norm))
    with pytest.MonkeyPatch.context() as mp:
        for name, value in list(vars(T).items()):
            if isinstance(value, re.Pattern):
                mp.setattr(T, name, _Counted(value, tally))
        profile = cProfile.Profile()
        profile.runcall(T.secret_edits, v)
    calls = sum(stat[1] for (file, _, _), stat in pstats.Stats(profile).stats.items() if "steward_boundary" in file)
    return calls + tally[0]


@pytest.mark.parametrize("chunk", ["1 ", "1234 ", "one ", "pin 1 ", "1111 is my pin ", "password is a ", "pin#",
                                   "pin1111/", "code-pin-", "1111#pin "])
def test_the_secret_rule_is_linear_on_long_text(chunk):
    """Four times the text does about four times the work; a quadratic scan would do sixteen. The work is counted,
    not timed, so a busy machine can't fail it (the wall-clock check is tests/perf/test_boundary_budgets.py)."""
    short, long = chunk * (2000 // len(chunk)), chunk * (8000 // len(chunk))
    a, b = _secret_work(short), _secret_work(long)
    assert b < 5 * a, (a, b, b / a)


def test_the_work_counter_reads_pos_and_endpos_however_passed():
    tally = [0]
    rx = _Counted(re.compile(r"\d"), tally)
    rx.search("abc123", 2)
    rx.search("abc123", pos=4)
    rx.finditer("abc123", 1, 3)
    rx.fullmatch(string="abc123", endpos=2)
    assert tally == [4 + 2 + 2 + 2]


# Secret words glued to a neighbour ("gate-code", "x#pin", ".code") read the same words around them as ecad483 did
# (a differential review of the first linear version, 2026-11-01).
A_ = "a "


@pytest.mark.parametrize("text, secrets", [
    ("4821 is the gate-code", ["4821"]),
    ("4821 is the door/code", ["4821"]),
    ("123456 is the 2fa-code", ["123456"]),
    ("0000 is the lock-combination", ["0000"]),
    ("1111. That's my debit-pin.", ["1111"]),
    ("since 1984 for my phone-pin", ["1984"]),
    ("four eight two one is the gate-code", ["four eight two one"]),
    ("pin " + A_ * 37 + "code#x a 1111", ["1111"]),
    ("1111 " + A_ * 10 + "code#x pin", ["1111"]),
    ("1111 " + A_ * 11 + "x#pin", ["1111"]),
    ("1111 is the .code pin", ["1111"]),
    ("pin#12#code34", ["12", "34"]),
    ("pin#1#pin#2#pin#3", ["1", "2", "3"]),
])
def test_a_glued_secret_word_reads_its_neighbours_as_before(text, secrets):
    from steward_boundary.text import secret_edits
    t = plain(text)
    out = apply(t, secret_edits(t))[0].casefold()
    for s in secrets:
        assert s.casefold() not in out.replace("[secret]", " "), out


def _secret_inputs(count: int, seed: int) -> list[str]:
    """Small texts shaped like the ones the secret rule finds hard: secret words glued to a neighbour on either side,
    several words, values at the window edges, spoken and full-width digits, punctuation and odd case."""
    rnd = random.Random(seed)
    words = ["pin", "PIN", "Pin", "password", "pw", "code", "security code", "ssn", "cvv", "passcode", "pass",
             "combination", "social", "otp", "p.i.n.", "gate-code", "debit-pin", "2fa-code"]
    values = ["1111", "4821", "12", "123", "1984", "one two three four", "four eight two one", "nine", "$50", "3",
              "2024", "fluffy", "hunter2", "１２３４", "07734", "123456"]
    filler = ["a", "is", "my", "the", "for", "was", "it's", "That's", "x", "and", "to", "of", "use", ".", ",", "?",
              "changed", "card", "debit", "bank", "number", "ends", "in", "since", "gate", "—", "é", "times", "new",
              "one"]
    glue = ["", "#", ":", "-", "/", "=", "", "", "x#", "1111", "_", ".", "x-", "("]
    out = []
    for _ in range(count):
        parts = []
        for _ in range(rnd.randint(1, 16)):
            r = rnd.random()
            tok = rnd.choice(words) if r < .25 else rnd.choice(values) if r < .45 else rnd.choice(filler)
            if rnd.random() < .25:
                tok = rnd.choice(glue) + tok
            if rnd.random() < .25:
                tok += rnd.choice(glue)
            if rnd.random() < .15:
                tok += rnd.choice(glue) + rnd.choice(words)       # a secret word glued on its right
            if rnd.random() < .2:
                tok = tok.upper() if rnd.random() < .5 else tok.title()
            parts.append(tok)
        if rnd.random() < .25:                                      # out to the window edges
            i = rnd.randrange(len(parts) + 1)
            parts[i:i] = ["a"] * rnd.choice([9, 10, 11, 12, 35, 36, 37, 38, 39, 40])
        out.append(plain(rnd.choice([" ", "  ", "\n", " \t "]).join(parts)))
    return out


def _glued_inputs(count: int, seed: int) -> list[str]:
    """Small texts with one token of 9 to 15 secret words glued together, more than the rule reads one by one."""
    rnd = random.Random(seed)
    words = ["pin", "code", "pw", "password", "cvv", "ssn", "combination", "otp", "passcode"]
    glue = ["#", "-", "/", ".", "_", "#1", "-12", "/123", "#fluffy", ".4"]
    filler = ["is", "my", "a", "1111", "12", "fluffy", "1", "2", "3", "the", ".", "That's", "changed", "to"]
    out = []
    for _ in range(count):
        tok = rnd.choice(words) + "".join(rnd.choice(glue) + rnd.choice(words) for _ in range(rnd.randint(8, 14)))
        if rnd.random() < .5:
            tok += rnd.choice(glue)
        left = [rnd.choice(filler) for _ in range(rnd.randint(0, 14))]
        right = [rnd.choice(filler) for _ in range(rnd.randint(0, 44))]
        out.append(plain(" ".join([*left, tok, *right])))
    return out


def _covered(edits) -> set[int]:
    return {i for e in edits for i in range(e.start, e.end)}


def test_the_secret_rule_matches_ecad483_wherever_a_token_holds_8_secret_words_or_fewer():
    """ecad483's rule is frozen in _secret_edits_ecad483.py. The live rule makes exactly its edits until a token holds
    more secret words than it reads one by one."""
    from steward_boundary.text import secret_edits

    from tests.boundary._secret_edits_ecad483 import secret_edits as old_secret_edits
    differ = [t for t in _secret_inputs(3000, seed=20261101) if secret_edits(t) != old_secret_edits(t)]
    assert not differ, f"{len(differ)} texts differ, e.g. {differ[:5]}"


def test_the_secret_rule_never_redacts_less_than_ecad483():
    """Every character ecad483's rule redacts, the live rule redacts too: a token with too many glued secret words
    fails closed instead."""
    from steward_boundary.text import secret_edits

    from tests.boundary._secret_edits_ecad483 import secret_edits as old_secret_edits
    lost = []
    for t in _secret_inputs(1000, seed=1) + _glued_inputs(1000, seed=5):
        gone = _covered(old_secret_edits(t)) - _covered(secret_edits(t))
        if gone:
            lost.append((t, "".join(t[i] for i in sorted(gone))))
    assert not lost, f"{len(lost)} texts lose redaction, e.g. {lost[:5]}"


@pytest.mark.parametrize("text, kept", [
    ("pin#code#cvv#pin#code#cvv#pw#pin#code#cvv#pin#code is fluffy", ["fluffy"]),
    ("pin#code#cvv#pin#code#pw#cvv#pin#code#cvv#pin#code is correct horse", ["correct horse"]),
])
def test_a_token_of_12_glued_secret_words_redacts_at_full_reach(text, kept):
    """12 secret words in one token: the middle 4 aren't read one by one, so all they could have read goes, and
    with it the values ecad483's rule took after them (here only the password word in the middle takes them)."""
    from steward_boundary.text import SECRET_RE, secret_edits

    from tests.boundary._secret_edits_ecad483 import secret_edits as old_secret_edits
    t = plain(text)
    assert len(list(SECRET_RE.finditer(t))) == 12
    old, new = apply(t, old_secret_edits(t))[0], apply(t, secret_edits(t))[0]
    for s in kept:
        assert s not in old and s not in new, (old, new)
    assert _covered(old_secret_edits(t)) <= _covered(secret_edits(t))


# Ordinary questions that mention a PIN or a password keep their numbers.
@pytest.mark.parametrize("text", [
    "How much did we spend on PIN purchases at Target in 2025?",
    "Were there any PIN debit charges over $50 in March?",
    "I forgot my password, how do I reset it?",
    "My password is not working since the 3rd.",
    "I changed my PIN. Can we retire at 62?",
    "Does a new password change the $500 transfer or the 4% rate?",
    "Is the spinning class 45 dollars a month?",
    "Can we save 529 money for 2 kids?",
    "I used my pin 3 times this week",
    "A 4 digit pin, or a 4-digit pin?",
    "I changed my password 3 times in 2024",
    "My password expires in 30 days.",
    "Do I need my SSN for the 1099?",
    "Is my SSN on the W-2 and the 401(k) form?",
    "When can we claim Social Security if we stop working at 62?",
    "Does the tax code let us deduct 20% of it?",
    "What's the zip code for the 2025 return?",
    "What combination of 529 and Roth IRA contributions makes sense for 2026?",
    # The second adversarial round (2026-10-25).
    "Is a combination of VTI and BND at 60/40 good?",
    "What combination of 3 funds should we hold until 2040?",
    "Is a combination of 401k and Roth contributions of 500 a month enough?",
    "My card got declined with code 05, what does that mean?",
    "The ACH payment came back with return code R01 for $450",
    "Response code 51 on the Visa, is the card blocked?",
    "The merchant code 5411 is grocery, right?",
    "Can we expense the truck under code section 179?",
    "Is a 1031 exchange under the Internal Revenue Code worth it for 2 rentals?",
    "Can they ask for my SSN at age 65?",
    "Do I need my Social Security number for the 1099 at age 62?",
    "Should we lock our Social Security numbers before the kids turn 18?",
    "Is my SSN needed for the 2025 return?",
    "Do I need my SSN for 2 forms?",
    "my social security number was leaked in the 2017 Equifax breach",
    "Did we pay the $35 pin reset fee twice in Q3?",
    "Does the password reset affect my 401k withdrawal?",
    "I have 12 passwords to manage, is 1Password worth $36 a year?",
    "Which password manager is cheaper, 1Password or Bitwarden?",
    "The pin on the map shows 3 branches within 5 miles",
    "How much did the 12 pins for the sewing kit cost?",
    "Is the PIN-less debit fee 0.25 per transaction?",
    "Is a 6 digit pin safer than 4?",
    "Does my password need 2 numbers and 1 symbol?",
    "my question is about password managers",
    "the problem is my password keeps expiring",
    "the issue is the password reset fee of $5",
    "Our Social Security is 2400 a month, can we retire?",
    "My pin got declined on 10/12 at the Target on 5th",
    "Does the chip and pin terminal fee of 2.50 apply at the farmers market?",
    "The password must be 8-12 characters, is that normal?",
    "Did the OTP fee of 0.10 per text add up to 12 last year?",
    "Is the password 3 years old now?",
    "Passwords cost us nothing but 1Password costs 36",
    "Is social media spending 300 a month too much?",
    # Argon's review of the third rule (2026-10-25).
    "My password's expired, so how do I check my 401(k) balance?",
    "My password doesn't work for my 401(k) rollover.",
    "I forgot my password. Please check my savings balance.",
    "I changed my PIN. Can we retire at 62 with $4,500 a month?",
])


def test_ordinary_questions_about_pins_keep_their_numbers(text):
    from steward_boundary.text import secret_edits
    assert secret_edits(plain(text)) == []


def test_a_question_after_a_password_word_keeps_its_words():
    from steward_boundary.text import secret_edits
    t = "I forgot my password, so what is my checking account balance?"
    assert apply(t, secret_edits(t))[0] == t
    t = "my pin is 1111 and pw fluffy"
    assert apply(t, secret_edits(t))[0] == "my pin is [secret] and pw [secret]"


# The spelled-digits rule (ruling 28) lives in the boundary, so the gateway's text check holds without the NAS
# (privacy approach review, 2026-10-24).
@pytest.mark.parametrize("text, want", [
    ("Use nine zero zero one two three four five six for the tax form.", "Use [number] for the tax form."),
    ("Is Eight eight one two zero three four five six seven one the joint account?",
     "Is [number] the joint account?"),
    ("card four-one-one-one, one one one one, one", "card [number]"),
    ("call oh seven one four five", "call [number]"),
])
def test_five_or_more_spelled_digits_are_a_number(text, want):
    assert question_text(text) == want
    assert not is_question_safe(text) and is_question_safe(want)
    assert not typed_ok(None, text)


def test_four_spelled_digits_and_ordinary_words_are_kept():
    for text in ("one two three four", "We have one, two or three kids", "Someone said nine; then one more"):
        assert question_text(text) == text


def test_spelled_edits_name_the_run():
    from steward_boundary.text import SPELLED_RE, spelled_edits
    assert SPELLED_RE.search("nine zero zero one two")
    assert [(e.start, e.end, e.label) for e in spelled_edits("Use nine zero zero one two now")] == [
        (4, 26, "[number]")]


def _digits_left(text: str) -> int:
    """Digits a text still carries, written as digits or as digit words."""
    words = re.findall(r"(?<![\w])(?:zero|one|two|three|four|five|six|seven|eight|nine|oh)(?![\w])", text.casefold())
    return sum(c.isdigit() for c in text) + len(words)


def test_the_stored_path_replaces_spelled_digits_too():
    """Path 1 is the hard boundary: a bank name holding a spelled-out number is a number there too (final review F1)."""
    text = "ZELLE TO NINE ZERO ZERO ONE TWO THREE FOUR"
    assert not is_stored_safe(text) and not typed_ok("free_text", text)
    assert stored_text(text) == "ZELLE TO [number]"
    assert is_stored_safe("ZELLE TO [number]") and typed_ok("free_text", "ZELLE TO [number]")
    assert stored_text("ONE TWO THREE FOUR CAFE") == "ONE TWO THREE FOUR CAFE"


@pytest.mark.parametrize("text, want", [
    # Any stretch with no letter or digit in it joins digit words, as it joins digits (final review F2).
    ("nine zero zero / one two / three four five six", "[number]"),
    ("nine.zero.zero.one.two", "[number]"),
    ("nine_zero_zero_one_two", "[number]"),
    ("nine zero zero (one two) three four five six", "[number]"),
    ("call nine zero zero # one two three", "call [number]"),
    # So does a spoken joining word: dictation writes these.
    ("nine zero zero and one two three four five six", "[number]"),
    ("nine zero zero zero and one two three four", "[number]"),
    ("four four one seven, then zero zero two nine", "[number]"),
    ("nine zero zero dash one two dash three four five six", "[number]"),
])
def test_spelled_digits_joined_by_any_separator_are_one_number(text, want):
    assert question_text(text) == want
    assert stored_text(text) == want
    assert not is_question_safe(text) and not typed_ok(None, text) and not typed_ok("free_text", text)


def test_digit_words_in_ordinary_sentences_are_kept():
    for text in ("one and two", "We have one, two or three kids", "Someone said nine; then one more",
                 "one or two and three or four", "Is one / two better than three?", "one and two and three"):
        assert question_text(text) == text, text


@pytest.mark.parametrize("text, want", [
    # Digit words are tokens of a number chain, so a number half in words and half in digits is one number (final
    # review F6): the words become "[number]" and the digits are masked as usual.
    ("nine zero zero 12 3456", "[number] • 3456"),
    ("SSN nine zero zero-12-3456 ok", "SSN [number]-•-3456 ok"),
    ("Use 900 one two 3456", "Use • [number] 3456"),
])
def test_a_number_half_in_words_and_half_in_digits_is_one_number(text, want):
    out = question_text(text)
    assert out == want and _digits_left(out) <= 4
    assert not is_question_safe(text) and is_question_safe(out, issued={"[number]"})
    assert stored_text(text) == want


def test_a_known_number_half_in_words_is_masked():
    """Two tokens aren't a chain, but a known identifier's digits across words and digits are masked all the same."""
    assert question_text("nine 00123 ok") == "nine •0123 ok"
    assert question_text("nine 00123 ok", known={"900123"}) == "[number] •0123 ok"


@pytest.mark.parametrize("text", [
    "Should we make two $1,200 payments?", "one 401(k) and two IRAs", "We'll be 62 one year and 63 the next",
    "ages one, 3 and 5", "Is one 2026 trip too many?",
])
def test_a_digit_word_beside_a_small_number_is_kept(text):
    assert question_text(text) == text
