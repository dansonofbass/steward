import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { MoneyInput } from './MoneyInput';

function Harness({ negative = false }: { negative?: boolean }) {
  const [v, setV] = useState('');
  return <MoneyInput aria-label="Amount" allowNegative={negative} value={v} onValueChange={setV} />;
}
const input = () => screen.getByLabelText('Amount') as HTMLInputElement;

describe('MoneyInput', () => {
  it('shows a $ prefix and separators as you type', () => {
    const { container } = render(<Harness />);
    expect(container.querySelector('.affix__pre')).toHaveTextContent('$');
    fireEvent.change(input(), { target: { value: '1492733' } });
    expect(input().value).toBe('1,492,733');
  });
  it('cleans a pasted amount and drops letters', () => {
    render(<Harness />);
    fireEvent.change(input(), { target: { value: '$1,234.56' } });
    expect(input().value).toBe('1,234.56');
    fireEvent.change(input(), { target: { value: 'abc' } });
    expect(input().value).toBe('');
  });
  it('allows a minus only when asked', () => {
    const { unmount } = render(<Harness />);
    fireEvent.change(input(), { target: { value: '-5' } });
    expect(input().value).toBe('5');
    unmount();
    render(<Harness negative />);
    fireEvent.change(input(), { target: { value: '-1500' } });
    expect(input().value).toBe('-1,500');
  });
  it('keeps the caret beside the digit being edited', () => {
    render(<Harness />);
    fireEvent.change(input(), { target: { value: '1234' } });
    input().focus();
    input().setSelectionRange(1, 1);
    // insert a 9 after the first digit: "1" + "9" + "234" with the caret after the 9
    fireEvent.change(input(), { target: { value: '19,234', selectionStart: 2, selectionEnd: 2 } });
    expect(input().value).toBe('19,234');
    expect(input().selectionStart).toBe(2);
  });
});
