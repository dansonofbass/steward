import { api, patch } from '../api/client';

/** Sorting redesign, decision 9 and Settings; phase 17 spec 3.6: Celebrations (default on) and Sound (default off) are
 *  the person's, kept in the directory, where null means never chosen. Until /me says, and for a choice never made, the
 *  device's old stored choice stands in, then the defaults. Reduced motion on a device always wins. The theme stays per
 *  device (lib/theme.ts). */
export const REDUCE = '(prefers-reduced-motion: reduce)';
const KEY = 'steward-celebrations';
const SOUND_KEY = 'steward-sound';

export type Prefs = { celebrations: boolean | null; sound: boolean | null };
type Send = (body: Partial<Record<keyof Prefs, boolean>>) => Promise<unknown>;
const UNCHOSEN: Prefs = { celebrations: null, sound: null };
const send: Send = (body) => api('/api/auth/me', patch(body));
let person: Prefs = UNCHOSEN;
let adopted = false;

/** The signed-in person's switches, from /me. */
export function setPersonPrefs(p: Prefs | null | undefined): void { person = p ?? UNCHOSEN; }
/** For tests and sign-out: forget the person and the adoption. */
export function forgetPersonPrefs(): void { person = UNCHOSEN; adopted = false; }

function device(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

export const reducedMotion = (): boolean => typeof window.matchMedia === 'function' && window.matchMedia(REDUCE).matches;
export const celebrationsChosen = (): boolean => person.celebrations ?? (device(KEY) !== 'off');
export const celebrationsOn = (): boolean => celebrationsChosen() && !reducedMotion();
export const soundOn = (): boolean => person.sound ?? (device(SOUND_KEY) === 'on');

/** Settings › Appearance: saves one switch for the person. It shows at once; a refusal puts it back and throws. */
export async function savePref(key: keyof Prefs, on: boolean, post: Send = send): Promise<void> {
  const before = person;
  person = { ...person, [key]: on };
  try {
    await post({ [key]: on });
  } catch (e) {
    person = before;
    throw e;
  }
}

function forgetDevice(): void {
  try { localStorage.removeItem(KEY); localStorage.removeItem(SOUND_KEY); } catch { /* private mode */ }
}

/** Spec 3.6, the first load after the deploy: where the person never chose and this device stored a choice, the
 *  device's choice is sent once; then the server's rules. After the first answer the device's old keys are forgotten,
 *  so the next person on a shared device starts from the defaults. A refused send keeps them for the next load. */
export async function adoptPrefs(server: Prefs | null | undefined, post: Send = send): Promise<boolean> {
  setPersonPrefs(server);
  if (adopted) return false;
  const s = server ?? UNCHOSEN;
  const body: Partial<Record<keyof Prefs, boolean>> = {};
  if (s.celebrations === null && device(KEY) === 'off') body.celebrations = false;
  if (s.sound === null && device(SOUND_KEY) === 'on') body.sound = true;
  adopted = true;
  if (Object.keys(body).length === 0) { forgetDevice(); return false; }
  person = { ...s, ...body };
  try {
    await post(body);
    forgetDevice();
    return true;                              // the caller refreshes /me, so the server's values rule from here
  } catch {
    adopted = false;
    return false;
  }
}

export type Celebrate = typeof import('../celebrate/celebrate');
let chunk: Promise<Celebrate> | null = null;

/** Runs fn with the celebrate chunk, loading it on the first celebration of the visit (spec, Celebrations). While
 *  celebrations are off nothing is loaded or run; if the chunk can't load, the next call tries again. Either way it
 *  resolves to undefined. */
export function withCelebrate<T>(fn: (c: Celebrate) => T): Promise<T | undefined> {
  if (!celebrationsOn()) return Promise.resolve(undefined);
  chunk ??= import('../celebrate/celebrate');
  return chunk.then(fn, () => { chunk = null; return undefined; });
}
