"""Every host Steward itself may open a connection to (release spec 2026-11-05, sections 7 and 10). PR 14's
tests/test_egress.py checks each module that connects against this."""
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from steward.services.scheduled_backup import backup_schedule
from steward.settings import Settings

if TYPE_CHECKING:
    from steward.app_settings import AppSettings


def outbound_hosts(settings: Settings, store: "AppSettings | None" = None) -> frozenset[str]:
    hosts = set(settings.simplefin_allowed_hosts)
    for url in (settings.gateway_url, settings.categorizer_url, backup_schedule(settings, store).ping_url):
        if url and (host := urlsplit(url).hostname):
            hosts.add(host)
    smtp_host = settings.smtp_host
    if store is not None and store.email_source() == "app":
        cfg = store.email()
        smtp_host = cfg.host if cfg else ""
    if smtp_host:
        hosts.add(smtp_host)
    return frozenset(hosts)
