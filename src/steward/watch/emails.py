"""The urgent email and the daily summary (spec 4.3; README screen 6; decision 10; rulings 6 and 18). Amounts, payee
and account names only: never an account or card number, not even the last 4. Each is HTML with a plain-text copy,
and neither depends on images or fixed colours."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from html import escape

from steward.db.models import Flag
from steward import clock as steward_clock
from steward.inventory.present import clean_account, clock, usd
from steward.watch import vocab as V
from steward.watch.store import facts_of
from steward.watch.views import scrub, weekday

NAME_FIELDS = frozenset({"Paid to", "From", "Into", "Account", "Bank"})
MUTED = "opacity:0.72;font-size:13px"


@dataclass(frozen=True)
class Email:
    subject: str
    text: str
    html: str


def clean(name: str) -> str:
    """Spec 4.3: an account name like "Everyday Checking ...4417" loses its number (the app's own cleaner)."""
    return clean_account(name)


def flag_link(base_url: str, slug: str, flag_id: int | None = None) -> str:
    base = f"{base_url.rstrip('/')}/b/{slug}/look-into"
    return f"{base}/{flag_id}" if flag_id is not None else base


def summary_line(f: Flag, name: str, account: str | None = None) -> str:
    """One line of the summary, from the flag's structured facts. `account` is views.account_label(); without it the
    account name is shown with its digits removed."""
    facts = facts_of(f)
    label = V.check_label(f.check, name)
    account = account if account is not None else clean(facts.get("account", ""))
    summary = scrub(f.summary, facts, account=account, clean=clean_account)
    if f.check == "low":
        return f"{label}: {account} is {usd(facts['balance_cents'])}, under its {usd(facts['floor_cents'])} floor"
    if f.check == "account":
        return f"{label}: {clean(facts.get('institution', ''))} reports {account}, which wasn't in the inventory"
    if f.check in ("deposit", "premium"):
        return f"{label}: {summary}"
    return f"{label}: {summary} ({account})" if account else f"{label}: {summary}"


def _flagged(f: Flag) -> str:
    local = f.created_at.astimezone(steward_clock.household_tz())
    return f"{weekday(local.date())}, {clock(local)}"


def _page(head: str, title: str, body: str, foot: str) -> str:
    return ("<!doctype html><html><body style=\"margin:0;padding:24px;font-family:-apple-system,'Segoe UI',Roboto,"
            "Helvetica,Arial,sans-serif;line-height:1.5\"><div style=\"max-width:560px\">"
            f"<p style=\"{MUTED};letter-spacing:0.06em;text-transform:uppercase;font-weight:600;margin:0 0 12px\">{head}</p>"
            f"<h1 style=\"font:400 22px/1.3 Georgia,serif;margin:0 0 16px\">{title}</h1>{body}"
            f"<p style=\"{MUTED};border-top:1px solid rgba(128,128,128,0.35);padding-top:12px;margin-top:24px\">{foot}</p>"
            "</div></body></html>")


def _button(href: str, text: str) -> str:
    return (f"<p style=\"margin:20px 0 8px\"><a href=\"{escape(href)}\" style=\"display:inline-block;padding:10px 20px;"
            f"border-radius:999px;background:#6b3f73;color:#ffffff;text-decoration:none;font-weight:600\">{escape(text)}</a></p>")


def urgent_email(f: Flag, rows: list[tuple[str, str]], *, book_name: str, slug: str, base_url: str, name: str,
                 large_cents: int, account: str | None = None) -> Email:
    """One email per urgent flag (spec 4.3), sent within 15 minutes."""
    facts = list(rows) + [("Flagged", _flagged(f))]
    summary = scrub(f.summary, facts_of(f), account=account, clean=clean_account)
    heading = f"{V.check_label(f.check, name)}: {summary}"
    why = V.why(f.check, facts_of(f).get("large_cents") or large_cents)
    link = flag_link(base_url, slug, f.id)
    width = max(len(k) for k, _ in facts) + 1
    text = (f"URGENT, {book_name.upper()}\n\n{heading}\n\n"
            + "".join(f"{(k + ':').ljust(width)} {v}\n" for k, v in facts)
            + f"\n{why}\n\nOpen the flag:\n{link}\n\n"
            f"You get urgent emails for {book_name}.\n"
            "Change this in Settings → Watching. The link works on the family's Tailscale network.\n")
    table = "".join(f"<tr><td style=\"{MUTED};padding:2px 16px 2px 0;vertical-align:top\">{escape(k)}</td>"
                    f"<td style=\"padding:2px 0\">{'<b>' + escape(v) + '</b>' if k == 'Amount' else escape(v)}</td></tr>"
                    for k, v in facts)
    body = (f"<table style=\"border-collapse:collapse;font-size:15px\">{table}</table><p>{escape(why)}</p>"
            f"{_button(link, 'Open the flag')}<p style=\"{MUTED};word-break:break-all\">{escape(link)}</p>")
    foot = (f"You get urgent emails for {escape(book_name)}. Change this in Settings → Watching. The link works on the "
            "family's Tailscale network.")
    return Email(f"Urgent, {book_name}: {scrub(f.title, facts_of(f), account=account, clean=clean_account)}", text,
                 _page(f"{escape(book_name)} · Urgent", escape(heading), body, foot))


def still_line(not_done: list[Flag], listed: set[int]) -> str | None:
    """"Still open: 3 urgent and 1 still checking." for the flags not in this summary (README screen 6)."""
    rest = [f for f in not_done if f.id not in listed]
    urgent = sum(1 for f in rest if f.status == "open" and f.severity == "urgent")
    checking = sum(1 for f in rest if f.status == "checking")
    other = len(rest) - urgent - checking
    parts = [p for p in (f"{urgent} urgent" if urgent else "", f"{checking} still checking" if checking else "",
                         f"{other} other{'s' if other != 1 else ''}" if other else "") if p]
    if not parts:
        return None
    joined = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
    return f"Still open: {joined}."


def summary_email(flags: list[Flag], *, book_name: str, slug: str, base_url: str, name: str, today: date,
                  still: str | None, accounts: dict[int, str] | None = None) -> Email:
    """Decision 8: the new normal flags, at 7:00 AM household time; never sent with none."""
    n = len(flags)
    when = f"{today:%a} {today:%b} {today.day}"
    head = f"{n} new to look into"
    lines = [(summary_line(f, name, (accounts or {}).get(f.id)), flag_link(base_url, slug, f.id)) for f in flags]
    text = (f"{book_name.upper()}, DAILY SUMMARY, {when.upper()}\n\n{head}\n\n"
            + "".join(f"- {line}\n  {link}\n" for line, link in lines)
            + (f"\n{still}\n{flag_link(base_url, slug)}\n" if still else "")
            + f"\nYou get the daily summary for {book_name}.\nChange this in Settings → Watching.\n")
    items = "".join(f"<tr><td style=\"padding:10px 16px 10px 0;border-top:1px solid rgba(128,128,128,0.35)\">"
                    f"{escape(line)}</td><td style=\"padding:10px 0;border-top:1px solid rgba(128,128,128,0.35)\">"
                    f"<a href=\"{escape(link)}\" style=\"color:#6b3f73;font-weight:600;text-decoration:none\">Open</a></td></tr>"
                    for line, link in lines)
    body = f"<table style=\"border-collapse:collapse;font-size:15px;width:100%\">{items}</table>"
    if still:
        body += (f"<p>{escape(still)} <a href=\"{escape(flag_link(base_url, slug))}\" style=\"color:#6b3f73;"
                 "font-weight:600;text-decoration:none\">See all in Look into</a></p>")
    foot = f"You get the daily summary for {escape(book_name)}. Change this in Settings → Watching."
    return Email(f"{book_name}: {head}, {when}", text,
                 _page(f"{escape(book_name)} · Daily summary", escape(head), body, foot))
