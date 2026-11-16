import { describe, expect, it } from 'vitest';
import { type Entry, entryOf, entryWithToken, STACK_MAX, stackReducer, topOf } from './undoStack';

const e = (id: string, token: string | null = null): Entry => ({ id, token, kind: 'sort', ids: [Number(id.slice(1))], card: null, view: 'focus' });

describe('the Undo stack (review focus P14)', () => {
  it('pushes, settles a pending token with its rows, and undoes the top or a middle entry', () => {
    let s = stackReducer([], { type: 'push', entry: e('e1') });
    s = stackReducer(s, { type: 'push', entry: e('e2', 't2') });
    expect(entryOf(s, 'e1')?.token).toBeNull();
    s = stackReducer(s, { type: 'settle', id: 'e1', token: 't1', ids: [1, 40, 41] });
    expect(entryOf(s, 'e1')).toMatchObject({ token: 't1', ids: [1, 40, 41] });
    expect(topOf(s)?.id).toBe('e2');
    expect(entryWithToken(s, 't1')?.id).toBe('e1');
    s = stackReducer(s, { type: 'drop', id: 'e1' });           // a middle entry (a toast's or a slim row's Undo)
    expect(s.map((x) => x.id)).toEqual(['e2']);
    s = stackReducer(s, { type: 'drop', id: 'e2' });           // a refusal drops it too
    expect(topOf(s)).toBeNull();
  });

  it('holds at most 50, dropping the oldest, and clears', () => {
    let s = stackReducer([], { type: 'clear' });
    for (let i = 1; i <= STACK_MAX + 2; i++) s = stackReducer(s, { type: 'push', entry: e(`e${i}`, `t${i}`) });
    expect(s).toHaveLength(50);
    expect(s[0].id).toBe('e3');
    expect(stackReducer(s, { type: 'clear' })).toEqual([]);
  });
});
