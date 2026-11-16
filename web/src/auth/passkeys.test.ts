import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@simplewebauthn/browser', async (orig) => ({
  ...(await orig<typeof import('@simplewebauthn/browser')>()),
  startRegistration: vi.fn(),
  startAuthentication: vi.fn(),
}));
vi.mock('../api/client', async (orig) => ({
  ...(await orig<typeof import('../api/client')>()),
  api: vi.fn(async () => ({ options: {}, challenge_id: 'c' })),
}));

import { startAuthentication, startRegistration, WebAuthnError } from '@simplewebauthn/browser';
import { registerThisDevice, signInWithPasskey } from './passkeys';

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
