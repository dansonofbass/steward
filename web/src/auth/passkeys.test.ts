import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from 'vitest';

vi.mock('@simplewebauthn/browser', async (orig) => ({
  ...(await orig<typeof import('@simplewebauthn/browser')>()),
  startRegistration: vi.fn(),
  startAuthentication: vi.fn(),
}));
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: vi.fn(async () => ({ options: {}, challenge_id: 'c' })),
}));

import { startAuthentication, startRegistration, WebAuthnAbortService, WebAuthnError } from '@simplewebauthn/browser';
import { api, ApiError } from '../api/client';
import { useFakeTimers } from '../test-clock';
import {
  AUTOFILL_MIN_GAP_MS, AUTOFILL_REFRESH_MS, CHALLENGE_LIFE_MS, offerPasskeysInAutofill, registerThisDevice, signInFromAutofill,
  signInWithPasskey, tellDeviceAccepted,
} from './passkeys';

const ALREADY = 'This device already has a Steward passkey for you. Sign in with it.';
const CLOSED = 'The passkey prompt was closed or timed out. Try again.';
const FAILED = "That didn't finish. Try again.";

const webauthn = (code: ConstructorParameters<typeof WebAuthnError>[0]['code'], name: string) =>
  new WebAuthnError({ message: 'x', code, cause: Object.assign(new Error('x'), { name }) });
const named = (name: string) => Object.assign(new Error('x'), { name });

beforeEach(() => vi.clearAllMocks());

describe('registration failures', () => {
  const run = async (err: unknown) => {
    vi.mocked(startRegistration).mockRejectedValueOnce(err);
    return registerThisDevice('Phone', 'pw').catch((e: Error) => e.message);
  };
  it('explains a synced passkey', async () => {
    expect(await run(webauthn('ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED', 'InvalidStateError'))).toBe(ALREADY);
    expect(await run(named('InvalidStateError'))).toBe(ALREADY);
  });
  it('explains a closed or timed-out prompt', async () => {
    expect(await run(webauthn('ERROR_CEREMONY_ABORTED', 'AbortError'))).toBe(CLOSED);
    expect(await run(named('NotAllowedError'))).toBe(CLOSED);
  });
  it('keeps the generic message for anything else', async () => {
    expect(await run(webauthn('ERROR_INVALID_RP_ID', 'SecurityError'))).toBe(FAILED);
    expect(await run('boom')).toBe(FAILED);
  });
});

describe('sign-in failures', () => {
  const run = async (err: unknown) => {
    vi.mocked(startAuthentication).mockRejectedValueOnce(err);
    return signInWithPasskey('Phone').catch((e: Error) => e.message);
  };
  it('explains a closed or timed-out prompt', async () => {
    expect(await run(named('NotAllowedError'))).toBe(CLOSED);
    expect(await run(webauthn('ERROR_CEREMONY_ABORTED', 'AbortError'))).toBe(CLOSED);
  });
  it('does not call an InvalidStateError a synced passkey', async () => {
    expect(await run(named('InvalidStateError'))).toBe(FAILED);
  });
  it('keeps the generic message for anything else', async () => {
    expect(await run(webauthn('ERROR_INVALID_RP_ID', 'SecurityError'))).toBe(FAILED);
  });
});

// Issue #13: the device's credential manager hears about passkeys the server no longer accepts, and the username box
// offers this site's passkeys through the browser's autofill (conditional mediation).
const RP = 'nas.example.ts.net';
const OPTIONS = { options: { challenge: 'Y2g', rpId: RP }, challenge_id: 'c' };
const ASSERTION = { id: 'Y3JlZC0x', rawId: 'Y3JlZC0x', response: {}, type: 'public-key', clientExtensionResults: {} };
const USER = { id: 1, username: 'jr', display_name: 'JR', email: null };
const UNKNOWN = "That passkey isn't registered any more. Sign in with your password and add it again.";
const EXPIRED = 'That sign-in attempt expired. Try again.';
/** login/verify's answers as api() throws them, with the `code` api/passkeys.py sends. */
const unknownAnswer = () => new ApiError(401, UNKNOWN, { error: UNKNOWN, code: 'unknown_credential' });
const expiredAnswer = () => new ApiError(400, EXPIRED, { error: EXPIRED, code: 'expired' });

function server(calls: Record<string, () => unknown>) {
  vi.mocked(api).mockImplementation(async (path: string) => {
    const answer = calls[path];
    if (!answer) throw new Error(`unexpected ${path}`);
    return answer() as never;
  });
}

/** A browser with PublicKeyCredential and only the given static methods. */
function browser(statics: Record<string, unknown>) {
  vi.stubGlobal('PublicKeyCredential', Object.assign(function PublicKeyCredential() {}, statics));
}

afterEach(() => vi.unstubAllGlobals());

describe('a passkey the server no longer knows', () => {
  it('is reported to the device, and the server words still show', async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    browser({ signalUnknownCredential });
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw unknownAnswer(); } });
    expect(await signInWithPasskey('Phone').catch((e: Error) => e.message)).toBe(UNKNOWN);
    expect(signalUnknownCredential).toHaveBeenCalledWith({ rpId: RP, credentialId: 'Y3JlZC0x' });
  });
  it('is only reported on the unknown answer, and a browser without the call is fine', async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    browser({ signalUnknownCredential });
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never).mockResolvedValueOnce(ASSERTION as never);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw new ApiError(400, "That passkey couldn't be checked. Try again."); } });
    await signInWithPasskey('Phone').catch(() => undefined);
    expect(signalUnknownCredential).not.toHaveBeenCalled();
    browser({});
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw unknownAnswer(); } });
    expect(await signInWithPasskey('Phone').catch((e: Error) => e.message)).toBe(UNKNOWN);
  });
  it('is not reported on a 401 without Steward\'s own answer, such as a proxy in front asking for its sign-in', async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    browser({ signalUnknownCredential });
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never).mockResolvedValueOnce(ASSERTION as never);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw new ApiError(401, 'Something went wrong (401).', null); } });
    await signInWithPasskey('Phone').catch(() => undefined);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw new ApiError(401, UNKNOWN, { error: UNKNOWN }); } });
    await signInWithPasskey('Phone').catch(() => undefined);
    expect(signalUnknownCredential).not.toHaveBeenCalled();
  });
});

describe('after a removal', () => {
  const accepted = { rp_id: RP, user_id: 'MQ', credential_ids: ['Y3JlZC0y'] };
  it('tells the device which passkeys still sign in', async () => {
    const signalAllAcceptedCredentials = vi.fn(async () => undefined);
    browser({ signalAllAcceptedCredentials });
    await tellDeviceAccepted(accepted);
    expect(signalAllAcceptedCredentials).toHaveBeenCalledWith({ rpId: RP, userId: 'MQ', allAcceptedCredentialIds: ['Y3JlZC0y'] });
  });
  it('does nothing where the browser lacks the call, and a refusal stays quiet', async () => {
    await tellDeviceAccepted(accepted);                       // no PublicKeyCredential at all
    browser({});
    await tellDeviceAccepted(accepted);
    browser({ signalAllAcceptedCredentials: vi.fn(async () => { throw named('SecurityError'); }) });
    await tellDeviceAccepted(accepted);
    await tellDeviceAccepted(undefined);                      // an answer without the list
  });
});

describe('passkeys in the username box', () => {
  const autofillBrowser = (more: Record<string, unknown> = {}) => browser({ isConditionalMediationAvailable: async () => true, ...more });

  it('are not asked for where the browser has no autofill for them', async () => {
    browser({ isConditionalMediationAvailable: async () => false });
    expect(await signInFromAutofill('Phone', new AbortController().signal)).toBeNull();
    browser({});
    expect(await signInFromAutofill('Phone', new AbortController().signal)).toBeNull();
    expect(api).not.toHaveBeenCalled();
    expect(startAuthentication).not.toHaveBeenCalled();
  });

  it('sign in when one is picked', async () => {
    autofillBrowser();
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS, '/api/auth/passkeys/login/verify': () => ({ user: USER }) });
    expect(await signInFromAutofill('Phone', new AbortController().signal)).toEqual(USER);
    expect(startAuthentication).toHaveBeenCalledWith({ optionsJSON: { ...OPTIONS.options, timeout: CHALLENGE_LIFE_MS }, useBrowserAutofill: true });
    expect(vi.mocked(api).mock.calls[1]).toEqual(['/api/auth/passkeys/login/verify', expect.objectContaining({
      body: JSON.stringify({ challenge_id: 'c', credential: ASSERTION, device_label: 'Phone' }) })]);
  });

  it('stop waiting when told to, and say nothing', async () => {
    autofillBrowser();
    const cancel = vi.spyOn(WebAuthnAbortService, 'cancelCeremony');
    const stop = new AbortController();
    vi.mocked(startAuthentication).mockImplementationOnce(() => new Promise((_, reject) => {
      cancel.mockImplementationOnce(() => reject(webauthn('ERROR_CEREMONY_ABORTED', 'AbortError')));
    }));
    server({ '/api/auth/passkeys/login/options': () => OPTIONS });
    const waiting = signInFromAutofill('Phone', stop.signal);
    await vi.waitFor(() => expect(startAuthentication).toHaveBeenCalled());
    stop.abort();
    expect(await waiting).toBeNull();
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(api).toHaveBeenCalledTimes(1);                     // no verify
    cancel.mockRestore();
  });

  it('never start when told to stop before the options came back', async () => {
    autofillBrowser();
    const cancel = vi.spyOn(WebAuthnAbortService, 'cancelCeremony');
    const stop = new AbortController();
    server({ '/api/auth/passkeys/login/options': () => { stop.abort(); return OPTIONS; } });
    expect(await signInFromAutofill('Phone', stop.signal)).toBeNull();
    expect(startAuthentication).not.toHaveBeenCalled();
    expect(cancel).not.toHaveBeenCalled();                    // nothing of ours to cancel; the button's prompt is left alone
    cancel.mockRestore();
  });

  it('stay quiet when the options or the browser fail, since the button still works', async () => {
    autofillBrowser();
    server({ '/api/auth/passkeys/login/options': () => { throw new ApiError(429, 'Too many tries.'); } });
    expect(await signInFromAutofill('Phone', new AbortController().signal)).toBeNull();
    vi.mocked(startAuthentication).mockRejectedValueOnce(named('NotAllowedError'));
    server({ '/api/auth/passkeys/login/options': () => OPTIONS });
    expect(await signInFromAutofill('Phone', new AbortController().signal)).toBeNull();
  });

  it('report an unknown passkey to the device and show the server words', async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    autofillBrowser({ signalUnknownCredential });
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ '/api/auth/passkeys/login/options': () => OPTIONS,
      '/api/auth/passkeys/login/verify': () => { throw unknownAnswer(); } });
    expect(await signInFromAutofill('Phone', new AbortController().signal).catch((e: Error) => e.message)).toBe(UNKNOWN);
    expect(signalUnknownCredential).toHaveBeenCalledWith({ rpId: RP, credentialId: 'Y3JlZC0x' });
  });
});

describe('passkeys stay on offer in the username box while the page is open', () => {
  const OPTIONS_PATH = '/api/auth/passkeys/login/options';
  const VERIFY_PATH = '/api/auth/passkeys/login/verify';
  const asked = (path: string) => vi.mocked(api).mock.calls.filter(([p]) => p === path).length;
  const settle = () => vi.advanceTimersByTimeAsync(0);
  const STALE_TICK = 30_000;                                   // passkeys.ts STALE_CHECK_MS
  let cancel: MockInstance<() => void>;
  let visibility: DocumentVisibilityState;

  beforeEach(() => {
    useFakeTimers();
    browser({ isConditionalMediationAvailable: async () => true });
    visibility = 'visible';
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility });
    cancel = vi.spyOn(WebAuthnAbortService, 'cancelCeremony');
    // A conditional request stays open until it is cancelled.
    vi.mocked(startAuthentication).mockImplementation(() => new Promise((_, reject) => {
      cancel.mockImplementationOnce(() => reject(webauthn('ERROR_CEREMONY_ABORTED', 'AbortError')));
    }));
    server({ [OPTIONS_PATH]: () => OPTIONS });
  });
  afterEach(() => {
    cancel.mockRestore();
    vi.mocked(startAuthentication).mockReset();
    delete (document as { visibilityState?: unknown }).visibilityState;
  });

  function offer(lastStart?: { current: number }) {
    const stop = new AbortController();
    const onRefused = vi.fn();
    const checking = vi.fn();
    return { stop, onRefused, checking, result: offerPasskeysInAutofill('Phone', stop.signal, { onRefused, checking, lastStart }) };
  }
  /** The username box, on the page, whose autofill offers passkeys. */
  function usernameBox() {
    const box = document.createElement('input');
    box.setAttribute('autocomplete', 'username webauthn');
    document.body.append(box);
    return box;
  }

  it('fetch a fresh challenge before the old one expires, four times in 15 minutes', async () => {
    const { stop, result } = offer();
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(AUTOFILL_REFRESH_MS - 1);
    expect(asked(OPTIONS_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(asked(OPTIONS_PATH)).toBe(2);
    expect(startAuthentication).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(15 * 60_000 - AUTOFILL_REFRESH_MS - 1000);
    expect(asked(OPTIONS_PATH)).toBe(4);                       // well inside the 30 the options allow
    stop.abort();
    expect(await result).toBeNull();
    expect(asked(OPTIONS_PATH)).toBe(4);
  });

  it('start again a full round later when the options or the browser fail', async () => {
    vi.mocked(startAuthentication).mockRejectedValueOnce(named('NotAllowedError'));
    const { stop, result, onRefused } = offer();
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(AUTOFILL_MIN_GAP_MS);
    expect(asked(OPTIONS_PATH)).toBe(1);
    server({ [OPTIONS_PATH]: () => { throw new ApiError(429, 'Too many tries.'); } });
    await vi.advanceTimersByTimeAsync(AUTOFILL_REFRESH_MS - AUTOFILL_MIN_GAP_MS);
    expect(asked(OPTIONS_PATH)).toBe(2);
    server({ [OPTIONS_PATH]: () => OPTIONS });
    await vi.advanceTimersByTimeAsync(AUTOFILL_REFRESH_MS);
    expect(asked(OPTIONS_PATH)).toBe(3);
    expect(startAuthentication).toHaveBeenCalledTimes(2);
    expect(onRefused).not.toHaveBeenCalled();
    stop.abort();
    expect(await result).toBeNull();
  });

  it('start again quietly when a pick finds its challenge expired', async () => {
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ [OPTIONS_PATH]: () => OPTIONS, [VERIFY_PATH]: () => { throw expiredAnswer(); } });
    const { stop, result, onRefused } = offer();
    await settle();
    expect(asked(VERIFY_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(AUTOFILL_MIN_GAP_MS);
    expect(asked(OPTIONS_PATH)).toBe(2);
    expect(startAuthentication).toHaveBeenCalledTimes(2);
    expect(onRefused).not.toHaveBeenCalled();
    stop.abort();
    expect(await result).toBeNull();
  });

  it('say why a pick was refused, then offer passkeys again, and sign in with the next pick', async () => {
    const signalUnknownCredential = vi.fn(async () => undefined);
    browser({ isConditionalMediationAvailable: async () => true, signalUnknownCredential });
    let verifies = 0;
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never).mockResolvedValueOnce(ASSERTION as never);
    server({ [OPTIONS_PATH]: () => OPTIONS,
      [VERIFY_PATH]: () => { if (verifies++ === 0) throw unknownAnswer(); return { user: USER }; } });
    const { result, onRefused } = offer();
    await settle();
    expect(onRefused).toHaveBeenCalledWith(expect.objectContaining({ message: UNKNOWN }));
    expect(signalUnknownCredential).toHaveBeenCalledWith({ rpId: RP, credentialId: 'Y3JlZC0x' });
    await vi.advanceTimersByTimeAsync(AUTOFILL_MIN_GAP_MS);
    expect(await result).toEqual(USER);
    expect(asked(OPTIONS_PATH)).toBe(2);
  });

  it('fetch nothing while the page is hidden, and start again when it is in view', async () => {
    const { stop, result } = offer();
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    visibility = 'hidden';
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(8 * 60 * 60_000);       // a night in a background tab
    expect(asked(OPTIONS_PATH)).toBe(1);
    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(2);
    stop.abort();
    expect(await result).toBeNull();
  });

  it('fetch a fresh challenge when the box is tapped on a device woken from sleep', async () => {
    const { stop, result } = offer();
    await settle();
    vi.setSystemTime(Date.now() + 8 * 60 * 60_000);           // the device slept, and no timer ran
    document.dispatchEvent(new FocusEvent('focusin'));
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(2);
    stop.abort();
    expect(await result).toBeNull();
  });

  it('ask nothing where the browser has no autofill for passkeys', async () => {
    browser({ isConditionalMediationAvailable: async () => false });
    expect(await offer().result).toBeNull();
    expect(api).not.toHaveBeenCalled();
  });

  it('leave the list alone while the box has focus, since the person may be picking, and catch up when it leaves', async () => {
    const box = usernameBox();
    const { stop, result } = offer();
    await settle();
    box.focus();                                               // the box's list is open, mid-pick
    await vi.advanceTimersByTimeAsync(AUTOFILL_REFRESH_MS);
    visibility = 'visible';
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(5 * 60_000);
    expect(asked(OPTIONS_PATH)).toBe(1);
    expect(cancel).not.toHaveBeenCalled();
    box.blur();
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(2);
    stop.abort();
    expect(await result).toBeNull();
    box.remove();
  });

  it('check the challenge when focus arrives in the box, before its list opens', async () => {
    const box = usernameBox();
    const { stop, result } = offer();
    await settle();
    await vi.advanceTimersByTimeAsync(AUTOFILL_REFRESH_MS - STALE_TICK);
    vi.setSystemTime(Date.now() + STALE_TICK);                 // old now, and no tick has run yet
    box.focus();
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(2);
    stop.abort();
    expect(await result).toBeNull();
    box.remove();
  });

  it('keep the wait when the window\'s focus goes to the device\'s passkey prompt and comes back', async () => {
    const box = usernameBox();
    box.focus();
    const { stop, result } = offer();
    await settle();
    vi.setSystemTime(Date.now() + AUTOFILL_REFRESH_MS);
    // The window lost focus and got it back; the box stayed the active element throughout.
    box.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    await settle();
    box.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    expect(cancel).not.toHaveBeenCalled();
    stop.abort();
    expect(await result).toBeNull();
    box.blur();
    box.remove();
  });

  it('wait out the minimum gap when started again, counting from the last start before', async () => {
    const lastStart = { current: -Infinity };
    const first = offer(lastStart);
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    first.stop.abort();                                        // the button was pressed, and its prompt failed
    expect(await first.result).toBeNull();
    const second = offer(lastStart);
    await settle();
    expect(asked(OPTIONS_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(AUTOFILL_MIN_GAP_MS - 1);
    expect(asked(OPTIONS_PATH)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(asked(OPTIONS_PATH)).toBe(2);
    second.stop.abort();
    expect(await second.result).toBeNull();
  });

  it('say when a pick is with the server, and keep a sign-in that lands after being stopped', async () => {
    let answer!: (v: unknown) => void;
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ [OPTIONS_PATH]: () => OPTIONS, [VERIFY_PATH]: () => new Promise((r) => { answer = r; }) });
    const { stop, result, checking } = offer();
    await settle();
    expect(checking).toHaveBeenCalledWith(true);
    stop.abort();                                              // the session may exist already
    answer({ user: USER });
    expect(await result).toEqual(USER);
    expect(checking).not.toHaveBeenCalledWith(false);
  });

  it('say when the server has refused a pick, so the page is usable again', async () => {
    vi.mocked(startAuthentication).mockResolvedValueOnce(ASSERTION as never);
    server({ [OPTIONS_PATH]: () => OPTIONS, [VERIFY_PATH]: () => { throw unknownAnswer(); } });
    const { stop, result, checking, onRefused } = offer();
    await settle();
    expect(checking.mock.calls).toEqual([[true], [false]]);
    expect(onRefused).toHaveBeenCalledTimes(1);
    stop.abort();
    expect(await result).toBeNull();
  });
});
