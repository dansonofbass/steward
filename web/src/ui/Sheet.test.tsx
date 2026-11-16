import { fireEvent, render, screen } from '@testing-library/react';
import { useRef, useState, type FormEvent } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { readCss, rule, uncomment } from '../test-css';
import { closeRequest, forcedCloseRequest } from '../test-dialog';
import { Sheet, useSheetSaved } from './Sheet';

afterEach(() => vi.restoreAllMocks());

const dialogOf = (name: string) => screen.getByRole('dialog', { name }) as HTMLDialogElement;
/** A tap on the backdrop: pressed and released outside the sheet's box (jsdom's box is 0×0 at the origin). */
function tapOutside(d: HTMLElement) {
  fireEvent.pointerDown(d, { clientX: 40, clientY: 40 });
  fireEvent.pointerUp(d, { clientX: 40, clientY: 40 });
}

describe('Sheet is a modal <dialog> (WEB-1)', () => {
  it('opens as a modal, named by its title, with focus on the title; Escape closes it', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Pick one"><button type="button">Groceries</button></Sheet>);
    const d = dialogOf('Pick one');
    expect(d.tagName).toBe('DIALOG');
    expect(d.open).toBe(true);
    expect(d).not.toHaveAttribute('aria-modal');      // showModal() says it; no role or aria-modal by hand
    expect(screen.getByRole('heading', { name: 'Pick one' })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('button', { name: 'Groceries' }), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Android's back gesture (a close request) closes the sheet, and nothing else hears it", () => {
    const onClose = vi.fn();
    const popped = vi.fn();
    window.addEventListener('popstate', popped);
    render(<Sheet open onClose={onClose} title="Ask"><textarea aria-label="Question" /></Sheet>);
    closeRequest();
    expect(onClose).toHaveBeenCalledOnce();
    expect(popped).not.toHaveBeenCalled();
    window.removeEventListener('popstate', popped);
  });

  it('leaves the body alone: no scroll lock by overflow (WEB-6)', () => {
    document.body.style.overflow = 'auto';
    const { rerender } = render(<Sheet open onClose={() => {}} title="A">x</Sheet>);
    expect(document.body.style.overflow).toBe('auto');
    rerender(<Sheet open={false} onClose={() => {}} title="A">x</Sheet>);
    expect(document.body.style.overflow).toBe('auto');
  });

  it('stops scroll chaining with overscroll-behavior, and is measured in dvh, not vh (WEB-6)', () => {
    const css = uncomment(readCss('ui/Sheet.css'));
    expect(rule(css, '.sheet:modal')).toContain('overscroll-behavior: contain');
    expect(rule(css, '.sheet::backdrop')).toMatch(/overflow: hidden; overscroll-behavior: contain/);
    expect(rule(css, '.sheet')).toContain('max-height: 85dvh');
    expect(css).not.toMatch(/\d+vh\b/);
    expect(css).not.toMatch(/body|html/);
  });

  it('renders into the page body, so no ancestor can hide it', () => {
    const { container } = render(<header style={{ position: 'sticky', zIndex: 30 }}><Sheet open onClose={() => {}} title="You">x</Sheet></header>);
    expect(dialogOf('You').parentElement).toBe(document.body);
    expect(container.querySelector('header')).toBeEmptyDOMElement();
  });

  it('gives focus back to what had it when it closes', () => {
    const { rerender } = render(<><button type="button">Open</button><Sheet open={false} onClose={() => {}} title="A">x</Sheet></>);
    const opener = screen.getByRole('button', { name: 'Open' });
    opener.focus();
    rerender(<><button type="button">Open</button><Sheet open onClose={() => {}} title="A">x</Sheet></>);
    expect(screen.getByRole('heading', { name: 'A' })).toHaveFocus();
    rerender(<><button type="button">Open</button><Sheet open={false} onClose={() => {}} title="A">x</Sheet></>);
    expect(opener).toHaveFocus();
  });

  it('gives each sheet its own title id', () => {
    render(<><Sheet open onClose={() => {}} title="One">a</Sheet><Sheet open onClose={() => {}} title="Two">b</Sheet></>);
    expect(dialogOf('One').getAttribute('aria-labelledby')).not.toBe(dialogOf('Two').getAttribute('aria-labelledby'));
  });

  it('the /design preview is no dialog at all', () => {
    render(<Sheet open onClose={() => {}} title="Pick a category" inline>a</Sheet>);
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByRole('region', { name: 'Pick a category' })).toBeInTheDocument();
  });
});

describe('Sheet focus', () => {
  it('focuses focusRef instead of its heading when given one', () => {
    function WithInput() {
      const r = useRef<HTMLInputElement>(null);
      return <Sheet open onClose={() => {}} title="T" focusRef={r} className="x-sheet"><input ref={r} aria-label="Find" /></Sheet>;
    }
    render(<WithInput />);
    expect(screen.getByLabelText('Find')).toHaveFocus();
    expect(dialogOf('T')).toHaveClass('sheet', 'x-sheet');
  });
  it('only the top sheet answers Escape: one closes the newer, the next the older (Ask about this P20)', () => {
    const closeTxn = vi.fn();
    const closeAsk = vi.fn();
    const both = (ask: boolean, onTxn: () => void = closeTxn) => (
      <><Sheet open onClose={onTxn} title="Mobile One">a</Sheet><Sheet open={ask} onClose={closeAsk} title="Ask">b</Sheet></>
    );
    const { rerender } = render(both(false));
    rerender(both(true));
    rerender(both(true, () => closeTxn()));              // a re-render of the lower sheet never moves it on top
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(closeAsk).toHaveBeenCalledOnce();
    expect(closeTxn).not.toHaveBeenCalled();
    rerender(both(false));
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(closeTxn).toHaveBeenCalledOnce();
  });
  it('onEscape goes first, and true keeps the sheet open', () => {
    const onClose = vi.fn();
    let tip = true;
    render(<Sheet open onClose={onClose} title="Ask" onEscape={() => { const had = tip; tip = false; return had; }}>x</Sheet>);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
    expect(dialogOf('Ask').open).toBe(true);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
  });
  it('a key handler that takes Escape (preventDefault) keeps it from closing the sheet', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Category"><input aria-label="Find" onKeyDown={(e) => { if (e.key === 'Escape') e.preventDefault(); }} /></Sheet>);
    fireEvent.keyDown(screen.getByLabelText('Find'), { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
  it('returnTo says where focus goes when it closes', () => {
    const view = (open: boolean) => <><button type="button">Opener</button><h1 tabIndex={-1}>Page</h1>
      <Sheet open={open} onClose={() => {}} title="Ask" returnTo={() => screen.getByRole('heading', { name: 'Page' })}>x</Sheet></>;
    const { rerender } = render(view(false));
    screen.getByRole('button', { name: 'Opener' }).focus();
    rerender(view(true));
    rerender(view(false));
    expect(screen.getByRole('heading', { name: 'Page' })).toHaveFocus();
  });
  it('a sheet that unmounts while open closes its dialog and gives focus back', () => {
    const view = (shown: boolean) => <><button type="button">Opener</button>{shown && <Sheet open onClose={() => {}} title="Gone">x</Sheet>}</>;
    const { rerender } = render(view(false));
    const opener = screen.getByRole('button', { name: 'Opener' });
    opener.focus();
    rerender(view(true));
    rerender(view(false));
    expect(opener).toHaveFocus();
    expect(document.querySelector('dialog')).toBeNull();
  });
  it("focus falls back to the title when focusRef's element can't take it (a disabled box)", () => {
    function Host() {
      const box = useRef<HTMLTextAreaElement>(null);
      return <Sheet open onClose={() => {}} title="Ask" focusRef={box}><textarea ref={box} disabled aria-label="Your question" /></Sheet>;
    }
    render(<Host />);
    expect(screen.getByRole('heading', { name: 'Ask' })).toHaveFocus();
  });
});

describe('a tap outside, and typed text (WEB-1)', () => {
  it('a tap on the backdrop closes a sheet with nothing typed in it', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Books"><button type="button">Ours</button></Sheet>);
    tapOutside(dialogOf('Books'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('a press inside that ends outside (a text selection dragged out) does not close it', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Books"><p>Words</p></Sheet>);
    const d = dialogOf('Books');
    fireEvent.pointerDown(screen.getByText('Words'), { clientX: 0, clientY: 0 });
    fireEvent.pointerUp(d, { clientX: 40, clientY: 40 });
    expect(onClose).not.toHaveBeenCalled();
  });

  function TripForm({ onClose }: { onClose: () => void }) {
    const [name, setName] = useState('Lake trip');
    return (
      <Sheet open onClose={onClose} title="Change the trip">
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Find<input type="text" role="combobox" aria-expanded="false" defaultValue="" /></label>
        <label>Link<input readOnly value="https://example.test/x" /></label>
      </Sheet>
    );
  }
  const typeName = (v: string) => {
    const box = screen.getByLabelText('Name');
    box.focus();
    fireEvent.change(box, { target: { value: v } });
  };

  it('with typed text, a tap outside asks first, and Keep editing keeps the text and goes back to the box', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    tapOutside(dialogOf('Change the trip'));
    expect(onClose).not.toHaveBeenCalled();
    const keep = screen.getByRole('button', { name: 'Keep editing' });
    expect(keep).toHaveFocus();
    expect(keep).toHaveAccessibleDescription('Discard what you typed?');
    fireEvent.click(keep);
    expect(screen.queryByRole('button', { name: 'Keep editing' })).toBeNull();
    expect(screen.getByLabelText('Name')).toHaveValue('Lake trip, June');
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('Discard closes it', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('Escape and the back gesture ask too; asked again, the sheet stays open', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    closeRequest();
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
    closeRequest();
    expect(screen.queryByRole('button', { name: 'Keep editing' })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialogOf('Change the trip').open).toBe(true);
  });

  it('a box put back as it was, a search box and a read-only box hold nothing to lose', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake');
    typeName('Lake trip');
    const find = screen.getByLabelText('Find');
    find.focus();
    fireEvent.change(find, { target: { value: 'groc' } });
    screen.getByLabelText('Link').focus();
    tapOutside(dialogOf('Change the trip'));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('a sheet whose caller keeps the draft (Ask) closes without asking', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Ask" keepsDraft><textarea aria-label="Question" /></Sheet>);
    const box = screen.getByLabelText('Question');
    box.focus();
    fireEvent.change(box, { target: { value: 'Half a thought' } });
    closeRequest();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("Chrome's second Escape or back press (a cancel that can't be prevented) keeps the text and the question (16i review I-1)", () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    closeRequest();                                  // the first: cancelable, so the sheet asks
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
    forcedCloseRequest();                            // the second: cancel arrives with cancelable false, then close
    expect(onClose).not.toHaveBeenCalled();
    expect(dialogOf('Change the trip').open).toBe(true);
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
    expect(screen.getByLabelText('Name')).toHaveValue('Lake trip, June');
  });

  it('a forced close with typed text and no question yet opens the sheet again, asking', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    forcedCloseRequest();
    expect(onClose).not.toHaveBeenCalled();
    expect(dialogOf('Change the trip').open).toBe(true);
    expect(screen.getByRole('button', { name: 'Keep editing' })).toHaveFocus();
  });

  it('a third forced close in a row lets the person out, as the browser intends (no trap)', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    closeRequest();
    forcedCloseRequest();
    forcedCloseRequest();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('a tap after the rescue counts as activation: the next forced close is caught again', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    forcedCloseRequest();
    fireEvent.pointerDown(screen.getByLabelText('Name'), { clientX: 0, clientY: 0 });
    forcedCloseRequest();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('Esc, Esc (rescued), Keep editing by keyboard, Esc, Esc keeps the text (16i re-review R-2)', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    typeName('Lake trip, June');
    closeRequest();                 // cancelable: asks
    forcedCloseRequest();           // forced: rescued, still asking
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));   // Enter on the button: a click, no pointerdown
    closeRequest();                 // cancelable again: the browser saw an activation, so the rescue is renewed
    forcedCloseRequest();           // forced: rescued again
    expect(onClose).not.toHaveBeenCalled();
    expect(dialogOf('Change the trip').open).toBe(true);
    expect(screen.getByLabelText('Name')).toHaveValue('Lake trip, June');
  });

  it('a forced close with nothing typed closes the sheet', () => {
    const onClose = vi.fn();
    render(<TripForm onClose={onClose} />);
    forcedCloseRequest();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('a date typed into a box counts as typed text', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="Balance"><label>As of<input type="date" defaultValue="" /></label></Sheet>);
    const box = screen.getByLabelText('As of');
    box.focus();
    fireEvent.change(box, { target: { value: '2026-11-10' } });
    tapOutside(dialogOf('Balance'));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Keep editing' })).toBeInTheDocument();
  });

  it('a parent that keeps it open after the browser closed it gets it shown again', () => {
    render(<Sheet open onClose={() => {}} title="Stays">x</Sheet>);
    forcedCloseRequest();
    expect(dialogOf('Stays').open).toBe(true);
  });

  it('each opening starts clean: text typed last time asks nothing', () => {
    const onClose = vi.fn();
    function Toggle({ open }: { open: boolean }) {
      return <Sheet open={open} onClose={onClose} title="A note"><input aria-label="Note" defaultValue="" /></Sheet>;
    }
    const { rerender } = render(<Toggle open />);
    const box = screen.getByLabelText('Note');
    box.focus();
    fireEvent.change(box, { target: { value: 'Dinner' } });
    rerender(<Toggle open={false} />);
    rerender(<Toggle open />);
    tapOutside(dialogOf('A note'));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe('a form that saves in place (16i review I-2)', () => {
  /** Like TxnDetail and NoteForm: Save keeps the sheet open and the box shows the saved value. */
  function SavesInPlace({ refuse = false }: { onClose?: () => void; refuse?: boolean }) {
    const [saved, setSaved] = useState('PayPal');
    const [text, setText] = useState('PayPal');
    const [error, setError] = useState('');
    const form = useRef<HTMLFormElement>(null);
    const markSaved = useSheetSaved(form);
    const save = (e: FormEvent) => {
      e.preventDefault();
      if (refuse) { setError('Not saved.'); return; }
      setSaved(text.trim());
      setText(text.trim());
      markSaved();
    };
    return (
      <form ref={form} onSubmit={save}>
        <label>Merchant <input value={text} onChange={(e) => setText(e.target.value)} /></label>
        <button type="submit">Save</button>
        <p>Saved: {saved}</p>
        {error && <p>{error}</p>}
      </form>
    );
  }
  const typeMerchant = (v: string) => {
    const box = screen.getByLabelText('Merchant');
    box.focus();
    fireEvent.change(box, { target: { value: v } });
  };

  it('after a save that keeps the sheet open, Close asks nothing', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="PayPal"><SavesInPlace onClose={onClose} /></Sheet>);
    typeMerchant('Disney+ ');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Saved: Disney+')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.queryByText('Discard what you typed?')).toBeNull();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it('typing again after the save asks again', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="PayPal"><SavesInPlace onClose={onClose} /></Sheet>);
    typeMerchant('Disney+');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    typeMerchant('Disney+ Hulu');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Discard what you typed?')).toBeInTheDocument();
  });

  it('a failed save still asks', () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="PayPal"><SavesInPlace onClose={onClose} refuse /></Sheet>);
    typeMerchant('Disney+');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Not saved.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Discard what you typed?')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it('outside a sheet (the desktop pane) the hook does nothing', () => {
    render(<SavesInPlace onClose={() => {}} />);
    typeMerchant('Disney+');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Saved: Disney+')).toBeInTheDocument();
  });

  /** A transaction's sheet: the note form and the detail form, each with its own Save (16i re-review R-1). */
  function NoteBox() {
    const [note, setNote] = useState('');
    return <form><label>Note <textarea value={note} onChange={(e) => setNote(e.target.value)} /></label></form>;
  }

  it("saving one form doesn't take another form's unsaved text as saved (16i re-review R-1)", () => {
    const onClose = vi.fn();
    render(<Sheet open onClose={onClose} title="PayPal"><NoteBox /><SavesInPlace /></Sheet>);
    const note = screen.getByLabelText('Note');
    note.focus();
    fireEvent.change(note, { target: { value: 'Ask Sam about this' } });   // typed, never saved
    typeMerchant('Disney+');
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    expect(screen.getByText('Saved: Disney+')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(screen.getByText('Discard what you typed?')).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }));
    fireEvent.change(screen.getByLabelText('Note'), { target: { value: '' } });   // the note put back: only the saved form is left
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
