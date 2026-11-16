// The Ask page's CSS against the design pass (docs/design/chat, web/mockups/chat.css): tokens only, 44 px touch
// targets, plum for what Steward replaced, amber for what the gateway's check removed.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

// Read as text: the test runner's CSS plugin returns an empty string for imported stylesheets.
const read = (rel: string) => readFileSync(new URL(rel, import.meta.url), 'utf8');
const button = read('../../ui/Button.css');
const sky = read('../../styles/sky.css');
const tokens = read('../../styles/tokens.css');
const ask = read('./ask.css');

const rule = (css: string, selector: string) => {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const hits = [...css.matchAll(new RegExp(`(?:^|\\})\\s*${esc}\\s*\\{([^}]*)\\}`, 'gm'))].map((m) => m[1]);
  return hits.join(' ');
};
const stripComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '');

describe('ask.css', () => {
  it('a phone page clears the tab bar and the top bar; a laptop page only fills the screen', () => {
    const body = stripComments(ask);
    expect(rule(body, '.askp')).toContain('min-height: calc(100dvh - 72px - 56px)');
    expect(body).toMatch(/@media \(min-width: 900px\) \{ \.askp \{ min-height: 100dvh; \} \}/);
  });

  it('keeps the tab bar on Ask and puts Ask in the main column (decisions 2, 3)', () => {
    expect(ask).not.toMatch(/\.app--ask/);
    expect(ask).not.toMatch(/\.ask-host/);
    expect(ask).not.toMatch(/\.behind/);
    expect(rule(ask, '.askp')).toContain('max-width: 760px');
  });

  it('uses design tokens only: every colour and every var() is defined', () => {
    const body = stripComments(ask);
    expect(body).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(body).not.toMatch(/\b(?:rgb|rgba|hsl|hsla)\(/i);
    const defined = new Set([...(tokens + sky).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
    const used = [...body.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]);
    expect(used.filter((v) => !defined.has(v))).toEqual([]);
  });

  it('chips: plum with a 20 px shield for Steward, amber for the gateway, each with its own icon colour', () => {
    expect(rule(ask, '.tok')).toContain('var(--accent) 16%');
    expect(rule(ask, '.tok svg')).toMatch(/width: 20px; height: 20px; color: var\(--accent-text\)/);
    expect(rule(ask, '.tok--model')).toContain('var(--warn) 22%');
    expect(rule(ask, '.tok--model svg')).toContain('color: var(--warn)');
  });

  it('a chip is a 44 px touch target even though it sits inside a line of text', () => {
    expect(rule(ask, '.tok')).toContain('position: relative');
    const area = rule(ask, '.tok::after');
    expect(area).toContain("content: ''");
    expect(area).toMatch(/inset: -12px/);   // the chip is about 24 px tall, so 12 px each way reaches 48 px
  });

  it('the composer box, the buttons and every standalone tap target are at least 44 px', () => {
    expect(rule(ask, '.composer textarea')).toMatch(/min-height: (7\d|[89]\d|\d{3})px/);
    expect(rule(button, '.btn')).toContain('min-height: 44px');
    for (const sel of ['.amsg__foot .link', '.saw__row .link', '.conv__title', '.del-btn']) {
      expect(rule(ask, sel), sel).toContain('min-height: 44px');
    }
    expect(rule(ask, '.example')).toContain('min-height: 52px');
  });

  it('the Will send card, the store-names card and the composer match the mockup', () => {
    expect(rule(ask, '.willsend')).toContain('inset 0 0 0 1px var(--line)');
    expect(rule(ask, '.willsend__text')).toContain('line-height: 1.7');
    expect(rule(ask, '.approve')).toContain('border-left: 4px solid var(--accent-text)');
    expect(rule(ask, '.approve--viewer')).toContain('border-left-color: var(--line)');
    expect(rule(ask, '.name')).toContain('border-radius: var(--r-pill)');
    expect(rule(ask, '.confirm__acts .btn, .approve__acts .btn')).toContain('flex: 1 1 auto');
    expect(rule(ask, '.composer__row')).toContain('justify-content: space-between');
  });

  it('icons are at least 20 px', () => {
    const sizes = [...stripComments(ask).matchAll(/(?:^|[\s;{])(?:width|height): (\d+)px/g)].map((m) => Number(m[1]));
    expect(sizes.filter((n) => n > 1 && n < 20)).toEqual([]);
  });

  it('Ask about this: the tip fades with the state duration (0 ms under reduced motion), and the chip and ✕ are 44 px', () => {
    expect(rule(ask, '.ask-tour')).toMatch(/animation: ask-tour-in var\(--dur-state\)/);
    expect(tokens).toMatch(/prefers-reduced-motion: reduce\)\s*\{\s*:root \{[^}]*--dur-state: 0ms/);
    expect(rule(ask, '.ask-chip')).toMatch(/min-height: 44px/);
    expect(rule(ask, '.ask-chip__x')).toMatch(/height: 44px/);
    expect(rule(ask, '.willsend.is-tour')).toMatch(/outline: 2px solid var\(--warn\)/);
  });
});
