import { afterEach, describe, expect, it } from 'vitest';
import { forgetProfileOpened, noteProfileOpened, profileOpened } from '../book/profileVisit';
import { forgetSignedOut } from './signedOut';

afterEach(() => { sessionStorage.clear(); forgetProfileOpened(); });

describe('signing out', () => {
  it("forgets which books' Home opened Profile, so the next person in this tab gets their own visit (issue 30)", () => {
    noteProfileOpened('ours');
    expect(profileOpened('ours')).toBe(true);
    forgetSignedOut();
    expect(profileOpened('ours')).toBe(false);
  });
});
