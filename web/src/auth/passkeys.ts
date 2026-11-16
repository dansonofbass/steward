import { browserSupportsWebAuthn, startAuthentication, startRegistration, WebAuthnError } from '@simplewebauthn/browser';
import { api, ApiError, json } from '../api/client';
import type { Me, Passkey } from '../api/types';

export const supported = () => browserSupportsWebAuthn();
const FAILED = "That didn't finish. Try again.";
const ALREADY_REGISTERED = 'This device already has a Steward passkey for you. Sign in with it.';
const CLOSED = 'The passkey prompt was closed or timed out. Try again.';

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

export async function registerThisDevice(label: string, currentPassword: string): Promise<Passkey> {
  const { options, challenge_id } = await api<{ options: Parameters<typeof startRegistration>[0]['optionsJSON']; challenge_id: string }>(
    '/api/auth/passkeys/register/options', json({ current_password: currentPassword }));
  let credential;
  try { credential = await startRegistration({ optionsJSON: options }); } catch (e) { browserFailure(e, 'registration'); }
  const r = await api<{ passkey: Passkey }>('/api/auth/passkeys/register/verify', json({ challenge_id, credential, label }));
  return r.passkey;
}

export async function signInWithPasskey(deviceLabel: string): Promise<Me['user']> {
  const { options, challenge_id } = await api<{ options: Parameters<typeof startAuthentication>[0]['optionsJSON']; challenge_id: string }>(
    '/api/auth/passkeys/login/options', json({}));
  let credential;
  try { credential = await startAuthentication({ optionsJSON: options }); } catch (e) { browserFailure(e, 'authentication'); }
  const r = await api<{ user: Me['user'] }>('/api/auth/passkeys/login/verify', json({ challenge_id, credential, device_label: deviceLabel }));
  return r.user;
}
