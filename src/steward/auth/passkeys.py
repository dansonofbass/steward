"""WebAuthn (passkeys) on top of py_webauthn. The API module turns these into routes."""
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from urllib.parse import urlparse

from webauthn import (
    generate_authentication_options, generate_registration_options, options_to_json,
    verify_authentication_response, verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url  # noqa: F401 - re-exported for the API and tests
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement,
)

from steward.db.directory_models import Passkey, User

CHALLENGE_TTL_S = 300
MAX_CHALLENGES = 1000
LABEL_MAX = 80
_B64URL = re.compile(r"[A-Za-z0-9_-]+")


class VerifyFailed(ValueError):
    """The browser's response did not check out. The message is for the log, never the user."""


@dataclass(frozen=True)
class RelyingParty:
    rp_id: str
    origin: str
    name: str = "Steward"


def relying_party(base_url: str) -> RelyingParty:
    u = urlparse(base_url)
    if not u.scheme or not u.hostname:
        raise ValueError(f"STEWARD_BASE_URL must be a full address, got {base_url!r}")
    return RelyingParty(rp_id=u.hostname, origin=f"{u.scheme}://{u.netloc}")


class ChallengeStore:
    """Short-lived challenges, in memory, single use. One process serves the household, so this is enough;
    a restart only means an in-flight sign-in says 'expired' and the person taps again."""

    def __init__(self, ttl_s: float = CHALLENGE_TTL_S, max_items: int = MAX_CHALLENGES, clock=time.monotonic):
        self._ttl = ttl_s
        self._max = max_items
        self._clock = clock
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[bytes, str, int | None, float]] = OrderedDict()

    def put(self, challenge: bytes, kind: str, user_id: int | None) -> str:
        cid = secrets.token_urlsafe(24)
        with self._lock:
            self._sweep()
            self._items[cid] = (challenge, kind, user_id, self._clock() + self._ttl)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
        return cid

    def pop(self, challenge_id: str, kind: str) -> tuple[bytes, int | None] | None:
        with self._lock:
            self._sweep()
            item = self._items.get(challenge_id)
            if item is None or item[1] != kind:
                return None
            del self._items[challenge_id]
            return item[0], item[2]

    def _sweep(self) -> None:
        now = self._clock()
        for cid in [c for c, (_, _, _, exp) in self._items.items() if exp <= now]:
            del self._items[cid]


def registration_options(rp: RelyingParty, user: User, existing: list[Passkey]) -> tuple[str, bytes]:
    """Returns (options JSON for the browser, challenge bytes to remember)."""
    opts = generate_registration_options(
        rp_id=rp.rp_id, rp_name=rp.name,
        user_id=str(user.id).encode(), user_name=user.username, user_display_name=user.display_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=p.credential_id) for p in existing],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED),
    )
    return options_to_json(opts), opts.challenge


def verify_registration(rp: RelyingParty, credential: dict, challenge: bytes) -> tuple[bytes, bytes, int]:
    """Returns (credential_id, public_key, sign_count) or raises VerifyFailed."""
    try:
        v = verify_registration_response(credential=credential, expected_challenge=challenge,
                                         expected_rp_id=rp.rp_id, expected_origin=rp.origin,
                                         require_user_verification=True)
    except (WebAuthnException, ValueError, KeyError, TypeError) as e:
        raise VerifyFailed(str(e)) from e
    return v.credential_id, v.credential_public_key, v.sign_count


def authentication_options(rp: RelyingParty) -> tuple[str, bytes]:
    # No allowCredentials: the browser offers whatever passkey it holds for this site (discoverable credentials).
    opts = generate_authentication_options(rp_id=rp.rp_id, user_verification=UserVerificationRequirement.REQUIRED)
    return options_to_json(opts), opts.challenge


def verify_authentication(rp: RelyingParty, credential: dict, challenge: bytes, passkey: Passkey) -> int:
    """Returns the new sign count or raises VerifyFailed (py_webauthn also rejects a sign-count rollback)."""
    try:
        v = verify_authentication_response(credential=credential, expected_challenge=challenge,
                                           expected_rp_id=rp.rp_id, expected_origin=rp.origin,
                                           credential_public_key=passkey.public_key,
                                           credential_current_sign_count=passkey.sign_count,
                                           require_user_verification=True)
    except (WebAuthnException, ValueError, KeyError, TypeError) as e:
        raise VerifyFailed(str(e)) from e
    return v.new_sign_count


def credential_id_of(credential: dict) -> bytes:
    """The browser's rawId, base64url → bytes. Raises VerifyFailed on anything odd."""
    raw = credential.get("rawId") if isinstance(credential, dict) else None
    if not isinstance(raw, str) or not _B64URL.fullmatch(raw):  # base64url_to_bytes silently drops bad characters
        raise VerifyFailed("missing or malformed rawId")
    try:
        return base64url_to_bytes(raw)
    except Exception as e:  # noqa: BLE001 - any decode failure is the same to the caller
        raise VerifyFailed("bad rawId") from e


def clean_label(label: str) -> str:
    return label.strip()[:LABEL_MAX]
