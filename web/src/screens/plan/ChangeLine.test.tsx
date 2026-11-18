import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PlanReady } from './api';
import { ChangeLine } from './ChangeLine';
import { CLOSER_CHEERS } from './copy';
import { planFixture } from './fixtures';

const fx = vi.hoisted(() => ({ closer: vi.fn((_a: { over: HTMLElement }) => {}),
  acorn: vi.fn(() => () => {}), winMoment: vi.fn(() => () => {}) }));
vi.mock('../../celebrate/celebrate', () => fx);

beforeEach(() => { localStorage.clear(); fx.closer.mockClear(); });

/** The fixture with today's Comfortably age `months` earlier than the saved plan's (negative: later). */
function moved(months: number): PlanReady {
  const d = planFixture();
  d.inputs_summary.comfortable_months = d.plan!.inputs_summary!.comfortable_months! - months;
  return d;
}
const settle = () => new Promise((r) => setTimeout(r, 0));

describe('the change line on the Overview (plan subpages decision 7)', () => {
  it('a year earlier: the line, a cheer from the year bag, and a small burst from the line', async () => {
    render(<ChangeLine data={moved(12)} />);
    const line = screen.getByTestId('change-line');
    expect(line).toHaveTextContent(/^▼ 1 year earlier than on Oct 1[23](, 2026)?\.$/);
    expect(CLOSER_CHEERS.year).toContain(screen.getByTestId('change-cheer').textContent);
    await vi.waitFor(() => expect(fx.closer).toHaveBeenCalledWith({ over: line }));
  });

  it('the arrow follows the age, as the words do: down for earlier, up for later', () => {
    const later = render(<ChangeLine data={moved(-12)} />);
    expect(screen.getByTestId('change-line')).toHaveTextContent(/^▲ 1 year later than on Oct 1[23](, 2026)?\.$/);
    later.unmount();
    render(<ChangeLine data={moved(3)} />);
    expect(screen.getByTestId('change-line')).toHaveTextContent(/^▼ 3 months earlier than on /);
  });

  it('half a year and two years draw from their own bags', async () => {
    const half = render(<ChangeLine data={moved(7)} />);
    expect(CLOSER_CHEERS.half).toContain(screen.getByTestId('change-cheer').textContent);
    half.unmount();
    localStorage.clear();
    render(<ChangeLine data={moved(26)} />);
    expect(CLOSER_CHEERS.years).toContain(screen.getByTestId('change-cheer').textContent);
    await vi.waitFor(() => expect(fx.closer).toHaveBeenCalledTimes(2));
  });

  it('under 6 months, later, or no change: the line only', async () => {
    for (const m of [3, -12, 0]) {
      const r = render(<ChangeLine data={moved(m)} />);
      expect(screen.getByTestId('change-line')).toBeInTheDocument();
      expect(screen.queryByTestId('change-cheer')).toBeNull();
      r.unmount();
    }
    await settle();
    expect(fx.closer).not.toHaveBeenCalled();
  });

  it('celebrates a change once: coming back shows the line without a new cheer or burst', async () => {
    const data = moved(12);
    const first = render(<ChangeLine data={data} />);
    await vi.waitFor(() => expect(fx.closer).toHaveBeenCalledTimes(1));
    first.unmount();
    const again = render(<ChangeLine data={data} />);
    expect(screen.getByTestId('change-line')).toHaveTextContent(/1 year earlier/);
    expect(screen.queryByTestId('change-cheer')).toBeNull();
    await settle();
    expect(fx.closer).toHaveBeenCalledTimes(1);
    again.unmount();
    // New inputs make a new change, and that one is celebrated.
    const next = moved(12);
    next.result.input_digest = 'def456';
    render(<ChangeLine data={next} />);
    expect(screen.getByTestId('change-cheer')).toBeInTheDocument();
    await vi.waitFor(() => expect(fx.closer).toHaveBeenCalledTimes(2));
  });

  it('shows nothing when no plan is saved yet', () => {
    const { container } = render(<ChangeLine data={{ ...planFixture(), plan: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
