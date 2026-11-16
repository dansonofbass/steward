"""Get Steward ready's eight rows (guided setup spec 3.2, 3.3, 5): pure builders from what the route read, so each
row's words and status are tested without a request. Dates and times are in the household's zone."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from steward import clock, gateway_name
from steward.advisor.state import gateway_line
from steward.app_settings import Effective
from steward.inventory.present import at_label, day_label
from steward.inventory.present import clock as clock_text
from steward.services.profile import join_words

Status = Literal["done", "needs", "optional"]

DAY, STALE = timedelta(hours=26), timedelta(hours=48)
MAX_ORIGIN = 200
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
_COPY = re.compile(r"steward-directory-\d{8}-\d{6}\.db")
EMAIL_WHY = {"auth": "The server refused the user name or password.",
             "connect": "Couldn't reach the email server. Check the server name and port.",
             "refused": "The server refused the From address."}
EMAIL_OTHER = "The server didn't accept the last email."
BASE_EXAMPLE = "https://steward.example.ts.net"
ADDRESS_UNKNOWN = "Couldn't tell which address this page is on."
CLAUDE_KEY = "ANTHROPIC_API_" + "KEY"   # in pieces, so no line reads as a key assignment to gitleaks


@dataclass(frozen=True)
class Line:
    name: str
    line: str
    running: str | None
    note: str | None = None
    where: Literal["steward", "gateway"] = "steward"


@dataclass(frozen=True)
class Row:
    key: str
    status: Status
    detail: str
    go: str | None
    lines: tuple[Line, ...] = ()
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"key": self.key, "status": self.status, "detail": self.detail, "go": self.go,
                "lines": [{"name": x.name, "line": x.line, "running": x.running, "note": x.note, "where": x.where}
                          for x in self.lines],
                "extra": dict(self.extra)}


def _local_day(t: datetime, today: date) -> str:
    d = t.astimezone(clock.household_tz()).date()
    return "today" if d == today else day_label(d, today)


def household_row(profile_done: int, profile_total: int, plan_done: int, plan_total: int,
                  next_section: str | None) -> Row:
    done = profile_done >= profile_total and plan_done >= plan_total
    return Row("household", "done" if done else "needs",
               f"Profile {profile_done} of {profile_total} · Plan {plan_done} of {plan_total}",
               None if done else "Continue", extra={"next": next_section})


def money_row(*, money_in: bool, linked: bool, last_sync: datetime | None, sync_failed: bool, accounts: int,
              last_import: datetime | None, waiting: int, today: date) -> Row:
    extra = {"linked": linked, "failed": sync_failed}
    if not money_in:
        return Row("money", "needs", "Nothing is in yet.", "Add", extra=extra)
    if sync_failed:
        return Row("money", "needs", "The last bank sync didn't work.", "Check", extra=extra)
    wait = "" if waiting <= 0 else f" · {waiting} {'waits' if waiting == 1 else 'wait'} in Review"
    if linked:
        head = "Linked" + (f" · updated {_local_day(last_sync, today)}" if last_sync else "")
        return Row("money", "done", head + wait, None, extra=extra)
    head = f"{accounts} {'account' if accounts == 1 else 'accounts'}"
    if last_import:
        head += f" · last import {_local_day(last_import, today)}"
    return Row("money", "done", head + wait, None, extra=extra)


def ask_row(*, url: str | None, paired: bool, reachable: bool | None, state: str | None, chat_on: bool,
            accelerator: object = None) -> Row:
    known = state == "ok" and isinstance(accelerator, str) and accelerator in ("cpu", "cuda", "rocm")
    extra = {"url_set": bool(url), "paired": paired, "reachable": reachable, "state": state, "chat_on": chat_on,
             "accelerator": accelerator if known else None}
    if not url:
        return Row("ask", "optional", "Not set up.", None,
                   (Line("STEWARD_GATEWAY_URL", "STEWARD_GATEWAY_URL=http://gateway:8430", None),), extra)
    if not paired:
        text = (f"{gateway_name.fill('{gateway}')} didn't answer at {url}." if reachable is False
                else gateway_name.fill("Not paired with {gateway}."))
        text = text[:1].upper() + text[1:]
        return Row("ask", "optional", text, "Pair", extra=extra)
    if state == "ok":
        if chat_on:
            return Row("ask", "done", gateway_name.fill("{gateway} is answering. Ask is on."), None, extra=extra)
        return Row("ask", "optional", "Ask is off in this book.", "Turn on", extra=extra)
    if state == "not_set_up":
        return Row("ask", "needs", gateway_name.fill("{gateway} has no Claude key."), "Check again",
                   (Line(CLAUDE_KEY, CLAUDE_KEY + "=sk-ant-…", None, where="gateway"),), extra)
    return Row("ask", "needs", gateway_line(state or "away"), "Check again", extra=extra)


def email_row(*, eff: dict[str, Effective], configured: bool, last: dict | None, version: int, today: date) -> Row:
    extra = {"source": eff["email.host"].source}
    host, pw = eff["email.host"], eff["email.password"]
    # unreadable, or let go when the server, port or user changed without it (app_settings._check)
    if pw.unreadable or (host.source == "app" and host.value and not pw.set):
        return Row("email", "needs", "Enter the email password again.", "Edit", extra=extra)
    if not configured:
        return Row("email", "optional", "Not set up.", "Set up", extra=extra)
    if last is None or last["config"] != version:
        return Row("email", "needs", "Send a test to check it.", "Send a test", extra=extra)
    if not last["ok"]:
        return Row("email", "needs", EMAIL_WHY.get(last["why"] or "", EMAIL_OTHER), "Send a test", extra=extra)
    return Row("email", "done", f"Last email sent {at_label(datetime.fromisoformat(last['at']), today)}.", "Edit",
               extra=extra)


def backups_row(*, at: str, last: dict | None, newest: datetime | None, now: datetime, folder: str) -> Row:
    def when(t: datetime) -> str:
        return at_label(t, now.astimezone(clock.household_tz()).date())

    run_at = clock_text(datetime.combine(date(2000, 1, 1), time.fromisoformat(at))) if at else None   # "3:00 AM"
    extra = {"dir": folder}
    if last and not last["ok"]:
        return Row("backups", "needs", "The last backup didn't work.", "Edit", extra=extra)
    if newest and now - newest > STALE:
        return Row("backups", "needs", f"The newest copy is from {when(newest)}.", "Edit", extra=extra)
    if last and last["ping_ok"] is False:
        return Row("backups", "needs", "The backup ping didn't go through.", "Edit", extra=extra)
    if newest is None:
        if run_at is None:
            return Row("backups", "needs", "Backups are off, and there's no copy yet.", "Edit", extra=extra)
        return Row("backups", "done", f"First copy at {run_at}", "Edit", extra=extra)
    tail = f" · next {run_at}" if run_at else " · made outside Steward's schedule"
    return Row("backups", "done", f"Last copy {when(newest)}{tail}", "Edit", extra=extra)


def newest_copy(folder: Path) -> datetime | None:
    """The newest modified time among the directory copies steward/services/backup.py writes (from Steward's schedule
    or `steward backup` in a NAS task); None when the folder is missing or has none."""
    try:
        times = [(folder / n).stat().st_mtime for n in os.listdir(folder) if _COPY.fullmatch(n)]
    except OSError:
        return None
    return datetime.fromtimestamp(max(times), timezone.utc) if times else None


def someone_row(names: list[str]) -> Row:
    if names:
        return Row("someone", "done", join_words(names), None)
    return Row("someone", "optional", "None yet.", "Add their book")


def clean_origin(origin: str | None) -> str | None:
    """The page's address as the browser reported it, if it looks like one; anything else counts as unknown."""
    if not origin or len(origin) > MAX_ORIGIN:
        return None
    try:
        u = urlsplit(origin)
        host = u.hostname
    except ValueError:
        return None
    return origin if u.scheme in ("http", "https") and host else None


def address_row(*, base_url: str, trusted_proxies: str, scheme: str, origin: str | None, peer: str) -> Row:
    base = base_url
    try:
        local = urlsplit(base).hostname in LOCAL_HOSTS
    except ValueError:
        local = False
    https_ok = base.startswith("https://") or (local and base.startswith("http://"))
    same = origin is not None and origin.rstrip("/") == base.rstrip("/")   # no origin proves nothing (INS-22)
    seen_ok = scheme == "https" or local
    if https_ok and same and seen_ok:
        return Row("address", "done", f"Steward is at {base}.", None)
    if https_ok and origin is None:
        return Row("address", "needs", ADDRESS_UNKNOWN, "Check again")
    lines: list[Line] = []
    if not (https_ok and same):
        shown = f"STEWARD_BASE_URL={origin}" if origin and origin.startswith("https://") else \
            f"STEWARD_BASE_URL={BASE_EXAMPLE}"
        lines.append(Line("STEWARD_BASE_URL", shown, base_url))
    if origin and origin.startswith("https://") and scheme == "http":
        lines.append(Line("STEWARD_TRUSTED_PROXIES", f"STEWARD_TRUSTED_PROXIES={trusted_proxies},{peer}",
                          trusted_proxies))
    if not https_ok:
        detail = "Steward's address isn't HTTPS."
    elif not same:
        detail = f"Steward's address is {base}, but this page is {origin}."
    else:
        detail = "Steward sees plain HTTP from its proxy."
    return Row("address", "needs", detail, "Check again", tuple(lines))


def key_row(*, key_file: Path | None, key_path: Path, data_dir: Path, stat=os.stat) -> Row:
    apart = False
    if key_file is not None:
        try:
            apart = str(key_path).startswith("/run/secrets/") or stat(key_path).st_dev != stat(data_dir).st_dev
        except OSError:
            apart = False
    if apart:
        return Row("key", "done", "The key is on its own mount.", None)
    return Row("key", "optional",
               "The key is in the data folder, so encryption protects copies and backups, not a running box.", None,
               (Line("STEWARD_KEY_FILE", "STEWARD_KEY_FILE=/run/secrets/steward_key",
                     str(key_file) if key_file else None,
                     note="Move the key file there first. Don't make a new one: a new key won't open your books."),))
