import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from steward.clock import zone
from steward.gateway_name import clean as clean_gateway_name
from steward_boundary.naming import DEFAULT_GATEWAY_NAME


# Import/export spec P26: Argon2id (t, m in KiB, p) for an encrypted export. Tests and the e2e server (env "test") use
# the cheap one so no test spends 256 MiB (plan Engineering choice 7); a test pins both.
EXPORT_KDF = (3, 262144, 1)
TEST_EXPORT_KDF = (1, 8192, 1)
# Hardening plan, Engineering choice 4: where tailscale serve (through Docker's port publishing) and steward-proxy's
# Caddy connect from. uvicorn believes their forwarded-for and forwarded-proto headers only from these. (Not spelled
# with its X- prefix here: tests/test_proxy_trust.py flags any file outside its ALLOWED that names that header.)
TRUSTED_PROXIES = "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
# Issue #9: the values the code compares STEWARD_ENV to. Anything else (production, PROD) stops at start-up, because
# the demo guards in steward serve and steward seed-demo run only for prod.
ENVS = ("prod", "test", "demo")
ENV_RULE = "STEWARD_ENV must be prod, test or demo. A real install uses prod."
# Issue #8: STEWARD_ALLOWED_HOSTS, more names the API answers at besides STEWARD_BASE_URL's host and loopback.
ALLOWED_HOSTS_RULE = ("STEWARD_ALLOWED_HOSTS must be host names or addresses separated by commas, such as "
                      "steward.lan,100.101.102.103: no https://, no port and no path.")
# Release spec 2026-11-05, section 7: the built-in backup's settings and what a refusal says (never the value itself).
BACKUP_AT_RULE = "STEWARD_BACKUP_AT must be a time like 03:00, or empty to turn the built-in backup off."
PING_URL_RULE = ("STEWARD_BACKUP_PING_URL must be an https:// or http:// address of up to 500 characters, with no "
                 "user name or password in it.")


def backup_time(v: str) -> str:
    """"" (off) or "HH:MM"; ValueError(BACKUP_AT_RULE) for anything else."""
    v = v.strip()
    if not v:
        return ""
    m = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})", v)
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ValueError(BACKUP_AT_RULE)
    return f"{int(m[1]):02d}:{m[2]}"


def ping_url(v: str) -> str:
    """"" (none) or the URL; ValueError(PING_URL_RULE) for anything else."""
    v = v.strip()
    if not v:
        return ""
    try:
        u = urlsplit(v)
        bad = (len(v) > 500 or any(c.isspace() for c in v) or u.scheme not in {"https", "http"}
               or not u.hostname or u.username is not None or u.password is not None)
        u.port
    except ValueError:
        bad = True
    if bad:
        raise ValueError(PING_URL_RULE)
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STEWARD_", env_file=".env", extra="ignore",
                                      hide_input_in_errors=True)   # a refused value (a ping URL, a password) is never echoed

    data_dir: Path
    base_url: str
    host: str = "127.0.0.1"
    port: int = 8420
    env: Literal["prod", "test", "demo"] = "prod"

    @field_validator("env", mode="before")
    @classmethod
    def _check_env(cls, v):
        if v not in ENVS:
            raise ValueError(ENV_RULE)
        return v

    session_days: int = 30
    categorizer_url: str | None = None
    statement_reader: bool = False   # PDF statements: start the reader thread under STEWARD_ENV=test (the e2e server)
    statement_reading: Literal["auto", "local", "gateway"] = "auto"   # PDF remote-reading P54: where PDFs are opened
    categorizer_timeout_s: float = 2.0
    # A batch of 50 took about 24 s on the gateway (deploy day, 2026-10-24); the wait for one batch.
    categorizer_batch_timeout_s: float = 60.0
    gateway_url: str | None = None
    sync_hours: float = 6
    web_dir: Path | None = None
    simplefin_hosts: str = "bridge.simplefin.org,beta-bridge.simplefin.org"
    export_tmp_dir: Path | None = None    # plan Engineering choice 6: None is the system temp folder (the spec's)
    trusted_proxies: str = TRUSTED_PROXIES
    allowed_hosts: str = ""     # issue #8: more names /api/ answers at (steward.api.hosts)

    @field_validator("allowed_hosts")
    @classmethod
    def _check_allowed_hosts(cls, v: str) -> str:
        from steward.api.hosts import plain_name
        names = [plain_name(h) for h in v.split(",") if h.strip()]
        if "" in names:
            raise ValueError(ALLOWED_HOSTS_RULE)
        return ",".join(names)

    @property
    def api_hosts(self) -> frozenset[str]:
        """The names /api/ answers at: STEWARD_BASE_URL's host, the loopback names and STEWARD_ALLOWED_HOSTS."""
        from steward.api.hosts import LOOPBACK, plain_name
        base = plain_name(urlsplit(self.base_url.strip()).hostname or "")
        return frozenset({base, *self.allowed_hosts.split(",")} - {""}) | LOOPBACK

    gateway_name: str = DEFAULT_GATEWAY_NAME   # spec 2026-11-05, section 7: what the screens call the gateway machine

    @field_validator("gateway_name")
    @classmethod
    def _clean_gateway_name(cls, v: str) -> str:
        return clean_gateway_name(v)

    timezone: str = ""      # spec 2026-11-05, section 7: STEWARD_TIMEZONE; empty is TZ, then UTC (steward/clock.py)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, v: str) -> str:
        v = v.strip()
        if v:
            zone(v)
        return v

    # Release spec 2026-11-05, section 6: STEWARD_KEY_FILE, the key on its own mount (a Docker secret such as
    # /run/secrets/steward_key). Unset (or empty), the key is <data dir>/steward.key as before.
    key_file: Path | None = None

    @field_validator("key_file", mode="before")
    @classmethod
    def _empty_key_file_is_unset(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    # Release spec 2026-11-05, section 7: STEWARD_BACKUP_AT is the daily time ("03:00"); set but empty turns it off.
    backup_at: str = "03:00"

    @field_validator("backup_at")
    @classmethod
    def _check_backup_at(cls, v: str) -> str:
        return backup_time(v)

    # STEWARD_BACKUP_DIR: where every backup goes; unset (or blank) is <data dir>/backups.
    backup_dir: Path | None = None

    @field_validator("backup_dir", mode="before")
    @classmethod
    def _empty_backup_dir_is_unset(cls, v):
        return None if v is None or (isinstance(v, str) and not v.strip()) else v

    # STEWARD_BACKUP_PING_URL: an address pinged after each scheduled backup; empty is none.
    backup_ping_url: str = ""

    @field_validator("backup_ping_url")
    @classmethod
    def _check_ping_url(cls, v: str) -> str:
        return ping_url(v)

    @property
    def export_kdf(self) -> tuple[int, int, int]:
        return TEST_EXPORT_KDF if self.env == "test" else EXPORT_KDF

    # Email is off until all four of host, user, password and from are set (STEWARD_SMTP_HOST and so on; see
    # docs/reference/configuration.md). Off, Settings says email isn't set up and nothing tries to send.
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""

    @property
    def simplefin_allowed_hosts(self) -> tuple[str, ...]:
        return tuple(h.strip() for h in self.simplefin_hosts.split(",") if h.strip())

    @property
    def key_path(self) -> Path:
        return self.key_file if self.key_file is not None else self.data_dir / "steward.key"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "steward.db"

    @property
    def directory_path(self) -> Path:
        return self.data_dir / "directory.db"

    @property
    def backups_dir(self) -> Path:
        return self.backup_dir if self.backup_dir is not None else self.data_dir / "backups"

    @property
    def books_dir(self) -> Path:
        return self.data_dir / "books"

    @property
    def advisor_token_path(self) -> Path:
        return self.data_dir / "advisor.token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
