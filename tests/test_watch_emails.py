"""The urgent email and the daily summary (spec 4.3; README screen 6; decision 10; rulings 6 and 18). Amounts, payee
and account names only: never an account or card number, not even the last 4."""
from datetime import date

from sqlalchemy import select

from steward.db.models import Flag, InventoryItem
from steward.inventory.items import edit_item
from steward.mail import FakeMailer
from steward.services.accounts import record_balance
from steward.watch.balances import check_low
from steward.watch.emails import clean, still_line, summary_email, summary_line, urgent_email
from steward.inventory.present import clean_account
from steward.watch.run import run_watch
from steward.watch.views import email_facts
from tests.watch_helpers import NOW, TODAY, account, d, history, txn

BASE = "https://nas.tail1234.ts.net"
ARGS = {"book_name": "Margaret Ellis", "slug": "margaret-ellis", "base_url": BASE, "name": "Margaret"}


def _gift(mdb, name="Joint checking"):
    a = account(mdb, name)
    history(mdb, a)
    txn(mdb, a, 30, -2347, "CVS/PHARMACY #04411 BREA CA", watched=True)
    txn(mdb, a, 2, -50_000, "CVS/PHARMACY #09812 GIFT CARD FULLERTON CA")
    run_watch(mdb, TODAY, NOW, after="sync")
    return mdb.query(Flag).one()


def test_the_urgent_email(margaret, mdb):
    f = _gift(mdb)
    e = urgent_email(f, email_facts(mdb, f), large_cents=50_000, **ARGS)
    assert e.subject == "Urgent, Margaret Ellis: $500.00 gift card at CVS Pharmacy"
    link = f"{BASE}/b/margaret-ellis/look-into/{f.id}"
    assert e.text == (
        "URGENT, MARGARET ELLIS\n\n"
        "Scam pattern: $500.00 gift card at CVS Pharmacy\n\n"
        "Amount:  $500.00\n"
        "Paid to: CVS Pharmacy\n"
        "Date:    Sat, Oct 17\n"
        "From:    Joint checking (Wells Fargo)\n"
        "Flagged: Mon, Oct 19, 6:12 AM\n\n"
        "This check flags every gift card, wire transfer, crypto exchange, money-transfer service and remote computer "
        "support payment, because those are the payments scammers ask for.\n\n"
        f"Open the flag:\n{link}\n\n"
        "You get urgent emails for Margaret Ellis.\n"
        "Change this in Settings → Watching. The link works on the family's Tailscale network.\n")
    assert f'href="{link}"' in e.html and ">Open the flag<" in e.html
    assert "Margaret Ellis · Urgent" in e.html and "Scam pattern: $500.00 gift card at CVS Pharmacy" in e.html


def test_no_email_shows_an_account_number(margaret, mdb, mctx):
    f = _gift(mdb, "Everyday Checking ...4417")
    e = urgent_email(f, email_facts(mdb, f), large_cents=50_000, **ARGS)
    assert "Everyday Checking 4417 (Wells Fargo)" in e.text and "5 4417" not in e.text
    save = account(mdb, "Way2Save savings x4425", "savings", feed=True)
    record_balance(mdb, save.id, d(1), 2_248_010)
    edit_item(mdb, mctx, mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == save.id)),
              {"details": {"floor_cents": 2_500_000}}, today=TODAY)
    [low_id] = check_low(mdb, TODAY, NOW, after="sync")
    low = mdb.get(Flag, low_id)
    s = summary_email([low], today=TODAY, still=None, **ARGS)
    assert "Way•Save savings 4425" in s.text       # 5 digits in the name: only the last 4 stay
    assert summary_line(low, "Margaret") == "Low balance: Way•Save savings 4425 is $22,480.10, under its $25,000.00 floor"


def test_clean_keeps_at_most_four_digits_and_drops_the_stored_last_four():
    assert clean("Everyday Checking ...4417") == "Everyday Checking 4417"
    assert clean("Checking-000123456789") == "Checking-•6789"
    assert clean_account("Everyday Checking ...4417", "4417") == "Everyday Checking"
    assert clean_account("Checking (4417)", "4417") == "Checking"
    assert clean_account("CHECKING (...4417)", "4417") == "CHECKING"
    assert clean_account("PREMIER SAVINGS x7731", "7731") == "PREMIER SAVINGS"
    assert clean_account("Checking 123456789", "6789") == "Checking"
    assert clean_account("Checking 123456789", "1111") == "Checking •6789"
    assert clean("Way2Save savings") == "Way2Save savings"


def test_the_daily_summary(margaret, mdb):
    a = account(mdb, "Citi card", "credit_card", owner="margaret", institution="Citi")
    history(mdb, a)
    txn(mdb, a, 31, -1599, "STREAMBOX *MONTHLY", merchant="StreamBox", category="subscriptions", watched=True)
    txn(mdb, a, 1, -1599, "STREAMBOX *MONTHLY", merchant="StreamBox", category="subscriptions")
    run_watch(mdb, TODAY, NOW, after="sync")
    f = mdb.query(Flag).one()
    s = summary_email([f], today=date(2026, 10, 19), still="Still open: 3 urgent and 1 still checking.", **ARGS)
    assert s.subject == "Margaret Ellis: 1 new to look into, Mon Oct 19"
    assert s.text == (
        "MARGARET ELLIS, DAILY SUMMARY, MON OCT 19\n\n"
        "1 new to look into\n\n"
        "- New monthly charge: StreamBox, $15.99 on Sep 18 and Oct 18 (Citi card)\n"
        f"  {BASE}/b/margaret-ellis/look-into/{f.id}\n\n"
        "Still open: 3 urgent and 1 still checking.\n"
        f"{BASE}/b/margaret-ellis/look-into\n\n"
        "You get the daily summary for Margaret Ellis.\n"
        "Change this in Settings → Watching.\n")
    assert ">Open<" in s.html and "See all in Look into" in s.html


def test_the_still_open_line():
    def flag(i, status, severity):
        return Flag(id=i, check="scam", status=status, severity=severity, summary="", title="")
    rows = [flag(1, "open", "urgent"), flag(2, "open", "urgent"), flag(3, "open", "urgent"),
            flag(4, "checking", "normal"), flag(5, "open", "normal"), flag(6, "open", "normal")]
    assert still_line(rows, {5, 6}) == "Still open: 3 urgent and 1 still checking."
    assert still_line(rows, set()) == "Still open: 3 urgent, 1 still checking and 2 others."
    assert still_line([], set()) is None


def test_the_fake_mailer_keeps_html_beside_the_old_tuples():
    m = FakeMailer()
    m.send("a@x.com", "Subject", "Body", html="<p>Body</p>")
    m.send("b@x.com", "Subject", "Body")
    assert m.sent == [("a@x.com", "Subject", "Body"), ("b@x.com", "Subject", "Body")]
    assert m.html == ["<p>Body</p>", None]


def test_an_account_named_with_its_whole_number_shows_at_most_the_last_4(margaret, mdb):
    """Missed-money summaries embed the account name: no email shows more of the number than its last 4."""
    a = account(mdb, "Checking 123456789", "checking", feed=True)
    item = mdb.scalar(select(InventoryItem).where(InventoryItem.account_id == a.id))
    f = Flag(check="deposit", severity="normal", status="open", item_id=item.id, account_id=a.id, due_on=d(7),
             title="Deposit hasn't arrived", summary="Social Security hasn't reached Checking 123456789 by Mon, Oct 12",
             facts='{"account": "Checking 123456789", "amount_cents": 214000, "usual_day": 3, "due": "2026-10-12"}')
    mdb.add(f)
    mdb.flush()
    u = urgent_email(f, email_facts(mdb, f), large_cents=50_000, **ARGS)
    s = summary_email([f], today=TODAY, still=None, **ARGS)
    for e in (u, s):
        blob = e.subject + e.text + e.html
        assert "123456789" not in blob and "56789" not in blob and "Checking" in blob
    assert summary_line(f, "Margaret") == "Missing deposit: Social Security hasn't reached Checking •6789 by Mon, Oct 12"
