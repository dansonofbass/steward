import { afterEach, describe, expect, it } from 'vitest';
import { ignoreKey } from './keys';

afterEach(() => { document.body.innerHTML = ''; });
const at = (html: string, sel: string) => { document.body.innerHTML = html; return document.querySelector(sel)!; };
const key = (target: Element | null, init: Partial<KeyboardEvent> = {}) =>
  ({ key: 's', target, ctrlKey: false, metaKey: false, altKey: false, repeat: false, defaultPrevented: false, ...init }) as KeyboardEvent;
const idle = { busy: false, menuOpen: false };

describe('ignoreKey (review focus, Keyboard)', () => {
  it('lets a key on the page through', () => {
    expect(ignoreKey(key(document.body), idle)).toBe(false);
  });
  it('ignores keys typed into an input, a textarea, a select or contenteditable, or inside one', () => {
    expect(ignoreKey(key(at('<input>', 'input')), idle)).toBe(true);
    expect(ignoreKey(key(at('<textarea></textarea>', 'textarea')), idle)).toBe(true);
    expect(ignoreKey(key(at('<select><option>a</option></select>', 'select')), idle)).toBe(true);
    expect(ignoreKey(key(at('<div contenteditable="true"><b>x</b></div>', 'b')), idle)).toBe(true);
    expect(ignoreKey(key(at('<div contenteditable="false"><b>x</b></div>', 'b')), idle)).toBe(false);
  });
  it('ignores keys while a dialog or a menu is open, or an action is in flight', () => {
    expect(ignoreKey(key(at('<div role="dialog"><p>x</p></div>', 'p')), idle)).toBe(true);
    document.body.innerHTML = '<div aria-modal="true"></div><p>x</p>';
    expect(ignoreKey(key(document.querySelector('p')), idle)).toBe(true);
    document.body.innerHTML = '';
    expect(ignoreKey(key(document.body), { busy: false, menuOpen: true })).toBe(true);
    expect(ignoreKey(key(document.body), { busy: true, menuOpen: false })).toBe(true);
  });
  it('lets keys through while a dialog that is a closed popover waits in the page, as the You menu does (issue #27)', () => {
    document.body.innerHTML = '<div role="dialog" popover="auto" aria-label="You"></div><p>x</p>';
    expect(ignoreKey(key(document.querySelector('p')), idle)).toBe(false);
  });
  it('ignores modifiers, a held key and a key already handled', () => {
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { repeat: true }, { defaultPrevented: true }]) {
      expect(ignoreKey(key(document.body, init), idle)).toBe(true);
    }
  });
  it('leaves Enter and Space on a button, a link or a menu item to that element', () => {
    expect(ignoreKey(key(at('<button>x</button>', 'button'), { key: 'Enter' }), idle)).toBe(true);
    expect(ignoreKey(key(at('<a href="#">x</a>', 'a'), { key: ' ' }), idle)).toBe(true);
    expect(ignoreKey(key(at('<div role="menuitemcheckbox">x</div>', 'div'), { key: 'Enter' }), idle)).toBe(true);
    expect(ignoreKey(key(at('<button>x</button>', 'button'), { key: 's' }), idle)).toBe(false);
  });
});
