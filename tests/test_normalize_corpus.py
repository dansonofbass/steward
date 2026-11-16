"""normalize() on real-shaped bank text: the pattern a merchant rule, a reimburse rule or a business rule matches on, and
what "Also apply to N matching transactions" groups by. A bank's reference noise (an ACH entry's "WEB ID:" tail, a
Zelle confirmation code, a store number, a date) is dropped so next month's row has the same pattern; a word never is,
so two payees stay two patterns. Every description here is made up, in the shapes the banks send."""
import importlib.util
from pathlib import Path

import pytest

from steward.services.transactions import normalize, tidy

CORPUS: list[tuple[str, str]] = [
    # ACH entries: the "PPD ID:" / "WEB ID:" tail and everything after it go
    ("CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224", "CHASE CREDIT CRD AUTOPAY"),
    ("CHASE CREDIT CRD AUTOPAY PPD ID: 4760039231", "CHASE CREDIT CRD AUTOPAY"),
    ("BETTERMENT SEC TRANSFER ST-A1B2C3D4E5 WEB ID: 1234567890", "BETTERMENT SEC TRANSFER"),
    ("BETTERMENT\nSEC TRANSFER\nST-Q9W8E7R6T5\nWEB ID: 1234567890", "BETTERMENT SEC TRANSFER"),
    ("Betterment SEC Transfer\nST-Z1X2C3V4B5\nWEB ID: 9876543210", "BETTERMENT SEC TRANSFER"),
    ("BETTERMENT SEC TRANSFER A125131005 WEB ID: 1743132639", "BETTERMENT SEC TRANSFER"),   # JR's real shape
    ("BETTERMENT SEC TRANSFER\nB998877665\nWEB ID: 1743132639", "BETTERMENT SEC TRANSFER"),
    ("ACME CORP PAYROLL PPD ID: 9111111101", "ACME CORP PAYROLL"),
    ("ACME CORP PAYROLL PPD ID: 9111111187", "ACME CORP PAYROLL"),
    ("GLOBEX INC PAYROLL PPD ID: 1222222202", "GLOBEX INC PAYROLL"),
    ("IRS USATAXPYMT CCD ID: 3387702000", "IRS USATAXPYMT"),
    ("VENMO PAYMENT 1023456789 WEB ID: 3264681992", "VENMO PAYMENT"),
    ("VENMO CASHOUT PPD ID: 5264681992", "VENMO CASHOUT"),
    ("PAYPAL INST XFER PPD ID: PAYPALSI77", "PAYPAL INST XFER"),
    ("ACME CORP DES:PAYROLL ID:123456789 INDN:SMITH,JOHN CO ID:1234567890 PPD", "ACME CORP DES:PAYROLL"),
    # Zelle: the code goes, the person stays
    ("ZELLE PAYMENT TO JOHN SMITH JPM99ABC123", "ZELLE PAYMENT TO JOHN SMITH"),
    ("Zelle payment to John Smith JPM99B8XYZ", "ZELLE PAYMENT TO JOHN SMITH"),
    ("Zelle payment to John Smith Conf# a1b2c3d4", "ZELLE PAYMENT TO JOHN SMITH"),
    ("ZELLE PAYMENT TO JANE DOE JPM77QRS456", "ZELLE PAYMENT TO JANE DOE"),
    ("ZELLE PAYMENT FROM JANE DOE BACCD4EF56GH", "ZELLE PAYMENT FROM JANE DOE"),
    ("ZELLE PAYMENT FROM JOHN SMITH WFCT0ABC1234", "ZELLE PAYMENT FROM JOHN SMITH"),
    # PayPal: a trailing *code goes as before; a name after the star stays
    ("PAYPAL *2K4LL0AB1", "PAYPAL"),
    ("PAYPAL *JOHNDOE 4029357733 CA", "PAYPAL *JOHNDOE CA"),
    ("PAYPAL *JANEROE 4029357733 CA", "PAYPAL *JANEROE CA"),
    # Card purchases: store numbers, dates and order codes go
    ("SHELL OIL 57444", "SHELL OIL"),
    ("SHELL OIL 574442120 SAN JOSE CA", "SHELL OIL SAN JOSE CA"),
    ("76 GAS 5555", "76 GAS"),
    ("76 GAS 0042 FREMONT CA", "76 GAS FREMONT CA"),
    ("CVS/PHARMACY #01234", "CVS/PHARMACY"),
    ("CVS/PHARMACY #05678 10/27", "CVS/PHARMACY"),
    ("AMZN Mktp US*2K4LL0AB1", "AMZN MKTP US"),
    ("AMZN Mktp US*7Y3TT9ZQ2", "AMZN MKTP US"),
    ("  amazon.com*2K4L9  ", "AMAZON.COM"),
    ("7-ELEVEN 1234", "7-ELEVEN"),
    ("7-ELEVEN 35512 AUSTIN TX", "7-ELEVEN AUSTIN TX"),
    ("COSTCO WHSE #0482  10/03", "COSTCO WHSE"),
    ("STARBUCKS STORE 12345 SEATTLE WA", "STARBUCKS STORE SEATTLE WA"),
    ("CARD PURCHASE 10/27 TRADER JOE'S #123 OAKLAND CA", "CARD PURCHASE TRADER JOE'S OAKLAND CA"),
    ("TARGET 00012345 BREA CA", "TARGET BREA CA"),
    ("TARGET 00067890 FREMONT CA", "TARGET FREMONT CA"),
    ("SQ *BLUE BOTTLE", "SQ *BLUE BOTTLE"),
    ("SQ *RED BOTTLE", "SQ *RED BOTTLE"),
    ("UBER *TRIP HELP.UBER.COM", "UBER *TRIP HELP.UBER.COM"),
    # Transfers and the like: an account mask and a reference go
    ("ONLINE TRANSFER TO SAV XXXXXX1234 REF #IB0XYZ1234", "ONLINE TRANSFER TO SAV"),
    ("ONLINE TRANSFER TO SAV ...1234", "ONLINE TRANSFER TO SAV"),
    ("ATM WITHDRAWAL 004521 10/28 MAIN ST", "ATM WITHDRAWAL MAIN ST"),
    # Words with a digit in them are still words
    ("IRA 401K CONTRIBUTION", "IRA 401K CONTRIBUTION"),
    ("PAYMENT TO T-MOBILE", "PAYMENT TO T-MOBILE"),
    ("Zelle payment to Jane Doe 12345", "ZELLE PAYMENT TO JANE DOE"),
    # Nothing to match on
    ("", ""),
    ("   \n ", ""),
    ("*ABC", ""),
]

STAY_DISTINCT = [
    ["ZELLE PAYMENT TO JOHN SMITH JPM99ABC123", "ZELLE PAYMENT TO JANE DOE JPM77QRS456",
     "ZELLE PAYMENT FROM JOHN SMITH WFCT0ABC1234", "ZELLE PAYMENT FROM JANE DOE BACCD4EF56GH"],
    ["VENMO PAYMENT 1023456789 WEB ID: 3264681992", "VENMO CASHOUT PPD ID: 5264681992"],
    ["PAYPAL *JOHNDOE 4029357733 CA", "PAYPAL *JANEROE 4029357733 CA"],
    ["ACME CORP PAYROLL PPD ID: 9111111101", "GLOBEX INC PAYROLL PPD ID: 1222222202"],
    ["SHELL OIL 57444", "76 GAS 5555", "CVS/PHARMACY #01234", "7-ELEVEN 1234", "AMZN Mktp US*2K4LL0AB1",
     "COSTCO WHSE #0482  10/03", "STARBUCKS STORE 12345 SEATTLE WA"],
    ["TARGET 00012345 BREA CA", "TARGET 00067890 FREMONT CA"],
    ["SQ *BLUE BOTTLE", "SQ *RED BOTTLE"],
]

COLLAPSE = [
    ["BETTERMENT SEC TRANSFER ST-A1B2C3D4E5 WEB ID: 1234567890", "BETTERMENT\nSEC TRANSFER\nST-Q9W8E7R6T5\nWEB ID: 1234567890",
     "Betterment SEC Transfer\nST-Z1X2C3V4B5\nWEB ID: 9876543210"],
    ["ZELLE PAYMENT TO JOHN SMITH JPM99ABC123", "Zelle payment to John Smith JPM99B8XYZ",
     "Zelle payment to John Smith Conf# a1b2c3d4"],
    ["ACME CORP PAYROLL PPD ID: 9111111101", "ACME CORP PAYROLL PPD ID: 9111111187"],
    ["CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224", "CHASE CREDIT CRD AUTOPAY PPD ID: 4760039231"],
    ["AMZN Mktp US*2K4LL0AB1", "AMZN Mktp US*7Y3TT9ZQ2"],
    ["CVS/PHARMACY #01234", "CVS/PHARMACY #05678 10/27"],
]

MIGRATION = Path(__file__).resolve().parents[1] / "src/steward/db/alembic/versions/0029_smarter_patterns.py"


def _frozen():
    spec = importlib.util.spec_from_file_location("m0029", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize


@pytest.mark.parametrize(("raw", "want"), CORPUS)
def test_each_description_has_its_pattern(raw, want):
    assert normalize(raw) == want


@pytest.mark.parametrize("group", STAY_DISTINCT)
def test_different_payees_and_stores_stay_different(group):
    assert len({normalize(r) for r in group}) == len(group)


@pytest.mark.parametrize("group", COLLAPSE)
def test_the_same_payees_rows_share_one_pattern(group):
    assert len({normalize(r) for r in group}) == 1


@pytest.mark.parametrize(("raw", "_"), CORPUS)
def test_a_pattern_is_its_own_pattern_and_an_old_one_reaches_the_new(raw, _):
    """The migration recomputes a stored pattern from the old one (rules keep no raw text): that must land where the
    raw text would, and a pattern must normalize to itself or a rule could never match."""
    assert normalize(normalize(raw)) == normalize(raw)
    assert normalize(tidy(raw)) == normalize(raw)


@pytest.mark.parametrize(("raw", "_"), CORPUS)
def test_the_migrations_frozen_copy_agrees_today(raw, _):
    assert _frozen()(raw) == normalize(raw)


def test_the_first_word_always_stays_and_the_cap_holds():
    assert normalize("12345") == "12345"
    assert normalize("WEB ID: 1234") == "WEB"
    assert normalize("X" * 300) == "X" * 200
    assert normalize("HARBOR " + "GRILL " * 60) == ("HARBOR " + "GRILL " * 60).strip()[:200]


def test_tidy_is_the_old_cleaning():
    """Payee keys (watching), the suggester's payer keys, the built-in rules and duplicate checks keep the old cleaning,
    so what they stored or compared before still holds."""
    assert tidy("COSTCO WHSE #0482  10/03") == "COSTCO WHSE"
    assert tidy("ZELLE PAYMENT TO JOHN SMITH JPM99ABC123") == "ZELLE PAYMENT TO JOHN SMITH JPM99ABC123"
    assert tidy("CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224") == "CHASE CREDIT CRD AUTOPAY PPD ID:"
