import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { COPY_NOTE_MS, CopyButton } from './CopyButton';

// The copy-button pattern (WEB-21): the note is the live region, in the page and empty before the press, outside the
// button, and it says both outcomes.
const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);
const press = async () => { await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Copy' })); }); };

describe('CopyButton says what happened (WEB-21)', () => {
  it('the note is an empty status beside the button before the press, and says Copied after', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(async () => {}) } });
    render(<CopyButton text="steward-gateway mcp-grant add" label="Copy" />);
    const note = screen.getByRole('status');
    expect(note).toBeEmptyDOMElement();
    expect(screen.getByRole('button', { name: 'Copy' })).not.toContainElement(note);
    await press();
    expect(note).toHaveTextContent('Copied');
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument();   // the button's word stays
  });

  it('a refused copy says so, runs the fallback, and the note empties after two seconds', async () => {
    useFakeTimers();
    const onFail = vi.fn();
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(async () => { throw new Error('denied'); }) } });
    render(<CopyButton text="x" label="Copy" onFail={onFail} />);
    await press();
    expect(onFail).toHaveBeenCalledOnce();
    expect(screen.getByRole('status')).toHaveTextContent("Couldn't copy. Select the text to copy it.");
    act(() => { vi.advanceTimersByTime(COPY_NOTE_MS); });
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
  });

  it('a second press says it again: the note changes even when the words are the same', async () => {
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText: vi.fn(async () => {}) } });
    render(<CopyButton text="x" label="Copy" />);
    await press();
    const first = screen.getByRole('status').textContent;
    await press();
    expect(screen.getByRole('status').textContent).not.toBe(first);
    expect(screen.getByRole('status').textContent!.trim()).toBe('Copied');
  });

  it('no source writes to the clipboard except CopyButton', () => {
    const writers = Object.entries(SOURCES).filter(([, src]) => /clipboard\.writeText/.test(src)).map(([path]) => path);
    expect(writers).toEqual(['/src/ui/CopyButton.tsx']);
  });
});
