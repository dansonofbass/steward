import { describe, expect, it } from 'vitest';
import { caretAfter, dollarsText, formatMoneyInput, fromHundredths, NOT_A_NUMBER, significantBefore, toHundredths, TWO_DECIMALS } from './money';

describe('toHundredths', () => {
  it.each([
    ['3.25', 325], ['3', 300], ['3.2', 320], ['0.5', 50], ['12000', 1_200_000], ['-12000.10', -1_200_010],
    ['-0.50', -50], [' 1,250.00 ', 125_000], ['$40', 4000], ['3.', 300],
  ])('%s -> %d', (s, n) => expect(toHundredths(s)).toEqual({ value: n }));

  it('does not round through floating point', () => expect(toHundredths('19.99')).toEqual({ value: 1999 }));
  it('rejects more than two decimals', () => expect(toHundredths('3.255')).toEqual({ error: TWO_DECIMALS }));
  it.each(['', 'abc', '1.2.3', '--4', '.5', '1e3'])('rejects %j', (s) => expect(toHundredths(s)).toEqual({ error: NOT_A_NUMBER }));
});

describe('fromHundredths', () => {
  it.each([[325, '3.25'], [300, '3'], [320, '3.2'], [-50, '-0.5'], [125_000, '1250']])('%d -> %s', (n, s) => expect(fromHundredths(n)).toBe(s));
});

describe('formatMoneyInput', () => {
  it.each([
    ['', ''], ['1', '1'], ['1492733', '1,492,733'], ['1,492,733', '1,492,733'], ['$1,234.56', '1,234.56'],
    ['1234.', '1,234.'], ['.5', '0.5'], ['007', '7'], ['1234.567', '1,234.567'], ['abc', ''], ['12a3', '123'],
    ['1.2.3', '1.23'], ['$', ''], [' 1 000 ', '1,000'],
  ])('%j -> %j', (raw, out) => expect(formatMoneyInput(raw)).toBe(out));

  it('drops a minus unless negatives are allowed', () => {
    expect(formatMoneyInput('-1234')).toBe('1,234');
    expect(formatMoneyInput('-1234', true)).toBe('-1,234');
    expect(formatMoneyInput('-$1234.5', true)).toBe('-1,234.5');
    expect(formatMoneyInput('-', true)).toBe('-');
    expect(formatMoneyInput('(1,234.56)', true)).toBe('-1,234.56');
    expect(formatMoneyInput('($1,234.56)')).toBe('1,234.56');
    expect(formatMoneyInput('1-2', true)).toBe('12');
  });

  it('round-trips through toHundredths as exact cents', () => {
    expect(toHundredths(formatMoneyInput('1492733'))).toEqual({ value: 149_273_300 });
    expect(toHundredths(formatMoneyInput('$1,234.56'))).toEqual({ value: 123_456 });
    expect(toHundredths(formatMoneyInput('-12000.1', true))).toEqual({ value: -1_200_010 });
    expect(toHundredths(formatMoneyInput('1.234'))).toEqual({ error: TWO_DECIMALS });
    expect(toHundredths(formatMoneyInput(''))).toEqual({ error: NOT_A_NUMBER });
  });

  it('shows stored cents with separators', () => {
    expect(dollarsText(149_273_300)).toBe('1,492,733');
    expect(dollarsText(-123_450)).toBe('-1,234.5');
    expect(dollarsText(0)).toBe('0');
  });
});

describe('caret helpers', () => {
  it('keeps the caret after the same digit when separators appear', () => {
    // typing the 4th digit of "1234" at the end: raw "1234", caret 4 -> formatted "1,234"
    expect(caretAfter('1,234', significantBefore('1234', 4))).toBe(5);
    // caret between "1" and "2" stays between them
    expect(caretAfter('1,234', significantBefore('1234', 1))).toBe(1);
    expect(caretAfter('1,234', significantBefore('1234', 2))).toBe(3);
  });
});
