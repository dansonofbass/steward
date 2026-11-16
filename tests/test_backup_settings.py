"""The built-in backup on the effective settings (guided setup spec 4.1, 4.3; release spec section 7)."""
from datetime import time

from steward.app_settings import AppSettings
from steward.egress import outbound_hosts
from steward.services import scheduled_backup as sb
from tests.test_app_settings import BY, EMAIL
from tests.test_scheduled_backup import LA, FakeHttp, at, stamps  # noqa: F401  (stamps is a fixture)

PING = "https://hc-ping.example/" + "-".join(["0a1b2c3d", "9f2c"])


def store(books, **env):
    return AppSettings(books.settings.model_copy(update=env), books.directory, books.master)


def test_the_watcher_reads_the_effective_time_and_ping_each_tick(books, stamps):
    st = store(books)
    st.save("backups", {"at": "04:30", "ping_url": PING}, **BY)
    assert sb.backup_schedule(books.settings, st) == sb.BackupSchedule(time(4, 30), PING)
    http = FakeHttp()
    assert sb.backup_tick(books, http, books.settings, at(LA, 2026, 10, 30, 4, 0), at(LA, 2026, 10, 29, 12, 0), st) is None
    rec = sb.backup_tick(books, http, books.settings, at(LA, 2026, 10, 30, 4, 31), at(LA, 2026, 10, 29, 12, 0), st)
    assert rec["ok"] is True and http.calls == [PING]


def test_an_empty_backup_at_in_env_keeps_it_off_whatever_the_app_holds(books):
    st = store(books)
    st.save("backups", {"at": "04:30"}, **BY)
    off = store(books, backup_at="")
    assert sb.backup_schedule(off.settings, off).at is None
    assert sb.backup_line(off.settings, off) == "Backups: off"


def test_the_ping_and_smtp_hosts_join_the_egress_list_from_the_app(books):
    st = store(books)
    st.save("backups", {"ping_url": PING}, **BY)
    st.save("email", EMAIL, **BY)
    assert outbound_hosts(books.settings, st) == frozenset({"testserver", "hc-ping.example", "smtp.example.com"})


def test_an_env_owned_ping_still_pings(books):
    """Preflight F4: with the ping in .env the store hands back the env value, not nothing."""
    st = store(books, backup_ping_url=PING)
    assert sb.backup_schedule(st.settings, st).ping_url == PING
    assert outbound_hosts(st.settings, st) == frozenset({"testserver", "hc-ping.example"})
