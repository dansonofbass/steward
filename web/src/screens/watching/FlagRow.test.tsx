import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../../test-utils';
import { FlagRowLink } from './FlagRow';
import { GIFT, PARENT, RALPHS } from './fixtures';

describe('A flag row', () => {
  it('reads like the mockup: the check in bold, the urgent mark, the account, the date and the amount', () => {
    wrapBook(<FlagRowLink row={GIFT} />, PARENT, '/b/margaret-ellis');
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/b/margaret-ellis/look-into/41');
    expect(link).toHaveClass('frow', 'is-urgent');
    expect(screen.getByText('Scam pattern:')).toBeInTheDocument();
    expect(screen.getByText('Urgent')).toBeInTheDocument();
    expect(screen.getByText('Joint checking')).toBeInTheDocument();
    expect(screen.getByText('$500.00')).toBeInTheDocument();
    expect(screen.getByText('Open')).toBeInTheDocument();
  });
  it('shows who is checking and the note, and leaves Open out on Home', () => {
    const { unmount } = wrapBook(<FlagRowLink row={RALPHS} />, PARENT, '/b/margaret-ellis');
    expect(screen.getByText('Still checking')).toBeInTheDocument();
    expect(screen.getByText('· JR, Oct 15')).toBeInTheDocument();
    expect(screen.getByText('JR: "Asked Margaret about two trips to Ralphs. Waiting to hear back."')).toBeInTheDocument();
    unmount();
    wrapBook(<FlagRowLink row={GIFT} compact />, PARENT, '/b/margaret-ellis');
    expect(screen.queryByText('Open')).toBeNull();
  });
});
