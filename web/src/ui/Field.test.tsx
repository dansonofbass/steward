import { act, fireEvent, render, screen } from '@testing-library/react';
import { useState, type FormEvent } from 'react';
import { describe, expect, it } from 'vitest';
import { Field } from './Field';
import { LiveRegions } from './Live';

describe('Field ties its error to its control (WEB-4)', () => {
  it('the error is in the control’s description, and the control is invalid', () => {
    const { rerender } = render(<Field label="Amount" hint="Dollars a month"><input /></Field>);
    const box = screen.getByLabelText('Amount');
    expect(box).not.toHaveAttribute('aria-invalid');
    expect(box).toHaveAccessibleDescription('Dollars a month');
    rerender(<Field label="Amount" hint="Dollars a month" error="Type an amount."><input /></Field>);
    expect(box).toHaveAttribute('aria-invalid', 'true');
    expect(box).toHaveAccessibleDescription('Dollars a month Type an amount.');
    const errId = box.getAttribute('aria-describedby')!.split(' ')[1];
    expect(document.getElementById(errId)).toHaveTextContent('Type an amount.');
  });
});

/** A set-aside's form: name and amount, checked on Save, then the server's answer. */
function SetAside({ server }: { server?: () => Promise<string | null> }) {
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [errors, setErrors] = useState<{ name?: string; amount?: string }>({});
  async function save(e: FormEvent) {
    e.preventDefault();
    const next = { name: name ? undefined : 'Name it.', amount: amount ? undefined : 'Type an amount.' };
    if (next.name || next.amount) { setErrors(next); return; }
    setErrors({});
    const refused = await server?.();
    if (refused) setErrors({ amount: refused });
  }
  return (
    <form onSubmit={save}>
      <Field label="Name" error={errors.name}><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Amount" error={errors.amount}><input value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <button type="submit">Save</button>
    </form>
  );
}
const save = () => {
  const button = screen.getByRole('button', { name: 'Save' });
  button.focus();
  fireEvent.submit(button.closest('form')!);
};

describe('after a failed submit, focus goes to the first invalid field (WEB-4)', () => {
  it('a check on Save: focus leaves Save for the first field in error', () => {
    render(<SetAside />);
    save();
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it('only the first: with the name typed, focus goes to the amount', () => {
    render(<SetAside />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Car tags' } });
    save();
    expect(screen.getByLabelText('Amount')).toHaveFocus();
  });

  it('the same error again on a second Save still moves focus', async () => {
    render(<SetAside />);
    save();
    save();
    await act(async () => {});                                     // the watcher checks once React has rendered
    expect(screen.getByLabelText('Name')).toHaveFocus();
  });

  it("the server's answer: focus moves when it arrives", async () => {
    let answer: (v: string) => void = () => {};
    render(<SetAside server={() => new Promise<string>((r) => { answer = r; })} />);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Car tags' } });
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '300' } });
    save();
    expect(screen.getByRole('button', { name: 'Save' })).toHaveFocus();
    await act(async () => { answer('That amount is over the limit.'); });
    expect(screen.getByLabelText('Amount')).toHaveFocus();
    expect(screen.getByLabelText('Amount')).toHaveAccessibleDescription('That amount is over the limit.');
  });

  it('typing after Save: a late answer no longer takes focus, it is said instead', async () => {
    let answer: (v: string) => void = () => {};
    render(<LiveRegions><SetAside server={() => new Promise<string>((r) => { answer = r; })} /></LiveRegions>);
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Car' } });
    fireEvent.change(screen.getByLabelText('Amount'), { target: { value: '300' } });
    save();
    const name = screen.getByLabelText('Name');
    name.focus();
    fireEvent.input(name, { target: { value: 'Car tags' } });
    await act(async () => { answer('That amount is over the limit.'); });
    expect(name).toHaveFocus();
    expect(screen.getByTestId('live-said')).toHaveTextContent('Amount: That amount is over the limit.');
  });

  it('an error that comes with no submit (a check as you leave) moves nothing and is said politely', () => {
    function Leave() {
      const [error, setError] = useState('');
      return <Field label="Email" error={error}><input onBlur={() => setError('That isn’t an email address.')} /></Field>;
    }
    render(<LiveRegions><Leave /><button type="button">Next</button></LiveRegions>);
    const box = screen.getByLabelText('Email');
    box.focus();
    act(() => { screen.getByRole('button', { name: 'Next' }).focus(); });
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus();
    expect(screen.getByTestId('live-said')).toHaveTextContent('Email: That isn’t an email address.');
  });
});
