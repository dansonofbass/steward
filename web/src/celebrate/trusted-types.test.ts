import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('./sound', () => ({ ding: vi.fn(), chime: vi.fn() }));

// Issue #14: the page's CSP requires Trusted Types (require-trusted-types-for 'script'; trusted-types celebrate), so
// the moment's SVG, the one HTML sink in the app, goes in only through the policy named celebrate, made once, which
// takes nothing but the moments' own markup.
type Rules = { createHTML: (markup: string) => string };

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  document.body.innerHTML = '';
});

describe("the moment's markup under Trusted Types", () => {
  it('goes through the one named policy, which refuses any other markup', async () => {
    const made: { name: string; rules: Rules }[] = [];
    const passed: string[] = [];
    vi.stubGlobal('trustedTypes', {
      createPolicy: (name: string, rules: Rules) => {
        made.push({ name, rules });
        return { createHTML: (markup: string) => { passed.push(markup); return rules.createHTML(markup); } };
      },
    });
    const { winMoment } = await import('./celebrate');
    const { MOMENTS } = await import('./moments');
    winMoment({ host: document.body.appendChild(document.createElement('div')), name: 'coins' });
    winMoment({ host: document.body.appendChild(document.createElement('div')), name: 'sprout' });
    expect(made.map((p) => p.name)).toEqual(['celebrate']);
    expect(passed).toEqual([MOMENTS.coins.svg, MOMENTS.sprout.svg]);
    expect(document.querySelectorAll('.cel-moment svg')).toHaveLength(2);
    expect(() => made[0].rules.createHTML('<img src=x onerror=alert(1)>')).toThrow(TypeError);
  });

  it('still shows the moment in a browser without Trusted Types', async () => {
    vi.stubGlobal('trustedTypes', undefined);
    const { winMoment } = await import('./celebrate');
    winMoment({ host: document.body.appendChild(document.createElement('div')), name: 'coins' });
    expect(document.querySelector('.cel-moment svg')).not.toBeNull();
  });
});
