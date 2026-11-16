import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { PairForm, normalizeCode } from './PairForm';

afterEach(() => vi.unstubAllGlobals());

describe('PairForm', () => {
  it('upper-cases and drops the dash and spaces, as the gateway does', () => {
    expect(normalizeCode(' k7m-4qx ')).toBe('K7M4QX');
  });
  it("sends the code once and shows the server's words, with no celebration", async () => {
    const f = stubFetch({ 'POST /api/install/gateway/pair': () => reply({ line: 'Paired with Zebra-Box.' }) });
    const { container } = wrapBook(<PairForm />);
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'k7m-4qx' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pair' }));
    expect(await screen.findByText('Paired with Zebra-Box.')).toBeInTheDocument();
    expect(callsTo(f, 'POST', '/api/install/gateway/pair')).toHaveLength(1);
    expect(callsTo(f, 'POST', '/api/install/gateway/pair')[0].body).toEqual({ code: 'K7M4QX' });
    expect(container.querySelector('.acorn')).toBeNull();
  });
  it("shows a refusal as the field's error", async () => {
    stubFetch({ 'POST /api/install/gateway/pair': () => reply({ error: "That code doesn't match. 4 tries left." }, 422) });
    wrapBook(<PairForm />);
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: 'AAAAAA' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pair' }));
    expect(await screen.findByText("That code doesn't match. 4 tries left.")).toBeInTheDocument();
  });
});
