import {
  browserSupportsWebAuthn, browserSupportsWebAuthnAutofill, sendSignal, startAuthentication, startRegistration, WebAuthnAbortService,
  WebAuthnError, type AuthenticationResponseJSON,
} from '@simplewebauthn/browser';
import { api, ApiError, json } from '../api/client';
import type { Me, Passkey } from '../api/types';

export const supported = () => browserSupportsWebAuthn();
const FAILED = "That didn't finish. Try again.";
const ALREADY_REGISTERED = 'This device already has a Steward passkey for you. Sign in with it.';
const CLOSED = 'The passkey prompt was closed or timed out. Try again.';

type Challenge = { options: Parameters<typeof startAuthentication>[0]['optionsJSON']; challenge_id: string };
/** What a removal answers (api/passkeys.py delete_passkey): the passkeys this person can still sign in with. */
export type Accepted = { rp_id: string; user_id: string; credential_ids: string[] };

function browserFailure(e: unknown, ceremony: 'registration' | 'authentication'): never {
  if (e instanceof ApiError) throw e;
  const code = e instanceof WebAuthnError ? e.code : undefined;
  const name = e instanceof Error ? e.name : undefined;
  if (ceremony === 'registration' && (code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED' || name === 'InvalidStateError')) {
    throw new ApiError(0, ALREADY_REGISTERED);
  }
  if (code === 'ERROR_CEREMONY_ABORTED' || name === 'NotAllowedError' || name === 'AbortError' || name === 'TimeoutError') {
    throw new ApiError(0, CLOSED);
  }
  throw new ApiError(0, FAILED);
}

// Issue #13: the WebAuthn signal calls tell the device's credential manager what the server accepts, so it stops
// offering a passkey that would only fail. They are new and not in every browser, so each is looked for first, and
// a refusal is never the person's problem.
function hasSignal(name: 'signalUnknownCredential' | 'signalAllAcceptedCredentials'): boolean {
  const pkc = (globalThis as unknown as { PublicKeyCredential?: Record<string, unknown> }).PublicKeyCredential;
  return typeof pkc?.[name] === 'function';
}

async function tellDeviceUnknown(rpID: string, credentialID: string): Promise<void> {
  if (!hasSignal('signalUnknownCredential')) return;
  try { await sendSignal({ signalName: 'unknownCredential', rpID, credentialID }); } catch { /* best effort */ }
}

export async function tellDeviceAccepted(accepted: Accepted | undefined): Promise<void> {
  if (!accepted || !hasSignal('signalAllAcceptedCredentials')) return;
  try {
    await sendSignal({ signalName: 'allAcceptedCredentials', rpID: accepted.rp_id, userID: accepted.user_id,
      allAcceptedCredentialIDs: accepted.credential_ids });
  } catch { /* best effort */ }
}

export async function registerThisDevice(label: string, currentPassword: string): Promise<Passkey> {
  const { options, challenge_id } = await api<{ options: Parameters<typeof startRegistration>[0]['optionsJSON']; challenge_id: string }>(
    '/api/auth/passkeys/register/options', json({ current_password: currentPassword }));
  let credential;
  try { credential = await startRegistration({ optionsJSON: options }); } catch (e) { browserFailure(e, 'registration'); }
  const r = await api<{ passkey: Passkey }>('/api/auth/passkeys/register/verify', json({ challenge_id, credential, label }));
  return r.passkey;
}

async function verify(challenge: Challenge, credential: AuthenticationResponseJSON, deviceLabel: string): Promise<Me['user']> {
  try {
    const r = await api<{ user: Me['user'] }>('/api/auth/passkeys/login/verify',
      json({ challenge_id: challenge.challenge_id, credential, device_label: deviceLabel }));
    return r.user;
  } catch (e) {
    // Only Steward's own "no record of this passkey" (removed, or from an old install) has the device forget it. A 401
    // from a proxy in front of Steward says nothing about the passkey.
    if (said(e, 'unknown_credential')) void tellDeviceUnknown(challenge.options.rpId ?? location.hostname, credential.id);
    throw e;
  }
}

/** The machine-readable `code` on a refusal from api/passkeys.py (EXPIRED, UNKNOWN). */
function said(e: unknown, code: 'expired' | 'unknown_credential'): boolean {
  return e instanceof ApiError && (e.body as { code?: unknown } | null)?.code === code;
}

export async function signInWithPasskey(deviceLabel: string): Promise<Me['user']> {
  const challenge = await api<Challenge>('/api/auth/passkeys/login/options', json({}));
  let credential;
  try { credential = await startAuthentication({ optionsJSON: challenge.options }); } catch (e) { browserFailure(e, 'authentication'); }
  return verify(challenge, credential, deviceLabel);
}

/** Offers this site's passkeys in the username box's autofill (conditional mediation), where the browser can. Resolves
 * with the person once one is picked and checks out; null when the browser can't, when `stop` fires before a pick (the
 * button was used, or the page closed), or when the browser gives up, since the button still works and says why. A
 * server refusal after a pick is thrown, as the button's is. `onPicked` runs when a pick goes to the server; from
 * then on `stop` changes nothing, because the server may already have signed the person in. */
export async function signInFromAutofill(deviceLabel: string, stop: AbortSignal,
  onPicked?: () => void): Promise<Me['user'] | null> {
  if (!(await browserSupportsWebAuthnAutofill()) || stop.aborted) return null;
  let challenge: Challenge;
  try {
    challenge = await api<Challenge>('/api/auth/passkeys/login/options', { ...json({}), signal: stop });
  } catch {
    return null;
  }
  if (stop.aborted) return null;
  // Cancel only our own wait: once the button's prompt is up, the shared abort service holds that one instead.
  const cancel = () => WebAuthnAbortService.cancelCeremony();
  stop.addEventListener('abort', cancel, { once: true });
  let credential;
  try {
    // The browser may end the wait at the options' timeout (60 s from py_webauthn). This wait is refreshed on its own
    // clock instead, so it asks for as long as the challenge lives.
    credential = await startAuthentication({ optionsJSON: { ...challenge.options, timeout: CHALLENGE_LIFE_MS }, useBrowserAutofill: true });
  } catch {
    return null;
  } finally {
    stop.removeEventListener('abort', cancel);
  }
  if (stop.aborted) return null;
  onPicked?.();
  return verify(challenge, credential, deviceLabel);
}

/** A login challenge lives 300 s on the server (auth/passkeys.py CHALLENGE_TTL_S). */
export const CHALLENGE_LIFE_MS = 300_000;
/** The username box's wait starts again with fresh options this long after it fetched them, inside the challenge's
 * life, so a pick from a sign-in page left open still checks out. */
export const AUTOFILL_REFRESH_MS = 240_000;
/** Waits start at least this far apart, so repeated refused picks can't spend the options budget the button needs
 * (30 per 15 minutes, auth/ratelimit.py PASSKEY_OPTIONS). */
export const AUTOFILL_MIN_GAP_MS = 60_000;
const STALE_CHECK_MS = 30_000;

/** Resolves once `notBefore` has passed and the page is in view, or when `stop` fires. A hidden page fetches nothing. */
function ready(stop: AbortSignal, notBefore: number): Promise<void> {
  return new Promise((resolve) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const done = () => {
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', check);
      stop.removeEventListener('abort', done);
      resolve();
    };
    function check() {
      clearTimeout(timer);
      if (stop.aborted) return done();
      const wait = notBefore - Date.now();
      if (wait > 0) timer = setTimeout(check, wait);
      else if (document.visibilityState !== 'hidden') done();
    }
    document.addEventListener('visibilitychange', check);
    stop.addEventListener('abort', done, { once: true });
    check();
  });
}

/** The username box whose autofill offers passkeys (autocomplete has the `webauthn` token). */
function isPasskeyBox(el: EventTarget | null): boolean {
  return el instanceof HTMLInputElement && (el.getAttribute('autocomplete') ?? '').split(/\s+/).includes('webauthn');
}

export type AutofillHooks = {
  /** A pick the server refused; an expired challenge starts again without one. */
  onRefused: (e: ApiError) => void;
  /** True when a pick goes to the server, false when the server refused it. Nothing else should sign in meanwhile. */
  checking?: (on: boolean) => void;
  /** When the last wait started, kept from one call to the next, so a caller that starts the offer again (after the
   * button's prompt or a password try) still waits out AUTOFILL_MIN_GAP_MS. */
  lastStart?: { current: number };
};

/** Keeps this site's passkeys on offer in the username box for as long as the sign-in page is open (issue #13).
 * Each wait uses a fresh challenge and starts again when the challenge gets old, when the browser ends it, or after
 * a pick the server refused. Resolves with the person once a pick checks out, even if `stop` fired while the server
 * was checking it (the session exists by then), and null when the browser can't offer passkeys there or `stop` fires
 * before a pick. */
export async function offerPasskeysInAutofill(deviceLabel: string, stop: AbortSignal,
  { onRefused, checking, lastStart = { current: -Infinity } }: AutofillHooks): Promise<Me['user'] | null> {
  if (!(await browserSupportsWebAuthnAutofill())) return null;
  let gap = AUTOFILL_MIN_GAP_MS;
  while (!stop.aborted) {
    await ready(stop, lastStart.current + gap);
    if (stop.aborted) break;
    const started = Date.now();
    lastStart.current = started;
    const round = new AbortController();
    const end = () => round.abort();
    // Date.now() keeps counting while the device sleeps, so a page woken after a night still refreshes.
    const old = () => Date.now() - started >= AUTOFILL_REFRESH_MS;
    // Ending a wait closes the browser's passkey list, so the clock and the page coming into view leave it alone while
    // the box has focus: the person may be picking. Focus arriving in the box checks first, before the list opens, and
    // focus leaving it catches up once focus has landed. A window that loses focus to the device's own passkey prompt
    // keeps the box as its active element, so its focus coming back is not an arrival. A challenge that runs out
    // during a pick comes back `expired` and starts again quietly.
    const stale = () => { if (!isPasskeyBox(document.activeElement) && old()) end(); };
    let inBox = isPasskeyBox(document.activeElement);
    const arriving = (e: FocusEvent) => {
      const back = inBox && isPasskeyBox(e.target);
      inBox = isPasskeyBox(e.target);
      if (!back && old()) end();
    };
    let landed: ReturnType<typeof setTimeout> | undefined;
    const leaving = () => {
      clearTimeout(landed);
      landed = setTimeout(() => { inBox = isPasskeyBox(document.activeElement); stale(); }, 0);
    };
    stop.addEventListener('abort', end, { once: true });
    const tick = setInterval(stale, STALE_CHECK_MS);
    document.addEventListener('visibilitychange', stale);
    document.addEventListener('focusin', arriving);
    document.addEventListener('focusout', leaving);
    try {
      const user = await signInFromAutofill(deviceLabel, round.signal, () => checking?.(true));
      if (user) return user;
      // Ended without our asking: the options were refused (429) or the browser gave up. Wait a full round.
      gap = round.signal.aborted ? AUTOFILL_MIN_GAP_MS : AUTOFILL_REFRESH_MS;
    } catch (e) {
      gap = AUTOFILL_MIN_GAP_MS;
      checking?.(false);
      if (!stop.aborted && !said(e, 'expired')) onRefused(e instanceof ApiError ? e : new ApiError(0, FAILED));
    } finally {
      clearInterval(tick);
      clearTimeout(landed);
      document.removeEventListener('visibilitychange', stale);
      document.removeEventListener('focusin', arriving);
      document.removeEventListener('focusout', leaving);
      stop.removeEventListener('abort', end);
    }
  }
  return null;
}
