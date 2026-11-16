"""SmtpMailer on the effective settings, mail.last, and the test email (guided setup spec 4.3, 4.6)."""
import logging
import smtplib
import socket
import ssl
from datetime import timedelta

import pytest

from steward.app_settings import AppSettings
from steward.auth.reset import safe_send
from steward.mail import FakeMailer, MailNotSetUp, SmtpMailer, mail_ready, why_of
from tests.factories import login, make_person
from tests.test_app_settings import BY, EMAIL, SENTINEL, store_for


class FakeSMTP:
    seen: list = []
    contexts: list = []
    fail: BaseException | None = None
    login_fail: BaseException | None = None
    send_fail: BaseException | None = None

    def __init__(self, host, port, timeout, context=None):
        FakeSMTP.seen.append(("connect", host, port))
        FakeSMTP.contexts.append(context)
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, user, password):
        FakeSMTP.seen.append(("login", user, password == SENTINEL))
        if FakeSMTP.login_fail is not None:
            raise FakeSMTP.login_fail

    def send_message(self, msg):
        FakeSMTP.seen.append(("send", msg["To"], msg["From"]))
        if FakeSMTP.send_fail is not None:
            raise FakeSMTP.send_fail

    def close(self):
        FakeSMTP.seen.append(("close",))


class FakeStartTLS(FakeSMTP):
    """smtplib.SMTP for port 587: a plain connection that must turn to TLS before anything else is said."""
    offers_starttls = True
    starttls_fail: BaseException | None = None

    def __init__(self, host, port, timeout):
        FakeSMTP.seen.append(("connect-plain", host, port))
        if FakeSMTP.fail is not None:
            raise FakeSMTP.fail

    def ehlo(self, name=""):
        FakeSMTP.seen.append(("ehlo",))
        return 250, b"ok"

    def has_extn(self, name):
        return name.lower() == "starttls" and FakeStartTLS.offers_starttls

    def starttls(self, context=None):
        FakeSMTP.seen.append(("starttls",))
        FakeSMTP.contexts.append(context)
        if FakeStartTLS.starttls_fail is not None:
            raise FakeStartTLS.starttls_fail
        return 220, b"ready"


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.seen, FakeSMTP.contexts, FakeSMTP.fail, FakeSMTP.login_fail = [], [], None, None
    FakeSMTP.send_fail, FakeStartTLS.offers_starttls, FakeStartTLS.starttls_fail = None, True, None
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP", FakeStartTLS)
    return FakeSMTP


def test_the_mailer_reads_the_effective_settings_at_each_send(books, smtp):
    store = AppSettings(books.settings, books.directory, books.master)
    m = SmtpMailer(books.settings, store)
    assert mail_ready(m) is False
    with pytest.raises(MailNotSetUp):
        m.send("a@example.com", "Hi", "Body")
    store.save("email", EMAIL, **BY)
    assert mail_ready(m) is True
    m.send("a@example.com", "Hi", "Body")
    assert smtp.seen == [("connect", "smtp.example.com", 465), ("login", "steward@example.com", True),
                         ("send", "a@example.com", "Steward <steward@example.com>")]
    assert store.last_mail()["ok"] is True and store.last_mail()["config"] == 1


def test_an_env_owned_email_group_still_sends_with_the_env_values(books, smtp):
    """Preflight F4: JR's NAS keeps its .env lines and the mailer must read them through the store."""
    store = store_for(books, smtp_host="mail.env.example", smtp_port=587, smtp_user="env-user",
                      smtp_password=SENTINEL, mail_from="Env <env@example.com>")
    m = SmtpMailer(books.settings, store)
    assert mail_ready(m) is True
    m.send("a@example.com", "Hi", "Body")
    assert smtp.seen == [("connect-plain", "mail.env.example", 587), ("ehlo",), ("starttls",), ("ehlo",),
                         ("login", "env-user", True), ("send", "a@example.com", "Env <env@example.com>")]


def test_port_587_turns_to_checked_tls_before_it_logs_in(books, smtp):
    """Nov 9 re-review: Steward spoke implicit TLS only, so 587 always failed. Port 587 now connects plain and must
    turn to TLS (STARTTLS, the certificate and host name checked) before the user name or password is sent."""
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", {**EMAIL, "port": 587}, **BY)
    SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    assert smtp.seen == [("connect-plain", "smtp.example.com", 587), ("ehlo",), ("starttls",), ("ehlo",),
                         ("login", "steward@example.com", True), ("send", "a@example.com", "Steward <steward@example.com>")]
    assert len(smtp.contexts) == 1 and _verifies(smtp.contexts[0])


def test_port_587_without_starttls_sends_no_auth_and_no_mail(books, smtp):
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", {**EMAIL, "port": 587}, **BY)
    FakeStartTLS.offers_starttls = False
    with pytest.raises(smtplib.SMTPNotSupportedError) as e:
        SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    assert smtp.seen == [("connect-plain", "smtp.example.com", 587), ("ehlo",), ("close",)]
    assert why_of(e.value) == "connect" and store.last_mail()["why"] == "connect"


@pytest.mark.parametrize("err", [ssl.SSLCertVerificationError("bad cert"), smtplib.SMTPResponseException(454, b"no TLS")],
                         ids=lambda e: type(e).__name__)
def test_a_failed_starttls_sends_no_auth_and_reads_as_connect(books, smtp, err):
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", {**EMAIL, "port": 587}, **BY)
    FakeStartTLS.starttls_fail = err
    with pytest.raises(type(err)):
        SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    assert not any(s[0] in ("login", "send") for s in smtp.seen)
    assert store.last_mail()["why"] == "connect"


def test_587_without_starttls_gets_the_connect_words(pat, app, smtp):
    app.state.mailer = SmtpMailer(app.state.settings, app.state.app_settings)
    assert pat.put("/api/install/settings/email", json={**EMAIL, "port": 587}).status_code == 200
    FakeStartTLS.offers_starttls = False
    r = pat.post("/api/install/email/test", json={})
    assert (r.status_code, r.json()) == (422, {"error": "Couldn't reach the email server. Check the server name and port."})
    assert not any(s[0] == "login" for s in smtp.seen)


@pytest.mark.parametrize("port", [465, 25, 2525])
def test_an_env_port_other_than_587_keeps_implicit_tls(books, smtp, port):
    """.env's port is the operator's and isn't checked: every port but 587 speaks implicit TLS, as before."""
    store = store_for(books, smtp_host="mail.env.example", smtp_port=port, smtp_user="env-user",
                      smtp_password=SENTINEL, mail_from="Env <env@example.com>")
    SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    assert smtp.seen[0] == ("connect", "mail.env.example", port) and _verifies(smtp.contexts[0])


def test_the_settings_alone_on_587_also_need_starttls(books, smtp):
    s = books.settings.model_copy(update=dict(smtp_host="mail.env.example", smtp_port=587, smtp_user="env-user",
                                              smtp_password=SENTINEL, mail_from="Env <env@example.com>"))
    FakeStartTLS.offers_starttls = False
    with pytest.raises(smtplib.SMTPNotSupportedError):
        SmtpMailer(s).send("a@example.com", "Hi", "Body")
    assert not any(e[0] == "login" for e in smtp.seen)


def _verifies(context) -> bool:
    return (isinstance(context, ssl.SSLContext) and context.check_hostname is True
            and context.verify_mode == ssl.CERT_REQUIRED)


def test_every_connection_checks_the_certificate_and_the_host_name(books, smtp):
    """Nov 8 review: SMTP_SSL without a context checks nothing, so anyone on the path could read the password. Each way
    Steward sends (the app's settings, a .env group through the store, and the Settings alone) verifies the server."""
    env = dict(smtp_host="mail.env.example", smtp_port=465, smtp_user="env-user", smtp_password=SENTINEL,
               mail_from="Env <env@example.com>")
    app_store = AppSettings(books.settings, books.directory, books.master)
    app_store.save("email", EMAIL, **BY)
    for m in (SmtpMailer(books.settings, app_store), SmtpMailer(books.settings, store_for(books, **env)),
              SmtpMailer(books.settings.model_copy(update=env))):
        m.send("a@example.com", "Hi", "Body")
    assert len(smtp.contexts) == 3 and all(_verifies(c) for c in smtp.contexts)


@pytest.mark.parametrize("err,why", [
    (smtplib.SMTPAuthenticationError(535, b"5.7.8 steward@example.com rejected"), "auth"),
    (smtplib.SMTPSenderRefused(550, b"no", "x@y.z"), "refused"),
    (smtplib.SMTPRecipientsRefused({}), "refused"),
    # Nov 8 review: everything before a mail server has answered over a checked connection is one reason, so the
    # test email can't tell a closed port from an open one that speaks something else
    (ssl.SSLError("wrong version number"), "connect"), (ssl.SSLCertVerificationError("bad cert"), "connect"),
    (socket.gaierror(-2, "Name or service not known"), "connect"),
    (TimeoutError(), "connect"), (ConnectionRefusedError(), "connect"), (ConnectionResetError(), "connect"),
    (smtplib.SMTPConnectError(554, b"no"), "connect"), (smtplib.SMTPServerDisconnected("gone"), "connect"),
    (smtplib.SMTPDataError(554, b"x"), "other"), (ValueError("x"), "other"),
])
def test_each_failure_has_its_reason(err, why):
    assert why_of(err) == why


# Each one made fresh per test (send() marks the exception it raises); the reason it reads once logged in.
PHASE_ERRORS = {
    "SMTPHeloError": (lambda: smtplib.SMTPHeloError(501, b"no"), "other"),
    "SMTPResponseException": (lambda: smtplib.SMTPResponseException(421, b"busy"), "other"),
    "SMTPNotSupportedError": (lambda: smtplib.SMTPNotSupportedError("SMTP AUTH extension not supported"), "other"),
    "SMTPException": (lambda: smtplib.SMTPException("x"), "other"),
    "SMTPServerDisconnected": (lambda: smtplib.SMTPServerDisconnected("gone"), "connect"),
    "SMTPAuthenticationError": (lambda: smtplib.SMTPAuthenticationError(535, b"no"), "auth"),
    "SMTPSenderRefused": (lambda: smtplib.SMTPSenderRefused(550, b"no", "x@example.com"), "refused"),
    "SMTPDataError": (lambda: smtplib.SMTPDataError(554, b"x"), "other"),
    "SSLError": (lambda: ssl.SSLError("x"), "connect"),
    "ConnectionResetError": (lambda: ConnectionResetError(), "connect"),
    "ValueError": (lambda: ValueError("x"), "other"),
}


@pytest.mark.parametrize("phase", ["connect", "login", "send"])
@pytest.mark.parametrize("name", list(PHASE_ERRORS))
def test_every_failure_before_login_but_a_refused_password_reads_as_connect(books, smtp, phase, name):
    """Nov 9 re-review: a HELO refusal, an odd reply or a server without AUTH told a live service from a closed port.
    Until login succeeds every failure is "connect", except a refused user name or password; after it, each keeps its
    own reason."""
    make, after_login = PHASE_ERRORS[name]
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", EMAIL, **BY)
    setattr(smtp, {"connect": "fail", "login": "login_fail", "send": "send_fail"}[phase], make())
    with pytest.raises(Exception) as caught:
        SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    want = after_login if phase == "send" or name == "SMTPAuthenticationError" else "connect"
    assert type(caught.value).__name__ == name
    assert why_of(caught.value) == want and store.last_mail()["why"] == want


def test_a_server_without_auth_gets_the_connect_words(pat, app, smtp, caplog):
    caplog.set_level(logging.DEBUG)
    app.state.mailer = SmtpMailer(app.state.settings, app.state.app_settings)
    pat.put("/api/install/settings/email", json=EMAIL)
    smtp.login_fail = smtplib.SMTPNotSupportedError("SMTP AUTH extension not supported by server.")
    r = pat.post("/api/install/email/test", json={})
    assert (r.status_code, r.json()) == (422, {"error": "Couldn't reach the email server. Check the server name and port."})
    assert "SMTPNotSupportedError" in caplog.text and SENTINEL not in caplog.text


def test_a_failed_send_is_recorded_and_raised(books, smtp):
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", EMAIL, **BY)
    smtp.fail = ssl.SSLError("bad")
    with pytest.raises(ssl.SSLError):
        SmtpMailer(books.settings, store).send("a@example.com", "Hi", "Body")
    assert (store.last_mail()["ok"], store.last_mail()["why"]) == (False, "connect")


def test_safe_send_still_logs_only_the_class_name(books, smtp, caplog):
    caplog.set_level(logging.DEBUG)
    store = AppSettings(books.settings, books.directory, books.master)
    store.save("email", EMAIL, **BY)
    smtp.login_fail = smtplib.SMTPAuthenticationError(535, b"steward@example.com rejected")
    safe_send(SmtpMailer(books.settings, store), "a@example.com", "Hi", "Body")
    assert "SMTPAuthenticationError" in caplog.text
    assert "steward@example.com" not in caplog.text and SENTINEL not in caplog.text


@pytest.fixture
def pat(client, ddb, ours):
    make_person(ddb, "pat", [(ours.id, "manager")])
    login(client, "pat")
    return client


def test_the_test_email_goes_only_to_the_caller(pat, app):
    r = pat.post("/api/install/email/test", json={})
    assert (r.status_code, r.json()) == (409, {"error": "Set up email first."})
    pat.put("/api/install/settings/email", json=EMAIL)
    r = pat.post("/api/install/email/test", json={"to": "someone@else.example"})     # no recipient is ever read
    assert r.json() == {"line": "Sent to pat@x.com. Check your inbox."}
    assert app.state.mailer.sent == [("pat@x.com", "Steward test email",
                                      "Email works. Steward can send invites, password resets and alerts.")]
    assert app.state.app_settings.last_mail()["ok"] is True


def test_a_changed_server_never_gets_the_old_password(pat, app, smtp):
    """Nov 8 review: a manager points the email at another server, keeps the password field empty, and sends a test. No
    connection is opened with the old password; the answer asks for the password."""
    app.state.mailer = SmtpMailer(app.state.settings, app.state.app_settings)
    assert pat.put("/api/install/settings/email", json=EMAIL).status_code == 200
    no_pw = {k: v for k, v in EMAIL.items() if k != "password"}
    r = pat.put("/api/install/settings/email", json={**no_pw, "host": "smtp.other.example"})
    assert r.status_code == 200 and r.json()["email"]["password_set"] is False
    r = pat.post("/api/install/email/test", json={})
    assert (r.status_code, r.json()) == (409, {"error": "Enter the email password again, then Send a test."})
    assert smtp.seen == []
    pat.put("/api/install/settings/email", json={**EMAIL, "host": "smtp.other.example"})
    assert pat.post("/api/install/email/test", json={}).status_code == 200
    assert smtp.seen[:2] == [("connect", "smtp.other.example", 465), ("login", "steward@example.com", True)]


def test_a_save_then_a_test_sends_with_the_saved_password(pat, app, smtp):
    app.state.mailer = SmtpMailer(app.state.settings, app.state.app_settings)
    assert pat.put("/api/install/settings/email", json=EMAIL).status_code == 200
    r = pat.post("/api/install/email/test", json={})
    assert r.json() == {"line": "Sent to pat@x.com. Check your inbox."}
    assert smtp.seen == [("connect", "smtp.example.com", 465), ("login", "steward@example.com", True),
                         ("send", "pat@x.com", "Steward <steward@example.com>")]


def test_a_server_changed_beside_the_password_never_gets_it(pat, app, smtp, books, caplog):
    """Nov 9 re-review: two saves at once could leave a new server beside the old password (the move check reads
    cached rows). The password is sealed for the server, port and user it was saved with, so here it reads as not set:
    Send a test asks for it and opens no connection, and the Email row asks for it too. No answer or log holds it."""
    from sqlalchemy.orm import Session

    from steward.db.directory_models import AppSetting
    caplog.set_level(logging.DEBUG)
    app.state.mailer = SmtpMailer(app.state.settings, app.state.app_settings)
    assert pat.put("/api/install/settings/email", json=EMAIL).status_code == 200
    with Session(books.directory) as s:          # the race, written straight to the row
        s.get(AppSetting, "email.host").value = "smtp.other.example"
        s.commit()
    app.state.app_settings.reload()
    test, read, ready = (pat.post("/api/install/email/test", json={}), pat.get("/api/install/settings"),
                         pat.get("/api/b/ours/ready"))
    assert (test.status_code, test.json()) == (409, {"error": "Enter the email password again, then Send a test."})
    assert smtp.seen == []
    assert {k: read.json()["email"][k] for k in ("host", "password_set", "password_unreadable")} == {
        "host": "smtp.other.example", "password_set": False, "password_unreadable": True}
    row = next(r for r in ready.json()["rows"] if r["key"] == "email")
    assert (row["status"], row["detail"], row["go"]) == ("needs", "Enter the email password again.", "Edit")
    for r in (test, read, ready):
        assert SENTINEL not in r.text
    assert SENTINEL not in caplog.text


class Refusing(FakeMailer):
    def __init__(self, err):
        super().__init__()
        self.err = err

    def send(self, *a, **k):
        raise self.err


UNREACHED = "Couldn't reach the email server. Check the server name and port."   # never the host, never which way


@pytest.mark.parametrize("err,words", [
    (smtplib.SMTPAuthenticationError(535, b"steward@example.com bad"), "The server refused the user name or password."),
    (OSError("unreachable"), UNREACHED), (ConnectionRefusedError(), UNREACHED), (TimeoutError(), UNREACHED),
    (socket.gaierror(-2, "Name or service not known"), UNREACHED), (ssl.SSLError("x"), UNREACHED),
    (ssl.SSLCertVerificationError("x"), UNREACHED), (smtplib.SMTPServerDisconnected("x"), UNREACHED),
    (smtplib.SMTPSenderRefused(550, b"no", "steward@example.com"), "The server refused the From address."),
    (smtplib.SMTPDataError(554, b"steward@example.com"), "The server didn't accept the email."),
])
def test_each_failure_is_one_plain_reason_with_no_server_text(pat, app, caplog, err, words):
    caplog.set_level(logging.DEBUG)
    pat.put("/api/install/settings/email", json=EMAIL)
    app.state.mailer = Refusing(err)
    r = pat.post("/api/install/email/test", json={})
    assert (r.status_code, r.json()) == (422, {"error": words}) and "smtp.example.com" not in r.text
    assert app.state.app_settings.last_mail()["ok"] is False
    assert "steward@example.com" not in caplog.text and SENTINEL not in caplog.text


def test_five_tests_per_fifteen_minutes(pat, fake_clock):
    pat.put("/api/install/settings/email", json=EMAIL)
    for _ in range(5):
        assert pat.post("/api/install/email/test", json={}).status_code == 200
    assert pat.post("/api/install/email/test", json={}).status_code == 429
    fake_clock.advance(timedelta(minutes=15, seconds=1))
    assert pat.post("/api/install/email/test", json={}).status_code == 200
