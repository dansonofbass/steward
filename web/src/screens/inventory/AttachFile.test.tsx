import { fireEvent, screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../../api/client';
import { stubFetch, wrapBook } from '../../test-utils';
import { uploadFile } from './api';
import { AttachFile } from './AttachFile';

// ESM exports can't be spied on; mock uploadFile and keep the rest of the module.
vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), uploadFile: vi.fn() }));
afterEach(() => { vi.unstubAllGlobals(); vi.mocked(uploadFile).mockReset(); });
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: [] };
const ITEM = { id: 6, kind: 'account', name: 'Deferred annuity', institution: 'Westmark Life', last4: '5521', status: 'needs_checking', files: [], history: [] };
const pdf = (name: string) => new File(['%PDF-1.4'], name, { type: 'application/pdf' });

describe('Attach a file', () => {
  it('uploads with the confirm box, shows the tax-form nudge and a refusal', async () => {
    stubFetch({ '/api/inventory/items/6': ITEM });
    const upload = vi.mocked(uploadFile)
      .mockResolvedValueOnce({ file: { id: 31, name: '1099-INT 2025 Harbor Savings.pdf', content_type: 'application/pdf', label: 'PDF', size: 98304, size_label: '96 KB', uploaded_on: '2026-10-18', uploaded_by: 'Jr' }, item: null, looks_like_tax_form: true })
      .mockRejectedValueOnce(new ApiError(415, 'Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. Save it as PDF or CSV and try again.'));
    wrapBook(<Routes><Route path="/b/:slug/inventory/:id/attach" element={<AttachFile />} /></Routes>, PARENT, '/b/margaret-ellis/inventory/6/attach');
    expect(await screen.findByText('To Westmark Life Deferred annuity ••5521, which Needs checking.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /Mark Deferred annuity Confirmed/ })).toBeChecked();
    fireEvent.change(screen.getByLabelText('Choose a file'), { target: { files: [pdf('1099-INT 2025 Harbor Savings.pdf')] } });
    expect(await screen.findByText('Attached · PDF · 96 KB')).toBeInTheDocument();
    expect(upload.mock.calls[0][1]).toEqual({ itemId: 6, confirm: true });
    expect(screen.getByRole('link', { name: 'Type it in' })).toHaveAttribute('href',
      '/b/margaret-ellis/inventory/tax-form?file=31&name=1099-INT%202025%20Harbor%20Savings.pdf');
    fireEvent.change(screen.getByLabelText('Choose a file'), { target: { files: [new File(['PK'], 'Westmark export.xlsx')] } });
    expect(await screen.findByText('Not attached: Steward takes PDF, PNG, JPEG, HEIC or CSV. Save it as PDF or CSV and try again.')).toBeInTheDocument();
  });
  it('a stopped upload leaves no row', async () => {
    stubFetch({ '/api/inventory/items/6': { ...ITEM, status: 'confirmed' } });
    vi.mocked(uploadFile).mockImplementation((_f, _o, _p, signal) => new Promise((_, reject) => {
      signal?.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')));
    }));
    wrapBook(<Routes><Route path="/b/:slug/inventory/:id/attach" element={<AttachFile />} /></Routes>, PARENT, '/b/margaret-ellis/inventory/6/attach');
    await screen.findByText('To Westmark Life Deferred annuity ••5521.');
    expect(screen.queryByRole('checkbox')).toBeNull();
    fireEvent.change(screen.getByLabelText('Choose a file'), { target: { files: [pdf('Statement.pdf')] } });
    const stop = await screen.findByRole('button', { name: 'Stop' });
    expect(stop).toHaveTextContent('Stop');   // a word beside the icon
    fireEvent.click(stop);
    await vi.waitFor(() => expect(screen.queryByText('Statement.pdf')).toBeNull());
  });
  it('sends you back to the item when it is closed, as the page itself does', async () => {
    stubFetch({ '/api/inventory/items/6': { ...ITEM, status: 'closed', closed_on: '2026-10-01' } });
    wrapBook(<Routes>
      <Route path="/b/:slug/inventory/:id/attach" element={<AttachFile />} />
      <Route path="/b/:slug/inventory/:id" element={<p>The item</p>} /></Routes>, PARENT, '/b/margaret-ellis/inventory/6/attach');
    expect(await screen.findByText('The item')).toBeInTheDocument();
    expect(screen.queryByLabelText('Choose a file')).toBeNull();
  });
});
