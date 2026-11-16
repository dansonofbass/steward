import { describe, expect, it } from 'vitest';
import { momentAllowed, type Allowed, type MomentKind } from './momentAllowed';

const ALL: Allowed = { face: true, motion: true, line: true, sound: true, golden: false };
const NONE: Allowed = { face: false, motion: false, line: false, sound: false, golden: false };
const household = { parent: false };
const parent = { parent: true };

describe('where character is allowed (phase 17 spec 3.5), row by row', () => {
  it.each(['import', 'profileDone', 'planDone', 'setAside', 'payday', 'tree', 'gatewayBack'] as MomentKind[])(
    'row 1, the wins: %s gets a face, motion, a line and sound', (kind) => {
      expect(momentAllowed(kind, household)).toEqual(ALL);
    });

  it.each(['sort', 'caughtUp'] as MomentKind[])('row 1, and only Review sorting and All caught up can be golden: %s', (kind) => {
    expect(momentAllowed(kind, household)).toEqual({ ...ALL, golden: true });
  });

  it("row 2, Steward's own hiccups: the oops face and its wince, no joke and no sound", () => {
    expect(momentAllowed('oops', household)).toEqual({ ...NONE, face: true, motion: true });
  });

  it.each(['money', 'payday', 'greeting'] as MomentKind[])('row 3, money news: nothing playful in a red month (%s)', (kind) => {
    expect(momentAllowed(kind, { parent: false, red: true })).toEqual(NONE);
  });

  it('row 3, and money news is never playful even when the month is fine', () => {
    expect(momentAllowed('money', household)).toEqual(NONE);
  });

  it.each(['care', 'flags', 'changes', 'watching'] as MomentKind[])('row 4: nothing in %s', (kind) => {
    expect(momentAllowed(kind, household)).toEqual(NONE);
  });

  it.each(['signIn', 'reset', 'invite', 'backup'] as MomentKind[])('row 5: nothing in %s', (kind) => {
    expect(momentAllowed(kind, household)).toEqual(NONE);
  });

  it('row 6, parent books: warm words only, no face, no motion, no sound, never golden', () => {
    for (const kind of ['caughtUp', 'import', 'gatewayBack', 'greeting'] as MomentKind[]) {
      expect(momentAllowed(kind, parent)).toEqual({ ...NONE, line: true });
    }
    expect(momentAllowed('sort', parent)).toEqual(NONE);                 // the sort cheers are jokes
  });

  it('row 6, parent books: no oops and no tree', () => {
    expect(momentAllowed('oops', parent)).toEqual(NONE);
    expect(momentAllowed('tree', parent)).toEqual(NONE);
  });

  it("the greeting is words only, and a red month doesn't touch the other wins", () => {
    expect(momentAllowed('greeting', household)).toEqual({ ...NONE, line: true });
    expect(momentAllowed('tree', { parent: false, red: true })).toEqual(ALL);
  });
});

describe('guided setup moments (spec 9)', () => {
  it('setupStep is a win with sound; planted is a win without it; neither is golden, and nothing in a parent book', () => {
    expect(momentAllowed('setupStep', household)).toEqual({ face: true, motion: true, line: true, sound: true, golden: false });
    expect(momentAllowed('planted', household)).toEqual({ face: true, motion: true, line: true, sound: false, golden: false });
    for (const k of ['setupStep', 'planted'] as const) expect(momentAllowed(k, parent)).toEqual(NONE);
  });
  it('settings and pairing are nothing', () => {
    for (const k of ['settings', 'pairing'] as const) expect(momentAllowed(k, household)).toEqual(NONE);
  });
});
