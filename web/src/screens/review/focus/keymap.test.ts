import { describe, expect, it } from 'vitest';
import { chipsFor, keyAct } from './keymap';

describe('the focus chips (P6)', () => {
  it('four: the guess first, then the household’s top categories', () => {
    expect(chipsFor('groceries', ['dining', 'groceries', 'shopping', 'personal', 'transport'])).toEqual(['groceries', 'dining', 'shopping', 'personal']);
    expect(chipsFor(null, ['dining', 'groceries', 'shopping', 'personal', 'transport'])).toEqual(['dining', 'groceries', 'shopping', 'personal']);
    expect(chipsFor('gifts', ['dining'])).toEqual(['gifts', 'dining']);
  });
});

describe('the focus keys (review focus, Keyboard)', () => {
  it('maps Enter, 1–4 (only as many as show), /, S, I, B and N, letters in either case; Z is Review’s', () => {
    expect(keyAct('Enter', 4)).toEqual({ type: 'take' });
    expect(keyAct('1', 4)).toEqual({ type: 'chip', index: 0 });
    expect(keyAct('4', 4)).toEqual({ type: 'chip', index: 3 });
    expect(keyAct('4', 3)).toBeNull();
    expect(keyAct('5', 4)).toBeNull();
    expect(keyAct('/', 4)).toEqual({ type: 'more' });
    for (const k of ['s', 'S']) expect(keyAct(k, 4)).toEqual({ type: 'snooze' });
    expect(keyAct('I', 4)).toEqual({ type: 'ignore' });
    expect(keyAct('b', 4)).toEqual({ type: 'business' });
    expect(keyAct('n', 4)).toEqual({ type: 'note' });
    expect(keyAct('z', 4)).toBeNull();
    expect(keyAct('x', 4)).toBeNull();
  });
});
