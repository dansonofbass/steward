import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { setCurrentBook } from '../../api/book';
import { markSetupOpen, PlanReadyLine } from './PlanReady';

describe('the Plan checklist done (phase 17 spec 3.7)', () => {
  it('the first overview after this device saw the checklist unfinished says so, once (R2: one count-free line)', () => {
    markSetupOpen();
    const first = render(<PlanReadyLine />);
    expect(screen.getByTestId('plan-ready')).toHaveTextContent('Every box ticked. The plan can see you now.');
    first.unmount();
    render(<PlanReadyLine />);
    expect(screen.queryByTestId('plan-ready')).toBeNull();
  });

  it('each book keeps its own note', () => {
    setCurrentBook('other');
    markSetupOpen();
    setCurrentBook('ours');
    render(<PlanReadyLine />);
    expect(screen.queryByTestId('plan-ready')).toBeNull();
  });

  it('a device that never saw the checklist says nothing', () => {
    render(<PlanReadyLine />);
    expect(screen.queryByTestId('plan-ready')).toBeNull();
  });
});
