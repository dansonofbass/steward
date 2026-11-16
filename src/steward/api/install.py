"""Settings for the whole install (guided setup spec 4.7): email, backups, time zone and gateway name, for a manager of
a household book only. Secrets are written and never read back: the answer says only that a password is set, and shows
a ping URL as its host and last four characters."""
import logging

from fastapi import APIRouter, Depends, Request

from steward import clock, gateway_name
from steward.advisor.gateway import GatewayClient, pair_once, read_token
from steward.api.body import bad, json_object
from steward.app_settings import EMAIL_ENV, AppSettings, SettingRefused, apply_effective, masked_ping
from steward.auth.ratelimit import MAIL_TEST, PAIR, limit
from steward.db.directory_models import User
from steward.deps import install_manager
from steward.mail import why_of
from steward_boundary.pairing import normalize

router = APIRouter(prefix="/api/install")
log = logging.getLogger(__name__)

TEST_SUBJECT = "Steward test email"
TEST_BODY = "Email works. Steward can send invites, password resets and alerts."
NOT_SET_UP = "Set up email first."
PASSWORD_AGAIN = "Enter the email password again, then Send a test."
SENT = "Sent to {email}. Check your inbox."
WHY_WORDS = {"auth": "The server refused the user name or password.",
             "connect": "Couldn't reach the email server. Check the server name and port.",   # never which way
             "refused": "The server refused the From address.",
             "other": "The server didn't accept the email."}

CODE_RULE = "Enter the code {gateway} shows."
PAIRED = "Paired with {gateway}."
NO_MATCH, NO_MATCH_LAST = "That code doesn't match.", "That code doesn't match. Run steward-gateway pair again."
NOT_WAITING = "No pairing is waiting on {gateway}. Run steward-gateway pair again."
NO_ANSWER = "{gateway} didn't answer at {url}."
NO_URL = "Add STEWARD_GATEWAY_URL to Steward's settings file first."


def settings_out(request: Request) -> dict:
    store: AppSettings = request.app.state.app_settings
    eff = store.effective()
    ping = store.secret("backup.ping_url")

    def plain(key: str) -> dict:
        e = eff[key]
        return {"value": e.value or "", "source": e.source, "env": e.env}

    return {
        "email": {"source": store.email_source(), "env": EMAIL_ENV, "host": eff["email.host"].value or "",
                  "port": int(eff["email.port"].value), "user": eff["email.user"].value or "",
                  "from": eff["email.from"].value or "", "password_set": eff["email.password"].set,
                  "password_unreadable": eff["email.password"].unreadable},
        "backups": {"at": plain("backup.at"),
                    "ping_url": {"set": bool(ping), "shown": masked_ping(ping) if ping else None,
                                 "source": eff["backup.ping_url"].source, "env": eff["backup.ping_url"].env},
                    "dir": str(request.app.state.settings.backups_dir)},
        "general": {"timezone": {**plain("general.timezone"), "running": clock.household_tz().key},
                    "gateway_name": plain("general.gateway_name")},
    }


def _save(request: Request, group: str, body: dict, me: User, after=None) -> dict:
    try:
        request.app.state.app_settings.save(group, body, by_id=me.id, by_name=me.display_name)
    except SettingRefused as e:
        raise bad(e.message, e.status) from None
    if after is not None:
        after()
    return settings_out(request)


@router.get("/settings")
def read(request: Request, me: User = Depends(install_manager)):
    return settings_out(request)


@router.put("/settings/email")
def save_email(request: Request, me: User = Depends(install_manager), body: dict = Depends(json_object)):
    return _save(request, "email", body, me)


@router.delete("/settings/email")
def remove_email(request: Request, me: User = Depends(install_manager)):
    try:
        request.app.state.app_settings.clear_email(by_id=me.id, by_name=me.display_name)
    except SettingRefused as e:
        raise bad(e.message, e.status) from None
    return settings_out(request)


@router.put("/settings/backups")
def save_backups(request: Request, me: User = Depends(install_manager), body: dict = Depends(json_object)):
    return _save(request, "backups", body, me)


@router.put("/settings/general")
def save_general(request: Request, me: User = Depends(install_manager), body: dict = Depends(json_object)):
    zone_before = clock.household_tz().key

    def apply() -> None:
        apply_effective(request.app.state.app_settings)     # no restart: the zone and the name take hold now
        if clock.household_tz().key != zone_before:
            request.app.state.books.clear_plan_caches()      # days and ages were worked out in the old zone

    return _save(request, "general", body, me, apply)


@router.post("/email/test")
def test_email(request: Request, me: User = Depends(install_manager),
               _limit: None = Depends(limit("mail-test", MAIL_TEST)),
               _body: dict = Depends(json_object)) -> dict:
    """Sends only to the signed-in manager; any recipient in the body is never read."""
    store: AppSettings = request.app.state.app_settings
    cfg = store.email()
    if cfg is None:
        # A new server, port or user saved without the password let the old one go (app_settings._check)
        again = store.email_source() == "app" and store.value("email.host") and store.secret("email.password") is None
        raise bad(PASSWORD_AGAIN if again else NOT_SET_UP, 409)
    mailer = request.app.state.mailer
    try:
        mailer.send(me.email, TEST_SUBJECT, TEST_BODY)
    except Exception as e:
        why = why_of(e)
        if not getattr(mailer, "records_sends", False):
            store.record_mail(False, why)
        log.warning("The test email didn't send (%s).", type(e).__name__)
        raise bad(WHY_WORDS[why]) from None
    if not getattr(mailer, "records_sends", False):
        store.record_mail(True, None)
    return {"line": SENT.format(email=me.email)}


@router.post("/gateway/pair")
def pair_gateway(request: Request, me: User = Depends(install_manager),
                 _limit: None = Depends(limit("pair", PAIR)), body: dict = Depends(json_object)) -> dict:
    """Pairing by code (guided setup spec 6.2): one try at the gateway with the code the person read from it. The code
    is never logged or stored; the token it brings is written by pair_once, and the live clients switch to it."""
    raw = body.get("code")
    code = normalize(raw) if isinstance(raw, str) else ""
    if len(code) not in (6, 16):
        raise bad(gateway_name.fill(CODE_RULE), 422)
    settings = request.app.state.settings
    url = settings.gateway_url
    if not url:
        raise bad(NO_URL, 409)
    answer = pair_once(settings.advisor_token_path, url, code, http=request.app.state.http)
    if answer.outcome == "paired":
        request.app.state.use_gateway(GatewayClient(url, read_token(settings)))
        request.app.state.books.log_event("info", "gateway", f"Paired with {gateway_name.current()} by {me.display_name}.")
        return {"line": gateway_name.fill(PAIRED)}
    if answer.outcome == "refused":
        left = answer.tries_left
        if left == 0:
            raise bad(NO_MATCH_LAST, 422)
        more = "" if left is None else f" {left} {'try' if left == 1 else 'tries'} left."
        raise bad(NO_MATCH + more, 422)
    if answer.outcome == "not_waiting":
        raise bad(gateway_name.fill(NOT_WAITING), 422)
    raise bad(gateway_name.fill(NO_ANSWER).replace("{url}", url), 503)
