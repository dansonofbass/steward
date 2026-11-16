import { useEffect, useState } from 'react';

/** Why passkeys can't work at this address in this browser: its certificate isn't trusted here, or it's an IP address. */
export type PasskeyBlock = 'certificate' | 'address';

/** Install gate INS-22: a page reached past a certificate warning still has https and isSecureContext, and Chrome's
 *  getClientCapabilities() and isUserVerifyingPlatformAuthenticatorAvailable() answer as on a trusted page. Only a real
 *  request tells: Chrome refuses navigator.credentials.get at once with NotAllowedError ("WebAuthn is not supported on
 *  sites with TLS certificate errors"), and an IP address gets SecurityError (a passkey needs a name). A conditional
 *  request shows nothing without a passkey field on the page, so on a trusted page it waits, silently, until the
 *  page aborts it. Anything else, or no WebAuthn at all, leaves the server's answer standing. */
export function probePasskeys(signal: AbortSignal): Promise<PasskeyBlock | null> {
  if (typeof PublicKeyCredential === 'undefined' || !navigator.credentials?.get) return Promise.resolve(null);
  const publicKey: PublicKeyCredentialRequestOptions = {
    challenge: crypto.getRandomValues(new Uint8Array(32)), allowCredentials: [], userVerification: 'preferred',
  };
  const why = (e: unknown): PasskeyBlock | null => {
    const name = e instanceof DOMException ? e.name : '';
    return name === 'NotAllowedError' ? 'certificate' : name === 'SecurityError' ? 'address' : null;
  };
  try {
    return navigator.credentials.get({ mediation: 'conditional', signal, publicKey }).then(() => null, why);
  } catch (e) {
    return Promise.resolve(why(e));
  }
}

/** The probe while `on`, aborted when the page closes or `on` turns off. */
export function usePasskeyBlock(on: boolean): PasskeyBlock | null {
  const [block, setBlock] = useState<PasskeyBlock | null>(null);
  useEffect(() => {
    if (!on) return undefined;
    const ac = new AbortController();
    void probePasskeys(ac.signal).then((b) => { if (!ac.signal.aborted) setBlock(b); });
    return () => ac.abort();
  }, [on]);
  return on ? block : null;
}
