// WEB-1, WEB-5, WEB-6 (release gate 0.1.0, fix 16i): a modal overlay is a native <dialog> opened with showModal(), which
// Sheet is. A scan of every source keeps the hand-built version from coming back:
// - no aria-modal: showModal() says it;
// - no scroll lock on the body or the root (overflow there shifts the page sideways; Sheet.css contains scroll instead);
// - no inert toggled by hand around a sheet: the modal makes the page inert;
// - role="dialog" only on the listed non-modal popovers.
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path) && !path.startsWith('/src/test-')),
);

/** Non-modal popovers that keep role="dialog", with why. */
const POPOVERS: Record<string, string> = {
  '/src/ui/CategoryMenu.tsx': "the desktop category menu: a popover beside its field; the phone's is a Sheet",
  '/src/frame/YouMenu.tsx': "the rail's You menu on a desktop: a popover over the rail; the phone's is a Sheet",
};

/** Hand-set inert that isn't about an overlay, with why. */
const OWN_INERT: Record<string, string> = {
  '/src/screens/review/focus/FocusCard.tsx': 'the next card waits behind the current one in the focus stack',
};

function problems(sources: Record<string, string>): string[] {
  const out: string[] = [];
  for (const [path, src] of Object.entries(sources)) {
    if (/aria-modal=|ariaModal|'aria-modal'/.test(src.replace(/\[aria-modal="true"\]/g, ''))) out.push(`${path}: aria-modal by hand`);
    if (/(?:body|documentElement)\.style\.overflow/.test(src)) out.push(`${path}: a scroll lock on the page`);
    if (/\binert=\{/.test(src) && !(path in OWN_INERT)) out.push(`${path}: inert by hand`);
    // An attribute, not a [role="dialog"] selector.
    if (/(?<!\[)role="dialog"/.test(src) && !(path in POPOVERS)) out.push(`${path}: role="dialog" on something that isn't a <dialog>`);
  }
  return out;
}

describe('modal overlays are native dialogs (WEB-1, WEB-5, WEB-6)', () => {
  it('no source rebuilds what showModal() gives', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(300);
    expect(problems(SOURCES)).toEqual([]);
  });

  it('the listed exceptions still exist, so the lists never go stale', () => {
    for (const path of [...Object.keys(POPOVERS)]) expect(SOURCES[path], path).toMatch(/role="dialog"/);
    for (const path of Object.keys(OWN_INERT)) expect(SOURCES[path], path).toMatch(/\binert=\{/);
  });

  it('catches each shape it looks for', () => {
    const planted = {
      '/src/a.tsx': '<div role="dialog" aria-modal="true">',
      '/src/b.tsx': "document.body.style.overflow = 'hidden';",
      '/src/c.tsx': '<section inert={adding || undefined}>',
    };
    expect(problems(planted)).toEqual([
      '/src/a.tsx: aria-modal by hand',
      '/src/a.tsx: role="dialog" on something that isn\'t a <dialog>',
      '/src/b.tsx: a scroll lock on the page',
      '/src/c.tsx: inert by hand',
    ]);
  });
});
