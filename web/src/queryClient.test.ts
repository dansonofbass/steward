import { afterEach, describe, expect, it } from 'vitest';
import { currentBook, setCurrentBook } from './api/book';
import { ApiError } from './api/client';
import { makeQueryClient, setQueryDataIfStillIn } from './queryClient';

afterEach(() => setCurrentBook('ours'));

describe('the query cache', () => {
  it('the same key in two books is two cache entries; the person\'s own keys are shared', () => {
    const qc = makeQueryClient();
    setCurrentBook('ours');
    qc.setQueryData(['accounts'], { accounts: ['ours'] });
    qc.setQueryData(['me'], { user: 1 });
    setCurrentBook('mom');
    expect(qc.getQueryData(['accounts'])).toBeUndefined();
    expect(qc.getQueryData(['me'])).toEqual({ user: 1 });
    qc.setQueryData(['accounts'], { accounts: ['mom'] });
    setCurrentBook('ours');
    expect(qc.getQueryData(['accounts'])).toEqual({ accounts: ['ours'] });
  });
});

describe('a retry after a book switch', () => {
  it('never stores the other book\'s data in the first book\'s entry', async () => {
    const qc = makeQueryClient();
    setCurrentBook('a');
    let attempts = 0;
    // Like the screens' queryFns: the open book is read again on every attempt.
    const queryFn = async () => {
      attempts += 1;
      if (attempts === 1) throw new ApiError(503, 'down');
      return { from: currentBook() };
    };
    const first = qc.fetchQuery({ queryKey: ['accounts'], queryFn, retry: 1, retryDelay: 30 }).catch(() => 'cancelled');
    await new Promise((r) => setTimeout(r, 10));
    setCurrentBook('b');
    await first;
    await new Promise((r) => setTimeout(r, 80));
    setCurrentBook('a');
    expect(attempts).toBe(1);
    expect(qc.getQueryData(['accounts'])).toBeUndefined();
  });
});

describe('an answer that lands after a book switch', () => {
  it('is written when the book is the same and skipped when it changed', () => {
    const qc = makeQueryClient();
    setCurrentBook('ours');
    expect(setQueryDataIfStillIn(qc, 'ours', ['setup'], () => ({ from: 'ours' }))).toBe(true);
    expect(qc.getQueryData(['setup'])).toEqual({ from: 'ours' });
    setCurrentBook('mom');   // the person switched while the request was in flight
    expect(setQueryDataIfStillIn(qc, 'ours', ['setup'], () => ({ from: 'late ours' }))).toBe(false);
    expect(qc.getQueryData(['setup'])).toBeUndefined();   // mom's entry untouched
    setCurrentBook('ours');
    expect(qc.getQueryData(['setup'])).toEqual({ from: 'ours' });
  });
});
