from datetime import date, datetime, timezone

import pytest

from steward.inventory import kinds as K
from steward.inventory.present import (
    article, clean_account, log_safe, mask_numbers, safe_line, scrub_text, day_label, joined, last4_of, long_label, mask, month_year, ordinal, short_ref, size_label, spelled, usd,
    when_label,
)

TODAY = date(2026, 10, 18)


@pytest.mark.parametrize("cents,text", [(0, "$0.00"), (821455, "$8,214.55"), (-118240, "−$1,182.40"),
                                        (118046225, "$1,180,462.25")])
def test_usd(cents, text):
    assert usd(cents) == text


@pytest.mark.parametrize("n,text", [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"),
                                    (13, "13th"), (21, "21st"), (22, "22nd"), (23, "23rd"), (31, "31st")])
def test_ordinal(n, text):
    assert ordinal(n) == text


def test_dates():
    assert day_label(date(2026, 3, 1), TODAY) == "Mar 1"
    assert day_label(date(2025, 2, 14), TODAY) == "Feb 14, 2025"
    assert month_year(date(2025, 2, 14)) == "Feb 2025"
    # 13:10 UTC is 6:10 AM in Los Angeles in October (PDT)
    assert when_label(datetime(2026, 10, 18, 13, 10, tzinfo=timezone.utc), TODAY) == "today, 6:10 AM"
    assert when_label(datetime(2026, 10, 12, 20, 5, tzinfo=timezone.utc), TODAY) == "Oct 12, 1:05 PM"


def test_numbers_and_labels():
    assert last4_of("GM-55120-0861") == "0861"
    assert last4_of("ab 12c") == "B12C"
    assert last4_of("--") is None
    assert mask("4417") == "••4417" and mask(None) is None
    assert long_label("Traditional IRA", "Fidelity", "3390") == "Fidelity Traditional IRA ••3390"
    assert long_label("Citi card", "Citi", "9012") == "Citi card ••9012"
    assert long_label("House", None, None) == "House"
    assert short_ref("Joint checking", "Wells Fargo", "4417") == "Wells Fargo ••4417"
    assert short_ref("Social Security", None, None) == "Social Security"


def test_words():
    assert size_label(412 * 1024) == "412 KB" and size_label(1_887_437) == "1.8 MB" and size_label(10) == "1 KB"
    assert article("annuity") == "an" and article("pension") == "a" and article("RMD") == "an"
    assert joined([]) == "" and joined(["A"]) == "A" and joined(["A", "B"]) == "A and B"
    assert joined(["A", "B", "C"]) == "A, B and C"
    assert spelled(2) == "Two" and spelled(12) == "12"


def test_the_parents_name_comes_from_the_first_owner_label():
    from steward.inventory.present import parent_name, possessive
    assert parent_name(["Margaret", "Robert (husband)", "Joint"]) == "Margaret"
    assert parent_name(["Margaret Ann", "Joint"]) == "Margaret"
    assert parent_name(["", "Joint"]) == "Joint" and parent_name([]) == "this person"
    assert possessive("Margaret") == "Margaret's" and possessive("Venus") == "Venus's"


def test_monthly_cents_rounds_each_item_half_up():
    assert K.monthly_cents(146000, "yearly") == 12167        # $1,460.00 a year is $121.67 a month
    assert K.monthly_cents(21200, "monthly") == 21200
    assert K.monthly_cents(30000, "quarterly") == 10000
    assert K.monthly_cents(None, "monthly") is None and K.monthly_cents(100, None) is None


def test_type_labels():
    assert K.type_label("insurance", "long_term_care") == "Long-term care"
    assert K.type_word("insurance", "long_term_care") == "long-term care"
    assert K.type_word("account", "cd") == "CD"
    assert K.type_label("account", "nope") is None


def test_a_contact_reads_name_then_firm():
    """Part 2's parked item: the document page showed "Park & Reyes Law Linda Park" with no separator."""
    assert long_label("Linda Park", "Park & Reyes Law", None, kind="contact") == "Linda Park, Park & Reyes Law"
    assert long_label("Linda Park", None, None, kind="contact") == "Linda Park"
    assert long_label("Traditional IRA", "Fidelity", "3390", kind="account") == "Fidelity Traditional IRA ••3390"


def test_the_document_page_names_who_prepared_it(margaret, mdb, mctx, books):
    from datetime import date
    from sqlalchemy import select
    from steward.db.models import InventoryItem
    from steward.demo_parent import seed_parent
    from steward.inventory.views import item_detail, load
    seed_parent(mdb, date(2026, 10, 18), by=mctx.user_id)
    L = load(mdb, {"margaret": "Margaret", "joint": "Joint"})
    poa = mdb.scalar(select(InventoryItem).where(InventoryItem.name == "Durable power of attorney"))
    detail = item_detail(mdb, L, poa, date(2026, 10, 18), books.directory)
    assert detail["refs"]["prepared_by_id"]["label"] == "Linda Park, Park & Reyes Law"


@pytest.mark.parametrize("name, last4, clean", [
    ("Everyday Checking ...4417", "4417", "Everyday Checking"),
    ("Checking-000123456789", "6789", "Checking"),
    ("Checking123456789", "6789", "Checking"),
    ("Everyday Checking123456789", "6789", "Everyday Checking"),
    ("Checking 123456789", "6789", "Checking"),
    ("Checking 123456789", None, "Checking •6789"),
    ("12345678 Savings", "6789", "•5678 Savings"),
    ("Way2Save savings", "2345", "Way2Save savings"),
    ("Joint checking", None, "Joint checking"),
])
def test_clean_account_keeps_the_last_four_and_trims_a_repeat_of_the_stored_one(name, last4, clean):
    assert clean_account(name, last4) == clean


LEAKS = [
    "1234 5678 9012", "1234-5678-9012-3456", "acct# 12 3456 7890", "XXXX-XXXX-1234-5678", "4929.3813.7264.5019",
    "CHK123456789", "1234,5678,9012,3456", "1234|5678|9012", "1234:5678:9012", "1234+5678+9012",
    "1234 \u2013 5678 \u2013 9012", "12\u200b34\u200b5678\u200b9012", "acct 1234~5678~9012", "1234  5678 9012",
    "1234ab5678cd9012", "Chk,5678,9012,3456", "$1234567890123456", "Oct 17 1234567890",
    "\uff14\uff19\uff12\uff19\u3000\uff13\uff18\uff11\uff13\uff0d\uff17\uff12\uff16\uff14\uff0d\uff15\uff10\uff11\uff19",
    "1234/5678/9012", "12/34/56/7890", "4929_3813_7264_5019", "card \u2022\u2022\u2022\u20225019 4929",
    "\u0664\u0669\u0662\u0669 \u0663\u0668\u0661\u0663 7264", "CVS/PHARMACY #09812 GIFT CARD",
]


def _digits(text: str) -> int:
    return sum(c.isdigit() for c in text)


@pytest.mark.parametrize("text", LEAKS)
def test_nothing_with_more_than_four_digits_gets_through(text):
    assert _digits(mask_numbers(text)) <= 4
    assert _digits(clean_account(text)) <= 4
    assert _digits(clean_account(text, "9012")) <= 4
    assert _digits(safe_line(text)) <= 4 or "$" in text or any(m in text for m in ("Oct",))


@pytest.mark.parametrize("text, masked", [
    ("1234 5678 9012", "\u2022 9012"),
    ("1234-5678-9012-3456", "\u2022-3456"),
    ("acct# 12 3456 7890", "acct# \u2022 7890"),
    ("XXXX-XXXX-1234-5678", "XXXX-XXXX-\u2022-5678"),
    ("1234ab5678cd9012", "\u2022ab\u2022cd9012"),
    ("12\u200b34\u200b5678\u200b9012", "\u20229012"),
    ("CVS/PHARMACY #09812 GIFT CARD", "CVS/PHARMACY #\u20229812 GIFT CARD"),
    ("Oct 17", "Oct 17"),
    ("Mon, Oct 19", "Mon, Oct 19"),
    ("ref 4417", "ref 4417"),
])
def test_mask_numbers_keeps_only_the_last_four_digits_of_the_whole_text(text, masked):
    assert mask_numbers(text) == masked


@pytest.mark.parametrize("name, clean", [
    ("Everyday Checking ...4417", "Everyday Checking 4417"),
    ("Checking (4417)", "Checking (4417)"),
    ("Chk,5678,9012,3456", "Chk,•,3456"),
    ("Roth IRA 2024", "Roth IRA 2024"),
    ("Way2Save savings", "Way2Save savings"),
    ("Joint checking", "Joint checking"),
    ("Acme Inc.", "Acme Inc."),
])
def test_clean_account_keeps_at_most_four_digits(name, clean):
    assert clean_account(name) == clean


@pytest.mark.parametrize("text, safe", [
    ("$1,234.56 to 1234 5678 9012 on Oct 17", "$1,234.56 to • 9012 on Oct 17"),
    ("Feb 14, 2025 at ACME 1234567", "Feb 14, 2025 at ACME •4567"),
    ("Mon, Oct 19", "Mon, Oct 19"),
])
def test_safe_line_keeps_amounts_and_dates(text, safe):
    assert safe_line(text) == safe


def test_the_cleaners_hold_for_generated_strings():
    import random
    rnd = random.Random(15)
    seps = list(" \t\n-_.,;:|/\\+~*#x•–—()[]{}<>!?'\"") + ["\u200b", "\u200d", "\ufeff", "\u3000", "ab", "Xy", "  "]
    for _ in range(3000):
        parts = []
        for _ in range(rnd.randint(1, 8)):
            parts.append("".join(rnd.choice("0123456789\uff10\uff15\u0664") for _ in range(rnd.randint(1, 6))))
            parts.append("".join(rnd.choice(seps) for _ in range(rnd.randint(0, 3))))
        text = "".join(parts)
        assert _digits(mask_numbers(text)) <= 4, text
        assert _digits(clean_account(text)) <= 4, text
        assert _digits(scrub_text(text + " a@b.com")) <= 4


@pytest.mark.parametrize("text", [
    "550 5.1.1 <jr@x.com> user unknown", "RCPT TO:<jr.hale+a@x.co.uk> refused", "5.1.1 jr@x.com", "from jr@x.com to sam@y.org",
])
def test_scrub_text_removes_addresses(text):
    out = scrub_text(text)
    assert "@" not in out and "(address)" in out


def test_log_safe_keeps_a_mail_servers_first_line_scrubbed_and_drops_any_other_message():
    import smtplib
    try:
        raise smtplib.SMTPException("550 <jr@x.com> bad\nSubject: Payee Alice 1234 5678 9012")
    except smtplib.SMTPException as e:
        assert log_safe(e) == "SMTPException: 550 <(address)> bad"
    assert log_safe(ValueError("Payee Alice paid 8137.29")) == "ValueError (message not logged)"
