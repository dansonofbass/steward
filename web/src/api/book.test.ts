import { afterEach, describe, expect, it } from 'vitest';
import { currentBook, resolveApiPath, setCurrentBook } from './book';

afterEach(() => setCurrentBook('ours'));

describe('resolveApiPath', () => {
  it('puts book routes under the open book', () => {
    setCurrentBook('mom-robins');
    expect(resolveApiPath('/api/accounts')).toBe('/api/b/mom-robins/accounts');
    expect(resolveApiPath('/api/transactions?q=x')).toBe('/api/b/mom-robins/transactions?q=x');
    expect(resolveApiPath('/api/profile/home')).toBe('/api/b/mom-robins/profile/home');
  });
  it('leaves person and directory routes, and paths that already name a book, alone', () => {
    for (const p of ['/api/auth/me', '/api/auth/passkeys/1', '/api/users', '/api/users/2/reset-password', '/api/books',
      '/api/books/mom/members', '/api/invites/accept', '/api/health', '/api/setup', '/api/setup/check', '/api/install/settings', '/api/install/gateway/pair','/api/b/ours/accounts', '/assets/x.js']) {
      expect(resolveApiPath(p)).toBe(p);
    }
  });
  it('a path that only starts like /api/books is still a book route', () => {
    expect(resolveApiPath('/api/bookshelf')).toBe('/api/b/ours/bookshelf');
  });
  it('refuses a book route when no book is open', () => {
    setCurrentBook(null);
    expect(currentBook()).toBeNull();
    expect(() => resolveApiPath('/api/accounts')).toThrow('No book is open');
  });
});
