import { describe, expect, it } from 'vitest';
import { titleName } from './itemTitle';

// Issue #29, privacy ruling: a page title goes into the browser's history and, with sync on, to the browser's maker. An
// item's title uses its name, never its numbers.
describe('titleName', () => {
  const CASES: [string, string][] = [
    ['Checking ••6789', 'Checking'],
    ['Joint checking (••4321)', 'Joint checking'],
    ['Savings xx4321', 'Savings'],
    ['Visa ...1234', 'Visa'],
    ['Card *0042', 'Card'],
    ['Card ending 1234', 'Card ending'],
    ['Emergency fund $1,500', 'Emergency fund'],
    ['Trip to Denver 2026', 'Trip to Denver'],
    ['2026 - Denver', 'Denver'],
    ['Acct 12345678 - Joint', 'Acct - Joint'],
    ['6789', ''],
    ['••6789', ''],
  ];
  for (const [name, title] of CASES) it(`titles "${name}" as "${title}"`, () => {
    expect(titleName(name)).toBe(title);
  });

  it('keeps a name with no numbers, and a number of one or two digits', () => {
    expect(titleName('Joint checking')).toBe('Joint checking');
    expect(titleName('Room 12')).toBe('Room 12');
    expect(titleName('Kitchen #2')).toBe('Kitchen #2');
    expect(titleName('Edit Grandfather clock')).toBe('Edit Grandfather clock');
  });

  it("keeps a plan's own name, and still drops the account's numbers beside it", () => {
    expect(titleName('Vanguard 401(k)')).toBe('Vanguard 401(k)');
    expect(titleName('403(b) ••5521')).toBe('403(b)');
    expect(titleName('457 (b) plan')).toBe('457 (b) plan');
    expect(titleName('NY 529 Direct Plan')).toBe('NY 529 Direct Plan');
    expect(titleName('529 ••4410')).toBe('529');
    expect(titleName('Fidelity 401(k) 123456789')).toBe('Fidelity 401(k)');
    expect(titleName('Acct 5290001')).toBe('Acct');           // a 529 inside a longer number is the number
    expect(titleName('••529')).toBe('');                      // a masked last three is the number
  });

  it('leaves no run of three digits in any title', () => {
    for (const name of ['a1b2c3', 'x123y', '1 2 3', '12.345', '#9999', '(555) 123-4567']) {
      expect(titleName(name), name).not.toMatch(/\d{3}/);
    }
  });
});
