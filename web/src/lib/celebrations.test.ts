import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { adoptPrefs, celebrationsChosen, celebrationsOn, forgetPersonPrefs, savePref, setPersonPrefs, soundOn, withCelebrate } from './celebrations';

const reduce = (on: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
  matches: on && q === '(prefers-reduced-motion: reduce)', media: q, addEventListener: () => {}, removeEventListener: () => {} }));
const UNCHOSEN = { celebrations: null, sound: null };
beforeEach(() => { localStorage.clear(); forgetPersonPrefs(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('Celebrations and Sound, per person (phase 17 spec 3.6)', () => {
  it('Celebrations is on and Sound off by default', () => {
    setPersonPrefs(UNCHOSEN);
    expect([celebrationsOn(), soundOn()]).toEqual([true, false]);
  });

  it("the person's choice rules over anything this device stored", () => {
    localStorage.setItem('steward-celebrations', 'off');
    setPersonPrefs({ celebrations: true, sound: true });
    expect([celebrationsChosen(), soundOn()]).toEqual([true, true]);
  });

  it("until /me answers, and for a choice never made, the device's old choice stands in", () => {
    localStorage.setItem('steward-celebrations', 'off');
    localStorage.setItem('steward-sound', 'on');
    expect([celebrationsChosen(), soundOn()]).toEqual([false, true]);
  });

  it('reduced motion always wins', () => {
    reduce(true);
    setPersonPrefs({ celebrations: true, sound: true });
    expect([celebrationsChosen(), celebrationsOn()]).toEqual([true, false]);
  });

  it('a blocked storage reads as the defaults', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    expect([celebrationsOn(), soundOn()]).toEqual([true, false]);
  });

  it('saving a switch shows at once and goes back if the server refuses', async () => {
    const send = vi.fn().mockResolvedValueOnce(undefined).mockRejectedValueOnce(new Error('no'));
    setPersonPrefs(UNCHOSEN);
    await savePref('sound', true, send);
    expect(send).toHaveBeenCalledWith({ sound: true });
    expect(soundOn()).toBe(true);
    await expect(savePref('celebrations', false, send)).rejects.toThrow('no');
    expect(celebrationsChosen()).toBe(true);
  });
});

describe("adopting this device's choice, once (spec 3.6)", () => {
  it("takes the device's choice where the person never chose, then forgets it on the device", async () => {
    localStorage.setItem('steward-celebrations', 'off');
    localStorage.setItem('steward-sound', 'on');
    const send = vi.fn().mockResolvedValue(undefined);
    await adoptPrefs({ celebrations: null, sound: false }, send);
    expect(send).toHaveBeenCalledWith({ celebrations: false });              // sound was chosen: the server's stands
    expect([celebrationsChosen(), soundOn()]).toEqual([false, false]);
    expect([localStorage.getItem('steward-celebrations'), localStorage.getItem('steward-sound')]).toEqual([null, null]);
  });

  it('a second person on the same device gets the defaults, not the first one\'s old choice', async () => {
    localStorage.setItem('steward-celebrations', 'off');
    const send = vi.fn().mockResolvedValue(undefined);
    await adoptPrefs(UNCHOSEN, send);                                       // the first person adopts it
    await adoptPrefs(UNCHOSEN, send);                                       // the next sign-in on this device
    expect(send).toHaveBeenCalledOnce();
    setPersonPrefs(UNCHOSEN);
    expect(celebrationsChosen()).toBe(true);
  });

  it('with nothing stored on the device nothing is sent', async () => {
    const send = vi.fn();
    await adoptPrefs(UNCHOSEN, send);
    expect(send).not.toHaveBeenCalled();
  });

  it('a refused adoption keeps the device choice, and tries again on the next load', async () => {
    localStorage.setItem('steward-sound', 'on');
    const send = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(undefined);
    await adoptPrefs(UNCHOSEN, send);
    expect([localStorage.getItem('steward-sound'), soundOn()]).toEqual(['on', true]);
    await adoptPrefs(UNCHOSEN, send);
    expect(send).toHaveBeenLastCalledWith({ sound: true });
    expect(localStorage.getItem('steward-sound')).toBeNull();
  });
});

describe('withCelebrate', () => {
  it('runs nothing while off, and hands over the chunk while on', async () => {
    setPersonPrefs({ celebrations: false, sound: null });
    const fn = vi.fn();
    expect(await withCelebrate(fn)).toBeUndefined();
    expect(fn).not.toHaveBeenCalled();
    setPersonPrefs({ celebrations: true, sound: null });
    expect(await withCelebrate((c) => typeof c.sorted)).toBe('function');
  });
});
