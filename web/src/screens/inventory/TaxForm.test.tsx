import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, reply, stubFetch, wrapBook } from '../../test-utils';
import { TaxForm } from './TaxForm';
import { uploadFile } from './api';

vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./api')>()), uploadFile: vi.fn() }));

afterEach(() => { vi.unstubAllGlobals(); vi.mocked(uploadFile).mockReset(); });
const OWNERS = [{ key: 'margaret', label: 'Margaret' }, { key: 'joint', label: 'Joint' }];
const PARENT = { slug: 'margaret-ellis', name: 'Margaret Ellis', kind: 'parent' as const, owners: OWNERS };

describe('Type in a tax form', () => {
  it('saves a 1099-INT with the attached file and says what it added', async () => {
    const fetchMock = stubFetch({ 'POST /api/inventory/tax-forms': () => reply({
      headline: "1099-INT saved. Harbor Savings Bank isn't in Margaret's inventory.",
      detail: 'Added to the suggestion already waiting for Harbor Savings Bank: account ••2207, $58.90 interest in 2025.',
      suggestion_id: 3, item_id: null }, 201) });
    wrapBook(<TaxForm />, PARENT, '/b/margaret-ellis/inventory/tax-form?file=31&name=1099-INT%202025%20Harbor%20Savings.pdf');
    expect(screen.getByText('Interest from a bank, credit union or savings bonds.')).toBeInTheDocument();
    expect(screen.getByText('1099-INT 2025 Harbor Savings.pdf')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Payer's name"), { target: { value: 'Harbor Savings Bank' } });
    fireEvent.change(screen.getByLabelText('Account number, last 4 (if shown)'), { target: { value: '2207' } });
    fireEvent.change(screen.getByLabelText('Box 1 Interest income'), { target: { value: '58.90' } });
    fireEvent.click(screen.getByRole('button', { name: "Save and check Margaret's items" }));
    expect(await screen.findByText("1099-INT saved. Harbor Savings Bank isn't in Margaret's inventory.")).toBeInTheDocument();
    const body = callsTo(fetchMock, 'POST', '/api/inventory/tax-forms')[0].body as Record<string, unknown>;
    expect(body).toEqual({ form: '1099-INT', tax_year: new Date().getFullYear() - 1, recipient: 'margaret', payer: 'Harbor Savings Bank',
      last4: '2207', boxes: { box_1: 5890 }, file_id: 31 });
    expect(screen.getByRole('link', { name: "Go to Is this one of Margaret's?" })).toHaveAttribute('href', '/b/margaret-ellis/inventory/suggestions');
  });
  it('switches forms and imports a CSV', async () => {
    const fetchMock = stubFetch({ 'POST /api/inventory/tax-forms/csv': () => reply({ saved: 2, results: [
      { headline: '1099-INT saved.', detail: 'Nothing new to add.', suggestion_id: null, item_id: 4 },
      { headline: "1099-DIV saved. Lakeside Funds isn't in Margaret's inventory.", detail: 'Added to Is this one of Margaret\'s?: account ••8812, $312.40 dividends in 2025.', suggestion_id: 9, item_id: null }] }, 201) });
    wrapBook(<TaxForm />, PARENT, '/b/margaret-ellis/inventory/tax-form');
    fireEvent.click(screen.getByRole('radio', { name: '1099-R' }));
    expect(screen.getByLabelText('Box 7 Distribution code')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Import several from a CSV'), { target: { files: [new File(['form,tax_year'], 'tax_forms.csv', { type: 'text/csv' })] } });
    expect(await screen.findByText('2 forms saved.')).toBeInTheDocument();
    expect(screen.getByText("1099-DIV saved. Lakeside Funds isn't in Margaret's inventory.")).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST', '/api/inventory/tax-forms/csv')).toHaveLength(1);
  });
  it('sends a viewer away without showing the form', () => {
    stubFetch({});
    wrapBook(<TaxForm />, { ...PARENT, role: 'viewer' }, '/b/margaret-ellis/inventory/tax-form');
    expect(screen.queryByLabelText("Payer's name")).not.toBeInTheDocument();
  });
  it('keeps Save off while the form is uploading, so it never saves without its file', async () => {
    let finish!: () => void;
    vi.mocked(uploadFile).mockImplementation(() => new Promise((resolve) => {
      finish = () => resolve({ file: { id: 44, name: 'form.pdf' } } as never);
    }));
    stubFetch({});
    wrapBook(<TaxForm />, PARENT, '/b/margaret-ellis/inventory/tax-form');
    fireEvent.change(screen.getByLabelText('Attach the form', { selector: 'input' }), { target: { files: [new File(['x'], 'form.pdf', { type: 'application/pdf' })] } });
    expect(await screen.findByRole('button', { name: "Save and check Margaret's items" })).toBeDisabled();
    finish();
    expect(await screen.findByText('form.pdf')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: "Save and check Margaret's items" })).toBeEnabled();
  });
  it('treats a malformed ?file= as no file instead of sending null', async () => {
    const fetchMock = stubFetch({ 'POST /api/inventory/tax-forms': () => reply({ headline: 'Saved.', detail: 'Done.', suggestion_id: null, item_id: null }, 201) });
    wrapBook(<TaxForm />, PARENT, '/b/margaret-ellis/inventory/tax-form?file=abc&name=form.pdf');
    expect(screen.queryByText('form.pdf')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Attach the form' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Payer's name"), { target: { value: 'Harbor Savings Bank' } });
    fireEvent.click(screen.getByRole('button', { name: "Save and check Margaret's items" }));
    await screen.findByText('Saved.');
    expect(callsTo(fetchMock, 'POST', '/api/inventory/tax-forms')[0].body).not.toHaveProperty('file_id');
  });
});
