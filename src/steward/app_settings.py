"""Settings chosen in the app (guided setup spec 4.2 to 4.4).

A fixed registry (KEYS) names every setting the app may store, the Settings field and .env variable it mirrors, and
whether it is plain or secret. Secret values (the SMTP password, the backup ping URL) are sealed with AES-256-GCM
under a key derived from steward.key; the setting's name is the associated data, so a sealed value cannot be moved
to another setting's row. The SMTP password's associated data also names the server, port and user it was saved with,
so beside any others it doesn't open and reads as not set. Sealed text never appears in an answer, a log, an error, an
export or an undo entry.

AppSettings reads in one order: a variable set in .env (even empty), then a value saved in the app, then the default.
"""
import ipaddress
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr
from typing import Literal
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from steward_boundary.naming import DEFAULT_GATEWAY_NAME

from steward import clock, gateway_name
from steward import settings as settings_mod
from steward.db.directory_models import AppSetting, DirectoryEvent, DirectoryMeta
from steward.db.engine import WRITE
from steward.db.keys import hkdf_sha256
from steward.settings import Settings

log = logging.getLogger(__name__)

SEAL_INFO = b"steward/settings/secret"
MAGIC = b"SST1"


@dataclass(frozen=True)
class Spec:
    key: str
    field: str          # the Settings field: "smtp_host"
    env: str            # "STEWARD_SMTP_HOST"
    kind: Literal["plain", "secret"]
    group: Literal["email", "backups", "general"]


KEYS: dict[str, Spec] = {s.key: s for s in (
    Spec("email.host", "smtp_host", "STEWARD_SMTP_HOST", "plain", "email"),
    Spec("email.port", "smtp_port", "STEWARD_SMTP_PORT", "plain", "email"),
    Spec("email.user", "smtp_user", "STEWARD_SMTP_USER", "plain", "email"),
    Spec("email.password", "smtp_password", "STEWARD_SMTP_PASSWORD", "secret", "email"),
    Spec("email.from", "mail_from", "STEWARD_MAIL_FROM", "plain", "email"),
    Spec("backup.at", "backup_at", "STEWARD_BACKUP_AT", "plain", "backups"),
    Spec("backup.ping_url", "backup_ping_url", "STEWARD_BACKUP_PING_URL", "secret", "backups"),
    Spec("general.timezone", "timezone", "STEWARD_TIMEZONE", "plain", "general"),
    Spec("general.gateway_name", "gateway_name", "STEWARD_GATEWAY_NAME", "plain", "general"),
)}
EMAIL_KEYS: tuple[str, ...] = tuple(k for k, s in KEYS.items() if s.group == "email")


def secret_key(master_hex: str) -> bytes:
    return hkdf_sha256(bytes.fromhex(master_hex), SEAL_INFO)


def _aad(setting: str, bound: str) -> bytes:
    return b"steward/setting/" + setting.encode() + (b"\x00" + bound.encode() if bound else b"")


def seal(key: bytes, setting: str, plain: str, bound: str = "") -> bytes:
    """`bound` joins the associated data: the email password is sealed for the server, port and user it was saved with
    (password_bound), so it opens only beside them."""
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, plain.encode(), _aad(setting, bound))


def unseal(key: bytes, setting: str, blob: bytes, bound: str = "") -> str | None:
    """None for anything that doesn't open: another steward.key, another setting's row, another server, port or user
    (for the email password), damaged bytes."""
    if len(blob) < 4 + 12 + 16 or blob[:4] != MAGIC:
        return None
    try:
        return AESGCM(key).decrypt(blob[4:16], blob[16:], _aad(setting, bound)).decode()
    except (InvalidTag, UnicodeDecodeError):
        return None


def password_bound(host: object, port: object, user: object) -> str:
    """What the email password is sealed for (Nov 9 re-review): "host|port|user". The host can't hold "|" (HOST_RULE)
    and the port is digits, so the user, last, can't make two triples read the same."""
    return f"{host}|{port}|{user}"


HOST_RULE = "Enter the server's name, like smtp.example.com."
PORT_RULE = "Use port 465 or 587. It's usually 465."
# Only the mail ports Steward speaks TLS on (465 implicit, 587 STARTTLS; steward.mail), so the test email can't probe
# other services (Nov 8 review, Nov 9 re-review)
MAIL_PORTS = (465, 587)
USER_RULE = "Enter the user name the server gave you."
PASSWORD_RULE = "Enter the password."
FROM_RULE = "Enter the address emails come from."
TIME_RULE = "Enter a time like 03:00."
PING_RULE = "Enter the ping URL from your checks service."
ENV_OWNS = "This is set in your settings file ({env})."
EMAIL_ENV = "STEWARD_SMTP_*"
UNKNOWN = "Unknown field: {name}."
EVENTS = {"email": "Email settings changed by {name}.", "email-removed": "Email settings removed by {name}.",
          "backups": "Backup settings changed by {name}.", "general": "Steward's settings changed by {name}."}
MAIL_LAST, EMAIL_VERSION = "mail.last", "email.version"

Source = Literal["env", "app", "default"]
Group = Literal["email", "backups", "general"]

# body field -> registry key, per group
FIELDS: dict[str, dict[str, str]] = {
    "email": {"host": "email.host", "port": "email.port", "user": "email.user", "password": "email.password",
              "from": "email.from"},
    "backups": {"at": "backup.at", "ping_url": "backup.ping_url"},
    "general": {"timezone": "general.timezone", "gateway_name": "general.gateway_name"},
}
_DELETES_WHEN_EMPTY = {"backup.ping_url", "general.timezone", "general.gateway_name"}
_PASSWORD_BELONGS_TO = ("email.host", "email.port", "email.user")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")
_ADDR = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


@dataclass(frozen=True)
class Effective:
    key: str
    value: str | None          # always None for a secret
    source: Source
    env: str
    set: bool
    unreadable: bool = False


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    user: str
    password: str = field(repr=False)
    mail_from: str


class SettingRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def masked_ping(url: str) -> str:
    return f"{urlsplit(url).hostname}/…{url[-4:]}"


def _has_control(v: str) -> bool:
    return any(unicodedata.category(c).startswith("C") for c in v)


def _host(v: object) -> str:
    if isinstance(v, str):
        v = v.strip()
        if _HOST.fullmatch(v) and ".." not in v:
            return v
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
    raise ValueError(HOST_RULE)


def _port(v: object) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v not in MAIL_PORTS:
        raise ValueError(PORT_RULE)
    return v


def _user(v: object) -> str:
    if not isinstance(v, str) or not 1 <= len(v) <= 200 or _has_control(v):
        raise ValueError(USER_RULE)
    return v


def _password(v: object) -> str:
    if not isinstance(v, str) or not 1 <= len(v) <= 500:
        raise ValueError(PASSWORD_RULE)
    return v


def _from(v: object) -> str:
    if (not isinstance(v, str) or len(v) > 200 or _has_control(v) or v.count("@") != 1
            or not _ADDR.fullmatch(parseaddr(v)[1])):
        raise ValueError(FROM_RULE)
    return v


def _time(v: object) -> str:
    if v is None or v == "":
        return ""
    try:
        if not isinstance(v, str):
            raise ValueError(TIME_RULE)
        return settings_mod.backup_time(v)
    except ValueError:
        raise ValueError(TIME_RULE) from None


def _ping(v: object) -> str:
    if v is None or v == "":
        return ""
    try:
        if not isinstance(v, str):
            raise ValueError(PING_RULE)
        return settings_mod.ping_url(v)
    except ValueError:
        raise ValueError(PING_RULE) from None


def _zone(v: object) -> str:
    if v is None or v == "":
        return ""
    if not isinstance(v, str):
        raise ValueError(clock.ZONE_RULE.format(name=v))
    v = v.strip()
    clock.zone(v)
    return v


def _gateway(v: object) -> str:
    if v is not None and not isinstance(v, str):
        raise ValueError(gateway_name.NAME_RULE)
    name = gateway_name.clean(v)
    return "" if name == DEFAULT_GATEWAY_NAME else name


_CHECKS = {"host": _host, "port": _port, "user": _user, "from": _from, "at": _time, "ping_url": _ping,
           "timezone": _zone, "gateway_name": _gateway}


def apply_effective(store: "AppSettings") -> None:
    """Put the effective time zone and gateway name in force (spec 4.3): .env, then the app, then the default. A saved
    value that no longer holds falls back to what .env or the default gives, with one plain line in the log."""
    try:
        clock.configure(store.value("general.timezone"))
    except ValueError:
        log.warning("The saved time zone isn't one Steward knows; using the default.")
        clock.configure(store.settings.timezone)
    try:
        gateway_name.configure(store.value("general.gateway_name"))
    except ValueError:
        log.warning("The saved gateway name isn't one Steward can use; using the default.")
        gateway_name.configure(store.settings.gateway_name)


class AppSettings:
    def __init__(self, settings: Settings, directory: Engine, master_hex: str):
        self.settings = settings
        self._directory = directory
        self._seal_key = secret_key(master_hex)
        self.version = 0
        self._cache: dict[str, tuple[str | None, bytes | None]] | None = None

    # ---- reading
    def reload(self) -> None:
        self._cache = None

    def _rows(self) -> dict[str, tuple[str | None, bytes | None]]:
        if self._cache is None:
            try:
                with Session(self._directory) as s:
                    self._cache = {r.key: (r.value, r.sealed) for r in s.query(AppSetting)}
            except OperationalError:      # a directory before d0007: no such table
                return {}
        return self._cache

    def _env_owns(self, spec: Spec) -> bool:
        fields = self.settings.model_fields_set
        if spec.group == "email":                      # spec 4.3: email is one group
            return any(KEYS[k].field in fields for k in EMAIL_KEYS)
        return spec.field in fields                     # an empty value counts as set

    def _one(self, spec: Spec, rows: dict | None = None) -> Effective:
        if self._env_owns(spec):
            raw = getattr(self.settings, spec.field)
            return Effective(spec.key, None if spec.kind == "secret" else str(raw), "env", spec.env, bool(raw))
        rows = self._rows() if rows is None else rows
        row = rows.get(spec.key)
        if row is not None:
            if spec.kind == "secret":
                plain = self._unseal_row(spec.key, rows)
                return Effective(spec.key, None, "app", spec.env, plain is not None, unreadable=plain is None)
            return Effective(spec.key, row[0], "app", spec.env, row[0] != "")
        default = Settings.model_fields[spec.field].default
        shown = "" if default is None else str(default)
        return Effective(spec.key, None if spec.kind == "secret" else shown, "default", spec.env,
                         bool(default) and spec.kind == "plain")

    def _bound(self, rows: dict) -> str:
        """The server, port and user the app's rows hold now, as password_bound joins them."""
        return password_bound(*((self._one(KEYS[k], rows).value or "") for k in _PASSWORD_BELONGS_TO))

    def _unseal_row(self, key: str, rows: dict, bound: str | None = None) -> str | None:
        """A saved secret's plain text, or None. The email password opens only beside the server, port and user it was
        saved for: `bound`, or what `rows` (one read of the table) hold now."""
        row = rows.get(key)
        if row is None:
            return None
        if key == "email.password" and bound is None:
            bound = self._bound(rows)
        return unseal(self._seal_key, key, row[1] or b"", bound or "")

    def effective(self) -> dict[str, Effective]:
        rows = self._rows()
        return {k: self._one(s, rows) for k, s in KEYS.items()}

    def value(self, key: str) -> str:
        spec = KEYS[key]
        if spec.kind != "plain":
            raise KeyError(key)
        return self._one(spec).value or ""

    def secret(self, key: str) -> str | None:
        """The plain text at the moment of use: the .env value when .env owns it (preflight F4), else the unsealed row
        (None when it doesn't open)."""
        spec = KEYS[key]
        if spec.kind != "secret":
            raise KeyError(key)
        if self._env_owns(spec):
            return getattr(self.settings, spec.field) or None
        return self._unseal_row(key, self._rows())

    def email(self) -> EmailConfig | None:
        """What a send uses, from one read of the table: the app's password is opened for exactly the server, port and
        user returned beside it, so it never goes anywhere else."""
        rows = self._rows()
        host, port_text, user, mail_from = (self._one(KEYS[k], rows).value or ""
                                            for k in ("email.host", "email.port", "email.user", "email.from"))
        if self._env_owns(KEYS["email.password"]):
            password = self.settings.smtp_password or None
        else:
            password = self._unseal_row("email.password", rows, password_bound(host, port_text, user))
        if not (host and user and mail_from and password):
            return None
        try:
            port = int(port_text)
        except ValueError:
            return None
        return EmailConfig(host, port, user, password, mail_from)

    def email_source(self) -> Source:
        if self._env_owns(KEYS["email.host"]):
            return "env"
        return "app" if any(k in self._rows() for k in EMAIL_KEYS) else "default"

    def email_version(self) -> int:
        if self._env_owns(KEYS["email.host"]):
            return 0
        try:
            with Session(self._directory) as s:
                row = s.get(DirectoryMeta, EMAIL_VERSION)
                return int(row.value) if row else 0
        except (OperationalError, ValueError):
            return 0

    # ---- saving
    def _check(self, group: str, body: dict) -> dict[str, object]:
        """Every value validated before anything is written: {registry key: cleaned value}."""
        names = FIELDS[group]
        for name in body:
            if name not in names:
                raise SettingRefused(422, UNKNOWN.format(name=name))
        out: dict[str, object] = {}
        try:
            if group == "email":
                for name in ("host", "port", "user", "from"):
                    out[names[name]] = _CHECKS[name](body.get(name))
                pw = body.get("password")
                if pw is not None:
                    out["email.password"] = _password(pw)
                else:
                    if self._unseal_row("email.password", self._rows()) is None:
                        raise ValueError(PASSWORD_RULE)
                    if self._moves_the_password(out):
                        out["email.password"] = None      # deleted: it is never sent where it wasn't saved for
            else:
                for name, v in body.items():
                    out[names[name]] = _CHECKS[name](v)
        except ValueError as e:
            raise SettingRefused(422, str(e)) from None
        return out

    def _moves_the_password(self, out: dict[str, object]) -> bool:
        """A save with no new password that changes the server, port or user (Nov 8 review): the saved password
        belongs to the old ones, so it goes, and nothing sends until it is typed again. This reads the cached rows,
        outside the write; if another save lands in between, the password's sealing (password_bound) still keeps it
        from opening beside any server, port or user but its own."""
        rows = self._rows()
        return any((rows.get(k) or (None,))[0] != str(out[k]) for k in _PASSWORD_BELONGS_TO)

    def save(self, group: Group, body: dict, *, by_id: int | None, by_name: str) -> None:
        if group == "email":
            if self._env_owns(KEYS["email.host"]):
                raise SettingRefused(409, ENV_OWNS.format(env=EMAIL_ENV))
        else:
            for name in body:
                key = FIELDS[group].get(name)
                if key and self._env_owns(KEYS[key]):
                    raise SettingRefused(409, ENV_OWNS.format(env=KEYS[key].env))
        values = self._check(group, body)
        with Session(self._directory.execution_options(**WRITE)) as s:
            now = clock.now()
            for key, v in values.items():
                row = s.get(AppSetting, key)
                if v is None or (v == "" and key in _DELETES_WHEN_EMPTY):     # None: the password _check let go
                    if row is not None:
                        s.delete(row)
                    continue
                if row is None:
                    row = AppSetting(key=key)
                    s.add(row)
                if key == "email.password":           # sealed for the server, port and user saved with it
                    bound = password_bound(values["email.host"], values["email.port"], values["email.user"])
                    row.value, row.sealed = None, seal(self._seal_key, key, str(v), bound)
                elif KEYS[key].kind == "secret":
                    row.value, row.sealed = None, seal(self._seal_key, key, str(v))
                else:
                    row.value, row.sealed = str(v), None
                row.updated_at, row.updated_by = now, by_id
            if group == "email":
                self._bump_email(s)
            s.add(DirectoryEvent(level="info", kind="settings", message=EVENTS[group].format(name=by_name)))
            s.commit()
        self.reload()
        self.version += 1

    @staticmethod
    def _bump_email(s: Session) -> None:
        row = s.get(DirectoryMeta, EMAIL_VERSION)
        if row is None:
            s.add(DirectoryMeta(key=EMAIL_VERSION, value="1"))
        else:
            row.value = str(int(row.value) + 1)

    def clear_email(self, *, by_id: int | None, by_name: str) -> None:
        with Session(self._directory.execution_options(**WRITE)) as s:
            rows = [r for r in (s.get(AppSetting, k) for k in EMAIL_KEYS) if r is not None]
            if not rows:
                return
            for r in rows:
                s.delete(r)
            self._bump_email(s)
            s.add(DirectoryEvent(level="info", kind="settings", message=EVENTS["email-removed"].format(name=by_name)))
            s.commit()
        self.reload()
        self.version += 1

    # ---- the last test mail
    def record_mail(self, ok: bool, why: str | None) -> None:
        try:
            record = {"at": clock.now().isoformat(), "ok": ok, "why": why, "config": self.email_version()}
            with Session(self._directory.execution_options(**WRITE)) as s:
                s.merge(DirectoryMeta(key=MAIL_LAST, value=json.dumps(record, separators=(",", ":"))))
                s.commit()
        except Exception as e:
            log.warning("Couldn't record the email result (%s).", type(e).__name__)

    def last_mail(self) -> dict | None:
        try:
            with Session(self._directory) as s:
                row = s.get(DirectoryMeta, MAIL_LAST)
                raw = row.value if row else None
        except OperationalError:
            return None
        if raw is None:
            return None
        try:
            d = json.loads(raw)
            if not isinstance(d, dict) or set(d) != {"at", "ok", "why", "config"}:
                return None
            when = datetime.fromisoformat(d["at"])
        except (ValueError, TypeError):
            return None
        if (when.tzinfo is None or not isinstance(d["ok"], bool) or not (d["why"] is None or isinstance(d["why"], str))
                or isinstance(d["config"], bool) or not isinstance(d["config"], int)):
            return None
        return d
