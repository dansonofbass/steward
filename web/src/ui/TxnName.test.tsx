import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { TxnName, txnLabel } from './TxnName';

const row = { merchant: 'PayPal', raw_description: 'PAYPAL *DISNEYPLUS' };

describe('a row with a name (P5)', () => {
  it('reads "Disney+ (PayPal)", the payee muted, and the payee alone without a name', () => {
    const { container, rerender } = render(<p><TxnName t={{ ...row, nickname: 'Disney+' }} /></p>);
    expect(container).toHaveTextContent('Disney+ (PayPal)');
    expect(screen.getByText('(PayPal)')).toHaveClass('txn-name__payee');
    rerender(<p><TxnName t={{ ...row, nickname: null }} /></p>);
    expect(container).toHaveTextContent(/^PayPal$/);
    rerender(<p><TxnName t={{ merchant: null, raw_description: 'SQ *VENDOR 2291', nickname: 'Coffee cart' }} /></p>);
    expect(container).toHaveTextContent('Coffee cart (SQ *VENDOR 2291)');
  });
  it('as plain text for a title', () => {
    expect(txnLabel({ ...row, nickname: 'Disney+' })).toBe('Disney+ (PayPal)');
    expect(txnLabel({ ...row })).toBe('PayPal');
    expect(txnLabel({ merchant: null, raw_description: 'CARD PAYMENT', nickname: null }, 'Transfer')).toBe('Transfer');
  });
});
