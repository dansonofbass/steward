/** A short, plain guess at what the user is holding, for labelling passkeys and sessions. */
export type DeviceName = 'iPhone' | 'iPad' | 'Android phone' | 'Windows PC' | 'Mac' | 'This device';

export function deviceName(ua: string): DeviceName {
  if (/iPhone/i.test(ua)) return 'iPhone';
  if (/iPad/i.test(ua)) return 'iPad';
  if (/Android/i.test(ua)) return 'Android phone';
  if (/Windows/i.test(ua)) return 'Windows PC';
  if (/Macintosh|Mac OS X/i.test(ua)) return 'Mac';
  return 'This device';
}

function browserName(ua: string): string | null {
  if (/Edg(e|A|iOS)?\//.test(ua)) return 'Edge';
  if (/Firefox\/|FxiOS\//.test(ua)) return 'Firefox';
  if (/Chrome\/|CriOS\//.test(ua)) return 'Chrome';
  if (/Safari\//.test(ua)) return 'Safari';
  return null;
}

/** The label stored with a session, e.g. "iPhone · Safari". It never says "This device", which marks the current session in the list. */
export function deviceLabel(ua: string): string {
  const device = deviceName(ua);
  const parts = [device === 'This device' ? null : device, browserName(ua)].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'Browser';
}
