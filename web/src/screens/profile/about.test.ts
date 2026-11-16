import { describe, expect, it } from 'vitest';
import { aboutFormFrom, parseAbout, type AboutForm } from './about';

const TODAY = '2026-10-14';
const fact = (value: string) => ({ value, as_of: '2026-10-14', note: null });
const empty: AboutForm = { myName: 'JR', jrDob: '', spouseDob: '', state: '', filing: '' };
const full: AboutForm = { myName: 'JR', jrDob: '1984-03-12', spouseDob: '1986-07-30', state: 'CA', filing: 'mfj' };

describe('About you', () => {
  it('fills the form from saved facts and the signed-in name', () => {
    expect(aboutFormFrom({ 'jr.dob': fact('1984-03-12'), state: fact('CA') }, 'JR'))
      .toEqual({ myName: 'JR', jrDob: '1984-03-12', spouseDob: '', state: 'CA', filing: '' });
  });
  it('sends only what changed', () => {
    expect(parseAbout(full, empty, TODAY)).toEqual({ facts: [
      { key: 'jr.dob', value: '1984-03-12' }, { key: 'spouse.dob', value: '1986-07-30' },
      { key: 'state', value: 'CA' }, { key: 'filing_status', value: 'mfj' },
    ], name: null });
    expect(parseAbout({ ...full, myName: ' Jordan ' }, full, TODAY)).toEqual({ facts: [], name: 'Jordan' });
  });
  it('says what is missing in plain words', () => {
    expect(parseAbout({ ...empty, myName: '' }, empty, TODAY)).toEqual({ errors: {
      myName: 'Enter a name of up to 80 characters.', jrDob: 'Enter a birthday.', spouseDob: 'Enter a birthday.',
      state: 'Choose a state.', filing: 'Choose how you file taxes.',
    } });
    expect(parseAbout({ ...full, jrDob: '2026-10-14' }, empty, TODAY)).toEqual({ errors: { jrDob: 'Enter a birthday in the past.' } });
  });
  it('a confirm checks only your own birthday and name', () => {
    const base = { ...full, myName: 'Alex' };
    expect(parseAbout({ ...base, state: '', spouseDob: '1986-07-31' }, base, TODAY, 'spouse'))
      .toEqual({ facts: [{ key: 'spouse.dob', value: '1986-07-31' }], name: null });
  });
  it('a person who is neither JR nor the spouse has no name field to check', () => {
    expect(parseAbout({ ...full, myName: null }, { ...full, myName: null }, TODAY)).toEqual({ facts: [], name: null });
  });
});
