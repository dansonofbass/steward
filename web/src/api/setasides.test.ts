import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';
import { invalidateSetAsides } from './setasides';

describe('invalidateSetAsides', () => {
  it('invalidates Spending, the list, the Plan, Transactions and the summary, and nothing else', async () => {
    const qc = new QueryClient();
    const seen: unknown[] = [];
    qc.invalidateQueries = (async (filters?: { queryKey?: unknown }) => { seen.push(filters?.queryKey); }) as QueryClient['invalidateQueries'];
    await invalidateSetAsides(qc);
    expect(seen).toEqual([['spending'], ['setasides'], ['plan'], ['transactions'], ['summary']]);
  });
});
