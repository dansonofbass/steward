"""The hosts Steward itself may contact (release spec 2026-11-05, sections 7 and 10, PR 14's egress test reads this):
the backup ping is the only host the built-in backup adds."""
from steward.egress import outbound_hosts


def test_with_nothing_set_only_simplefin_is_allowed(settings):
    assert outbound_hosts(settings) == frozenset({"testserver"})


def test_the_ping_host_joins_the_allowlist(settings):
    s = settings.model_copy(update={"backup_ping_url": "https://hc-ping.example/abc"})
    assert outbound_hosts(s) == frozenset({"testserver", "hc-ping.example"})


def test_every_configured_service_is_listed(settings):
    s = settings.model_copy(update={"gateway_url": "http://100.64.0.9:8430", "categorizer_url": "http://gpu.lan:9000",
                                    "smtp_host": "smtp.example.com"})
    assert outbound_hosts(s) == frozenset({"testserver", "100.64.0.9", "gpu.lan", "smtp.example.com"})
