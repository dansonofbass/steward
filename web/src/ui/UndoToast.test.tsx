import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFakeTimers } from '../test-clock';
import { LiveRegions, useLive } from './Live';
import { Sheet } from './Sheet';
import { UndoToast } from './UndoToast';

afterEach(() => vi.useRealTimers());

describe('UndoToast', () => {
  it('names what left, offers Undo and goes after 10 seconds', () => {
    useFakeTimers();
    const onUndo = vi.fn();
    const onClose = vi.fn();
    render(<UndoToast text="Removed Ava" onUndo={onUndo} onClose={onClose} />);
    expect(screen.getByRole('status')).toHaveTextContent('Removed Ava · Undo');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(onUndo).toHaveBeenCalled();
    // The dot before Undo is Undo's, so it wraps with it (#22).
    const undo = screen.getByRole('button', { name: 'Undo' }).parentElement!;
    expect(undo).toHaveClass('undo-toast__undo');
    expect(undo.textContent).toBe(' · Undo');
    act(() => { vi.advanceTimersByTime(10_000); });
    expect(onClose).toHaveBeenCalled();
  });

  it('a new onClose mid-countdown does not re-arm the timer', () => {
    useFakeTimers();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<UndoToast text="x" onUndo={() => {}} onClose={first} />);
    act(() => { vi.advanceTimersByTime(6_000); });
    rerender(<UndoToast text="x" onUndo={() => {}} onClose={second} />);
    act(() => { vi.advanceTimersByTime(4_000); });
    expect(second).toHaveBeenCalledTimes(1);
    expect(first).not.toHaveBeenCalled();
  });

  it('holds while focus is in it, then runs out what was left', () => {
    useFakeTimers();
    const onClose = vi.fn();
    render(<UndoToast text="x" onUndo={() => {}} onClose={onClose} />);
    act(() => { vi.advanceTimersByTime(4_000); });
    const undo = screen.getByRole('button', { name: 'Undo' });
    act(() => { undo.focus(); });
    act(() => { vi.advanceTimersByTime(20_000); });
    expect(onClose).not.toHaveBeenCalled();
    act(() => { undo.blur(); });
    act(() => { vi.advanceTimersByTime(5_999); });
    expect(onClose).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('carries a stamp tag and a link; with no onUndo it only says something', () => {
    render(<UndoToast tag="SORTED" text="GREENLEAF MARKET → Groceries" link={<a href="/x">Settle</a>} onClose={() => {}} />);
    expect(screen.getByRole('status')).toHaveTextContent('SORTED · GREENLEAF MARKET → Groceries Settle');
    expect(screen.getByText('SORTED')).toHaveClass('stamp');
    expect(screen.queryByRole('button', { name: 'Undo' })).toBeNull();
  });

  it('a screen reader hears the parts apart: the hidden dots keep their spaces (THO-10)', () => {
    render(<UndoToast tag="SORTED" text="Cafe → Groceries" onUndo={() => {}} onClose={() => {}} />);
    // What a screen reader reads: the text, without what is aria-hidden.
    const spoken = (el: Node): string => (el.nodeType === Node.TEXT_NODE ? el.textContent ?? ''
      : (el as Element).getAttribute?.('aria-hidden') === 'true' ? '' : [...el.childNodes].map(spoken).join(''));
    expect(spoken(screen.getByRole('status')).replace(/\s+/g, ' ').trim()).toBe('SORTED Cafe → Groceries Undo');
  });

  it('a cheer is its own row after Undo, and Undo stays whole (phase 17 spec 3.7)', () => {
    render(<UndoToast text="SORTED · Cafe" cheer="Nicely done." onUndo={() => {}} onClose={() => {}} />);
    expect(screen.getByTestId('toast-cheer')).toHaveTextContent('Nicely done.');
    expect(screen.getByRole('status')).toHaveTextContent('SORTED · Cafe · UndoNicely done.');
  });

  it('a cheer whose own row would wrap is skipped, never cut, and the receipt and Undo stay', () => {
    // jsdom lays nothing out: make the cheer row report more content than it shows.
    const sw = vi.spyOn(Element.prototype, 'scrollWidth', 'get').mockReturnValue(400);
    const cw = vi.spyOn(Element.prototype, 'clientWidth', 'get').mockReturnValue(300);
    render(<UndoToast text="Sorted Northwind Regional Medical Center Pharmacy" cheer="Sorted with style." onUndo={() => {}} onClose={() => {}} />);
    expect(screen.queryByTestId('toast-cheer')).toBeNull();
    expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Sorted Northwind Regional Medical Center Pharmacy · Undo');
    sw.mockRestore();
    cw.mockRestore();
  });
});

describe('the toast arrives in a live region that was already there (WEB-7)', () => {
  function Page({ shown }: { shown: boolean }) {
    return <LiveRegions><p>Review</p>{shown && <UndoToast text="Cafe → Groceries" onUndo={() => {}} onClose={() => {}} />}</LiveRegions>;
  }

  it('the page has its polite region before any toast, and the toast is added to it', () => {
    const { rerender } = render(<Page shown={false} />);
    const region = screen.getByTestId('live-toasts');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toBeEmptyDOMElement();
    rerender(<Page shown />);
    expect(screen.getByTestId('live-toasts')).toBe(region);          // the same node: only its contents changed
    expect(region).toContainElement(screen.getByTestId('undo-toast'));
    expect(region).toHaveTextContent('Cafe → Groceries · Undo');
    // The region carries the announcement: no live region nested inside it (16i review Minor 8).
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByTestId('undo-toast')).not.toHaveAttribute('aria-live');
    rerender(<Page shown={false} />);
    expect(region).toBeEmptyDOMElement();
  });

  it("inside an open sheet it goes to the sheet's own region, since the page behind a modal is inert", () => {
    render(<LiveRegions><Sheet open onClose={() => {}} title="Mobile One"><UndoToast text="Saved" onUndo={() => {}} onClose={() => {}} /></Sheet></LiveRegions>);
    const sheet = screen.getByRole('dialog', { name: 'Mobile One' });
    expect(within(sheet).getByTestId('live-toasts')).toContainElement(screen.getByTestId('undo-toast'));
    expect(within(sheet).getByTestId('live-toasts')).toHaveTextContent('Saved · Undo');
  });
});

describe('say: a line through the polite region (WEB-7)', () => {
  function Sayer({ text }: { text: string }) {
    const live = useLive();
    return <button type="button" onClick={() => live?.say(text)}>Say</button>;
  }
  it('fills a polite region that was empty, and the same line twice still changes it', () => {
    render(<LiveRegions><Sayer text="Spending" /></LiveRegions>);
    const region = screen.getByTestId('live-said');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole('button', { name: 'Say' }));
    expect(region.textContent).toBe('Spending');
    fireEvent.click(screen.getByRole('button', { name: 'Say' }));
    expect(region.textContent).toBe('Spending ');
  });
});
