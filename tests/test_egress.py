"""P1 (docs/CLAIMS.md): every module of Steward's that can open a connection is listed here with the host its setting
names, and each client reaches only that host. src/steward/egress.py's outbound_hosts is the list of those hosts
(release spec 2026-11-05, sections 7 and 10)."""
import ast
import smtplib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx2
import pytest
from fastapi.testclient import TestClient

from steward.egress import outbound_hosts

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("src/steward", "src/steward_pdf", "src/steward_boundary")
NETWORK = frozenset({"httpx2", "httpx", "requests", "urllib.request", "urllib3", "aiohttp", "http.client", "smtplib",
                     "socket", "websockets", "ftplib", "telnetlib", "asyncio", "ssl", "subprocess", "xmlrpc",
                     "socketserver", "multiprocessing.connection", "imaplib", "poplib", "anthropic"})

# Each module that imports a network library, and the outbound_hosts source it reaches.
CONNECTORS = {
    "src/steward/services/simplefin/client.py": "simplefin: settings.allowed_hosts",
    "src/steward/app.py": "simplefin and gateway: the shared app.state.http client (sync, the readiness probe, "
                          "pairing by code with settings.gateway_url)",
    "src/steward/cli.py": "simplefin (sync) and gateway (advisor pair: settings.gateway_url or the --gateway you type)",
    "src/steward/api/ready.py": "gateway: the readiness probe, through app.state.http",
    "src/steward/advisor/gateway.py": "gateway: HTTP, and the WebSocket for each turn",
    "src/steward/services/statements/client.py": "gateway: the statement reader",
    "src/steward/services/categorizer_client.py": "categorizer: settings.categorizer_url, else the paired gateway",
    "src/steward/services/scheduled_backup.py": "ping: the backup ping",
    "src/steward/mail.py": "smtp: the mail server (ssl wraps that same connection)",
    "src/steward_pdf/sandbox.py": "none: _probes() opens a socket only to prove the filter refuses it, and subprocess "
                                  "starts the confined PDF reader child (python -I -m), not a client",
}


def _network_libraries(tree: ast.AST) -> set[str]:
    """The NETWORK libraries a module imports anywhere, inside functions too, or names to __import__/import_module."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
              and isinstance(node.args[0].value, str)
              and ((isinstance(node.func, ast.Name) and node.func.id == "__import__")
                   or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"))):
            names.add(node.args[0].value)
    return {lib for lib in NETWORK for name in names if name == lib or name.startswith(lib + ".")}


def connecting_modules(root: Path) -> dict[str, set[str]]:
    """Each .py under PACKAGES that imports a network library, by its path from root, with the libraries it imports."""
    found: dict[str, set[str]] = {}
    for package in PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            libraries = _network_libraries(ast.parse(path.read_text(encoding="utf-8"), str(path)))
            if libraries:
                found[path.relative_to(root).as_posix()] = libraries
    return found


def test_every_module_that_can_open_a_connection_is_listed():
    found = connecting_modules(ROOT)
    assert len(CONNECTORS) >= 9
    unlisted, gone = sorted(set(found) - set(CONNECTORS)), sorted(set(CONNECTORS) - set(found))
    assert (unlisted, gone) == ([], []), "list each new module in CONNECTORS with the host it reaches"


def test_the_inventory_notices_a_new_connection(tmp_path):
    files = {"src/steward/x.py": "def later():\n    import httpx2\n",
             "src/steward_boundary/y.py": "from urllib import request\n",
             "src/steward_pdf/z.py": "import json\n",
             "src/steward/services/quiet_dial.py": "import asyncio\nasyncio.open_connection('h.test', 443)\n",
             "src/steward/services/quiet_curl.py": "import subprocess\nsubprocess.run(['curl', 'h.test'])\n"}
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    assert connecting_modules(tmp_path) == {"src/steward/x.py": {"httpx2"}, "src/steward_boundary/y.py": {"urllib.request"},
                                            "src/steward/services/quiet_dial.py": {"asyncio"},
                                            "src/steward/services/quiet_curl.py": {"subprocess"}}


GATEWAY, CATEGORIZER, PING, SMTP = "http://gw.test:8430", "http://cat.test:9000", "https://ping.test/steward", "smtp.test"
CODE = "K7M-4QX"


class Recorder:
    """An httpx2 transport that keeps each request's URL and answers 200 with `answer` (JSON, or text for a str)."""

    def __init__(self, answer: dict | str | None = None):
        self.answer, self.urls = {} if answer is None else answer, []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.urls.append(request.url)
        if isinstance(self.answer, str):
            return httpx2.Response(200, text=self.answer)
        return httpx2.Response(200, json=self.answer)

    def client(self) -> httpx2.Client:
        return httpx2.Client(transport=httpx2.MockTransport(self))

    @property
    def hosts(self) -> list[str]:
        return [u.host for u in self.urls]


def every_new_client_records(monkeypatch, rec: Recorder) -> None:
    """Each httpx2.Client a module builds for itself from now on sends through rec."""
    real = httpx2.Client
    monkeypatch.setattr(httpx2, "Client", lambda *a, **kw: real(*a, **{**kw, "transport": httpx2.MockTransport(rec)}))


def paired(settings):
    """Settings with the gateway's address and a pairing token, as after `steward advisor pair`."""
    s = settings.model_copy(update={"gateway_url": GATEWAY, "categorizer_url": ""})
    s.advisor_token_path.parent.mkdir(parents=True, exist_ok=True)
    s.advisor_token_path.write_text("t")
    return s


def categorizer_from_its_setting(settings, monkeypatch, request):
    from steward.services.categorizer_client import client_for
    s, rec = settings.model_copy(update={"categorizer_url": CATEGORIZER}), Recorder()
    every_new_client_records(monkeypatch, rec)
    model = client_for(s)
    model.categorize("COFFEE SHOP", -450)
    model.categorize_batch([("COFFEE SHOP", -450)])
    model.close()
    return s, "cat.test", rec.hosts


def categorizer_through_the_gateway(settings, monkeypatch, request):
    from steward.services.categorizer_client import client_for
    s, rec = paired(settings), Recorder()
    every_new_client_records(monkeypatch, rec)
    model = client_for(s)
    model.categorize("COFFEE SHOP", -450)
    model.categorize_batch([("COFFEE SHOP", -450)])
    model.close()
    return s, "gw.test", rec.hosts


def statement_reader(settings, monkeypatch, request):
    from steward.services.statements.client import statement_client_for
    s, rec = paired(settings), Recorder()
    every_new_client_records(monkeypatch, rec)
    reader = statement_client_for(s)
    reader.layout([], None)
    reader.page(b"png", 1, 1, 10, 10)
    reader.extract(b"%PDF-")
    reader.render(b"%PDF-", 1)
    reader.close()
    return s, "gw.test", rec.hosts


def gateway_http(settings, monkeypatch, request):
    from steward.advisor.gateway import client_from_settings
    s, rec = paired(settings), Recorder()
    every_new_client_records(monkeypatch, rec)
    gw = client_from_settings(s)
    for call in (gw.health, lambda: gw.redact("x"), lambda: gw.title("x"), gw.usage, gw.settings,
                 lambda: gw.set_settings(cap=1), lambda: gw.sent_since(datetime(2026, 10, 1, tzinfo=timezone.utc)),
                 lambda: gw.prewarm_plan(1, 1), lambda: gw.prewarm(1, 1, "0" * 64)):
        call()
    gw.close()
    assert len(rec.urls) == 9
    return s, "gw.test", rec.hosts


def gateway_turn(settings, monkeypatch, request):
    from steward.advisor.gateway import client_from_settings
    s, opened = paired(settings), []
    monkeypatch.setattr("websockets.sync.client.connect", lambda uri, **kw: opened.append(uri) or object())
    client_from_settings(s).connect()
    assert [urlsplit(u).scheme for u in opened] == ["ws"]
    return s, "gw.test", [urlsplit(u).hostname for u in opened]


def gateway_pairing_from_the_cli(settings, monkeypatch, request):
    from steward.advisor.gateway import new_code, pair
    s, rec = settings.model_copy(update={"gateway_url": GATEWAY}), Recorder({"token": "t"})
    assert pair(s.advisor_token_path, s.gateway_url, new_code(), http=rec.client(), sleep=lambda _: None) == "paired"
    return s, "gw.test", rec.hosts


def simplefin(settings, monkeypatch, request):
    from steward.services.simplefin.client import SimplefinError, claim, fetch_accounts
    access = "http://demo:demo@testserver/simplefin"
    claimed, fetched = Recorder(access), Recorder({"accounts": []})
    assert claim(claimed.client(), "http://testserver/simplefin/claim/demo", settings.allowed_hosts) == access
    fetch_accounts(fetched.client(), access, None, allowed_hosts=settings.allowed_hosts)
    with pytest.raises(SimplefinError):         # a host outside allowed_hosts is refused before any request
        fetch_accounts(fetched.client(), "https://demo:demo@elsewhere.test/simplefin", None,
                       allowed_hosts=settings.allowed_hosts)
    return settings, "testserver", claimed.hosts + fetched.hosts


def backup_ping(settings, monkeypatch, request):
    from steward.services.scheduled_backup import backup_schedule, ping
    s, rec = settings.model_copy(update={"backup_ping_url": PING}), Recorder()
    ping(rec.client(), backup_schedule(s).ping_url, True)
    ping(rec.client(), backup_schedule(s).ping_url, False)
    return s, "ping.test", rec.hosts


def mail_server(settings, monkeypatch, request):
    """Port 587 connects plain and turns to TLS; every other port is implicit TLS (mail._connect). Both are run."""
    from steward.app_settings import EmailConfig
    from steward.mail import _connect
    s, opened = settings.model_copy(update={"smtp_host": SMTP}), []

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            opened.append((type(self).__name__, host))

        def ehlo(self): pass
        def has_extn(self, name): return True
        def starttls(self, **kw): pass
        def close(self): pass

    class FakeSMTP_SSL(FakeSMTP):
        pass

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP_SSL)
    for port in (587, 465):
        _connect(EmailConfig(s.smtp_host, port, "steward", "pw", "steward@example.com"))
    assert [kind for kind, _ in opened] == ["FakeSMTP", "FakeSMTP_SSL"]
    return s, "smtp.test", [host for _, host in opened]


def the_apps_shared_client(settings, monkeypatch, request):
    """app.state.http: the readiness probe (an unpaired gateway) and pairing by code from the browser."""
    from steward.app import create_app
    from tests.factories import login, make_person
    books, ddb, ours = (request.getfixturevalue(f) for f in ("books", "ddb", "ours"))
    s, rec = settings.model_copy(update={"gateway_url": GATEWAY}), Recorder()
    make_person(ddb, "pat", [(ours.id, "manager")])
    with TestClient(create_app(s, books, http=rec.client()), base_url="https://nas.tail1234.ts.net") as c:
        login(c, "pat")
        assert c.get("/api/b/ours/ready").status_code == 200
        c.post("/api/install/gateway/pair", json={"code": CODE})
    assert {"/v1/health", "/v1/pair"} <= {u.path for u in rec.urls}, "the probe and the pairing both ran"
    return s, "gw.test", rec.hosts


CLIENTS = [categorizer_from_its_setting, categorizer_through_the_gateway, statement_reader, gateway_http, gateway_turn,
           gateway_pairing_from_the_cli, simplefin, backup_ping, mail_server, the_apps_shared_client]


@pytest.mark.parametrize("case", CLIENTS, ids=[c.__name__ for c in CLIENTS])
def test_each_client_reaches_only_the_host_its_setting_names(case, settings, monkeypatch, request):
    s, host, hosts = case(settings, monkeypatch, request)
    assert hosts, "the client sent nothing, so this case proves nothing"
    assert set(hosts) == {host}
    assert host in outbound_hosts(s)
