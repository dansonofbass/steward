import smtplib
from pathlib import Path

import pytest

from steward.auth.users import create_user
from steward.mail import MailNotSetUp, SmtpMailer, mail_ready
from steward.settings import Settings


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
    s = Settings()
    assert s.data_dir == tmp_path
    assert s.host == "127.0.0.1"
    assert s.port == 8420
    assert s.session_days == 30
    assert s.key_path == tmp_path / "steward.key"
    assert s.db_path == tmp_path / "steward.db"


MAIL_VARS = ("STEWARD_SMTP_HOST", "STEWARD_SMTP_PORT", "STEWARD_SMTP_USER", "STEWARD_SMTP_PASSWORD", "STEWARD_MAIL_FROM")
FULL_MAIL = {"STEWARD_SMTP_HOST": "smtp.example.com", "STEWARD_SMTP_USER": "postmaster@example.com",
             "STEWARD_SMTP_PASSWORD": "pw", "STEWARD_MAIL_FROM": '"Steward" <noreply@example.com>'}


def _no_mail_env(monkeypatch, tmp_path):
    for v in MAIL_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")


def _no_smtp(monkeypatch):
    """Any attempt to reach a mail server fails the test."""
    def refuse(*a, **k):
        raise AssertionError("an SMTP connection was opened")
    monkeypatch.setattr(smtplib, "SMTP_SSL", refuse)


def test_email_is_off_by_default(tmp_path, monkeypatch):
    _no_mail_env(monkeypatch, tmp_path)
    s = Settings(_env_file=None)
    assert (s.smtp_host, s.smtp_user, s.smtp_password, s.mail_from) == ("", "", "", "")
    assert mail_ready(SmtpMailer(s)) is False


def test_email_needs_all_four_settings(tmp_path, monkeypatch):
    _no_mail_env(monkeypatch, tmp_path)
    for k, v in FULL_MAIL.items():
        monkeypatch.setenv(k, v)
    assert SmtpMailer(Settings(_env_file=None)).configured is True
    for missing in FULL_MAIL:
        monkeypatch.setenv(missing, "")
        assert SmtpMailer(Settings(_env_file=None)).configured is False, missing
        monkeypatch.setenv(missing, FULL_MAIL[missing])


def test_sending_with_email_off_opens_no_connection(tmp_path, monkeypatch):
    _no_mail_env(monkeypatch, tmp_path)
    _no_smtp(monkeypatch)
    with pytest.raises(MailNotSetUp):
        SmtpMailer(Settings(_env_file=None)).send("someone@example.com", "Hi", "Body")


def test_forgot_with_email_off_tries_nothing(client, ddb, app, monkeypatch, caplog):
    """The real mailer with nothing set: the app starts, forgot answers as always, and no mail server is contacted."""
    _no_smtp(monkeypatch)
    app.state.mailer = SmtpMailer(app.state.settings)
    assert mail_ready(app.state.mailer) is False
    create_user(ddb, "jr", "jr@x.com", "JR", "pw-one-two-3")
    r = client.post("/api/auth/forgot", json={"username": "jr"})
    assert r.status_code == 202
    assert "Email isn't set up" in caplog.text


def test_the_time_zone_setting_refuses_a_name_that_is_no_zone(settings, monkeypatch):
    from pydantic import ValidationError
    from steward.settings import Settings
    assert settings.timezone == "America/Los_Angeles"
    monkeypatch.setenv("STEWARD_TIMEZONE", "Pacific")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("value", ["production", "PROD", "Prod", "dev", ""])
def test_an_unknown_steward_env_stops_with_the_allowed_values(tmp_path, monkeypatch, value):
    """Gate finding SEC-7 (issue #9): STEWARD_ENV=production or PROD skipped the demo guards, which compare it to prod
    exactly. Only the values the code uses are taken; anything else stops with them named."""
    from pydantic import ValidationError
    from steward.settings import ENV_RULE
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
    monkeypatch.setenv("STEWARD_ENV", value)
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None)
    assert ENV_RULE in str(e.value) and "prod, test or demo" in ENV_RULE


@pytest.mark.parametrize("value", ["prod", "test", "demo"])
def test_the_three_steward_envs_are_taken(tmp_path, monkeypatch, value):
    monkeypatch.setenv("STEWARD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STEWARD_BASE_URL", "https://nas.tail1234.ts.net")
    monkeypatch.setenv("STEWARD_ENV", value)
    assert Settings(_env_file=None).env == value
