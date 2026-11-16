import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from steward.app_settings import AppSettings, EmailConfig
from steward.settings import Settings


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None: ...


class FakeMailer:
    def __init__(self, configured: bool = True) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.html: list[str | None] = []
        self.configured = configured

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        self.sent.append((to, subject, body))
        self.html.append(html)


class MailNotSetUp(RuntimeError):
    """SmtpMailer.send without all four mail settings: refused before any connection is opened."""


BEFORE_LOGIN = "steward_before_login"     # SmtpMailer.send marks what it raises before login succeeded


def why_of(e: BaseException) -> str:
    """One reason per failure, for mail.last and the test email's words. Order matters: every smtplib error and
    ssl.SSLError is an OSError. Every failure before login succeeded (refused, timed out, no such name, TLS or its
    certificate, a bad greeting or HELO, an odd reply, no AUTH), except a refused user name or password, is the one
    reason "connect", so the test email can't be used to learn which hosts and ports answer (Nov 8 review, Nov 9
    re-review). After login each class keeps its own reason."""
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "auth"
    if getattr(e, BEFORE_LOGIN, False):
        return "connect"
    if isinstance(e, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)):
        return "refused"
    if isinstance(e, (ssl.SSLError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected)):
        return "connect"
    if isinstance(e, smtplib.SMTPException):
        return "other"
    if isinstance(e, (OSError, TimeoutError)):      # socket.gaierror, refused, unreachable, timed out
        return "connect"
    return "other"


STARTTLS_PORT = 587
NO_STARTTLS = "The server doesn't offer STARTTLS."


def _connect(cfg: EmailConfig) -> smtplib.SMTP:
    """A connection that is TLS before anything private is said. The default context checks the certificate and the
    host name (Nov 8 review), .env's email included. Port 587 connects plain and must turn to TLS with STARTTLS; a
    server that doesn't offer it is refused before the user name or password is sent (Nov 9 re-review). Every other
    port, .env's included, speaks implicit TLS as before."""
    context = ssl.create_default_context()
    if cfg.port != STARTTLS_PORT:
        return smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20, context=context)
    smtp = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
    try:
        smtp.ehlo()
        if not smtp.has_extn("starttls"):
            raise smtplib.SMTPNotSupportedError(NO_STARTTLS)
        smtp.starttls(context=context)
        smtp.ehlo()                    # again, over TLS: what the server offers now (AUTH among it)
    except BaseException:
        smtp.close()
        raise
    return smtp


class SmtpMailer:
    """With a store, reads the effective settings (.env, then the app) at each send and records mail.last; without
    one it uses the Settings' four values as before."""
    records_sends = True

    def __init__(self, s: Settings, store: AppSettings | None = None) -> None:
        self.s = s
        self.store = store

    def _config(self) -> EmailConfig | None:
        if self.store is not None:
            return self.store.email()
        s = self.s
        if not (s.smtp_host.strip() and s.smtp_user and s.smtp_password and s.mail_from.strip()):
            return None
        return EmailConfig(s.smtp_host, s.smtp_port, s.smtp_user, s.smtp_password, s.mail_from)

    @property
    def configured(self) -> bool:
        """Spec 4.3: without SMTP settings, flags still show and Settings says email isn't set up. All four are
        needed; the host and the from address default to empty (settings.py), so a fresh install has email off."""
        return self._config() is not None

    def send(self, to: str, subject: str, body: str, html: str | None = None) -> None:
        cfg = self._config()
        if cfg is None:
            raise MailNotSetUp("Email isn't set up")
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = cfg.mail_from, to, subject
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")
        logged_in = False
        try:
            with _connect(cfg) as smtp:
                smtp.login(cfg.user, cfg.password)
                logged_in = True
                smtp.send_message(msg)
        except Exception as e:
            if not logged_in:
                try:
                    setattr(e, BEFORE_LOGIN, True)
                except AttributeError:      # an exception that takes no attributes: why_of reads its class
                    pass
            if self.store is not None:
                self.store.record_mail(False, why_of(e))
            raise
        if self.store is not None:
            self.store.record_mail(True, None)


def mail_ready(mailer) -> bool:
    return bool(getattr(mailer, "configured", True))
