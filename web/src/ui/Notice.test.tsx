import { fireEvent, render, screen } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { LiveRegions, useLive } from './Live';
import { Notice } from './Notice';

// Issue #23: a live region added with its text already in it is often not read. An info or warn notice is said through
// the page's polite region, which was there before it; the notice itself is not a live region. An error stays an alert.
describe('Notice', () => {
  it('an info notice is said through the polite region, and is not a live region itself', () => {
    render(<LiveRegions><Notice>Your password is changed.</Notice></LiveRegions>);
    expect(screen.getByTestId('live-said')).toHaveTextContent('Your password is changed.');
    expect(document.querySelector('.notice')).toHaveTextContent('Your password is changed.');
    expect(document.querySelector('.notice')).not.toHaveAttribute('role');
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('a warning is said too, and a changed line is said again; the same line is not', () => {
    function Changing() {
      const [n, setN] = useState(1);
      const [, rerender] = useState(0);
      return (
        <>
          <Notice tone="warn"><p>{`${n} to look into`}</p></Notice>
          <button type="button" onClick={() => setN((x) => x + 1)}>More</button>
          <button type="button" onClick={() => rerender((x) => x + 1)}>Again</button>
        </>
      );
    }
    render(<LiveRegions><Changing /></LiveRegions>);
    const region = screen.getByTestId('live-said');
    expect(region).toHaveTextContent('1 to look into');
    region.textContent = '';
    fireEvent.click(screen.getByRole('button', { name: 'Again' }));
    expect(region).toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole('button', { name: 'More' }));
    expect(region).toHaveTextContent('2 to look into');
  });

  it('says each part laid out on its own as its own phrase, and inline parts with the words around them', () => {
    render(<LiveRegions><Notice><div>Accounts without a type</div><p><strong>1</strong> new account has no type.</p></Notice></LiveRegions>);
    expect(screen.getByTestId('live-said').textContent).toBe('Accounts without a type 1 new account has no type.');
  });

  it('parts inline words before a paragraph from the paragraph', () => {
    render(<LiveRegions><Notice>Saved<p>Next, add a bank.</p></Notice></LiveRegions>);
    expect(screen.getByTestId('live-said').textContent).toBe('Saved Next, add a bank.');
  });

  it('a line break parts the words on either side', () => {
    render(<LiveRegions><Notice>Checking is done<br />Savings is next</Notice></LiveRegions>);
    expect(screen.getByTestId('live-said').textContent).toBe('Checking is done Savings is next');
  });

  it('a render with the same text does not read the parts again', () => {
    function Changing() {
      const [n, setN] = useState(1);
      const [, rerender] = useState(0);
      return (
        <>
          <Notice tone="warn"><p>{`${n} to look into`}</p></Notice>
          <button type="button" onClick={() => setN((x) => x + 1)}>More</button>
          <button type="button" onClick={() => rerender((x) => x + 1)}>Again</button>
        </>
      );
    }
    render(<LiveRegions><Changing /></LiveRegions>);
    const again = screen.getByRole('button', { name: 'Again' });
    const more = screen.getByRole('button', { name: 'More' });
    const style = vi.spyOn(window, 'getComputedStyle');
    try {
      fireEvent.click(again);
      expect(style).not.toHaveBeenCalled();
      fireEvent.click(more);
      expect(style).toHaveBeenCalled();
      expect(screen.getByTestId('live-said')).toHaveTextContent('2 to look into');
    } finally { style.mockRestore(); }
  });

  it('an error stays an alert, and is not said twice', () => {
    render(<LiveRegions><Notice tone="error">That didn’t save.</Notice></LiveRegions>);
    expect(screen.getByRole('alert')).toHaveTextContent('That didn’t save.');
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();
  });

  it('a line said in the same moment as the notice is heard as well (a page change says its name)', () => {
    function PageName() {
      const live = useLive();
      useEffect(() => { live?.say('Home'); }, [live]);
      return null;
    }
    render(<LiveRegions><PageName /><Notice>Joined the book.</Notice></LiveRegions>);
    expect(screen.getByTestId('live-said')).toHaveTextContent('Home Joined the book.');
  });
});
