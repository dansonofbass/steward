// WEB-12 (release gate 0.1.0, fix 16i): a custom radio group keeps a native one's keys. The helper's behaviour, and a
// scan of every source: each role="radio" is a roving Tab stop (radioTab) inside a radiogroup that handles the arrows.
import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { radioFocusKeys, radioKeys, radioTab } from './radioKeys';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

function HowOften({ moveOnly = false }: { moveOnly?: boolean }) {
  const [kind, setKind] = useState('yearly');
  return (
    <div role="radiogroup" aria-label="How often" onKeyDown={moveOnly ? radioFocusKeys : radioKeys}>
      {['yearly', 'twice', 'once'].map((k) => (
        <button key={k} type="button" role="radio" aria-checked={kind === k} tabIndex={radioTab(kind === k)} onClick={() => setKind(k)}>{k}</button>
      ))}
    </div>
  );
}
const radio = (name: string) => screen.getByRole('radio', { name });

describe('radio keys (WEB-12)', () => {
  it('the checked radio is the one Tab stop', () => {
    render(<HowOften />);
    expect(radio('yearly')).toHaveAttribute('tabindex', '0');
    expect(radio('twice')).toHaveAttribute('tabindex', '-1');
  });

  it('Right and Down move and choose, wrapping; Left and Up go back; Home and End go to the ends', () => {
    render(<HowOften />);
    radio('yearly').focus();
    fireEvent.keyDown(radio('yearly'), { key: 'ArrowRight' });
    expect(radio('twice')).toHaveFocus();
    expect(radio('twice')).toBeChecked();
    expect(radio('twice')).toHaveAttribute('tabindex', '0');
    fireEvent.keyDown(radio('twice'), { key: 'ArrowDown' });
    fireEvent.keyDown(radio('once'), { key: 'ArrowDown' });
    expect(radio('yearly')).toHaveFocus();
    expect(radio('yearly')).toBeChecked();
    fireEvent.keyDown(radio('yearly'), { key: 'ArrowUp' });
    expect(radio('once')).toBeChecked();
    fireEvent.keyDown(radio('once'), { key: 'Home' });
    expect(radio('yearly')).toBeChecked();
    fireEvent.keyDown(radio('yearly'), { key: 'End' });
    expect(radio('once')).toHaveFocus();
  });

  it('the move-only variant leaves the choice alone', () => {
    render(<HowOften moveOnly />);
    radio('yearly').focus();
    fireEvent.keyDown(radio('yearly'), { key: 'ArrowRight' });
    expect(radio('twice')).toHaveFocus();
    expect(radio('yearly')).toBeChecked();
  });

  it('every role="radio" in the app is a roving Tab stop in a radiogroup that takes the arrows', () => {
    const problems: string[] = [];
    let radios = 0;
    for (const [path, src] of Object.entries(SOURCES)) {
      if (path === '/src/lib/radioKeys.tsx') continue;
      const tags = [...src.matchAll(/<button\b[^>]*role="radio"[^>]*>/g)].map((m) => m[0]);
      radios += tags.length;
      for (const tag of tags) if (!/tabIndex=\{radioTab\(/.test(tag)) problems.push(`${path}: a radio that isn't a roving Tab stop`);
      const groups = [...src.matchAll(/role="radiogroup"[^>]*>/g)].map((m) => m[0]);
      if (tags.length && !groups.some((g) => /onKeyDown=\{radio(?:Focus)?Keys\}/.test(g))) problems.push(`${path}: radios whose group doesn't take the arrows`);
    }
    expect(radios).toBeGreaterThanOrEqual(8);
    expect(problems).toEqual([]);
  });
});
