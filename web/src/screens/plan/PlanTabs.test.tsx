import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { askState, resetAsk } from '../../ask/store';
import { wrapBook } from '../../test-utils';
import { PlanTabs } from './PlanTabs';

afterEach(() => { resetAsk(); });

describe('Ask about the Plan (P18)', () => {
  it('ends the tab row on Overview and How it works, both about the Plan', () => {
    const first = wrapBook(<PlanTabs on="overview" />, { chat: true });
    fireEvent.click(screen.getByRole('button', { name: 'Ask about the Plan' }));
    expect(askState().about).toStrictEqual({ kind: 'plan' });
    expect(askState().surface).toStrictEqual({ kind: 'plan', page: 'overview' });
    first.unmount();
    wrapBook(<PlanTabs on="how" />, { chat: true });
    fireEvent.click(screen.getByRole('button', { name: 'Ask about the Plan' }));
    expect(askState().surface).toStrictEqual({ kind: 'plan', page: 'how' });
  });
  it('is not on Try changes, Next dollar or Taxes, nor while setup is unfinished, nor with chat off', () => {
    for (const on of ['try', 'next', 'taxes'] as const) {
      const r = wrapBook(<PlanTabs on={on} />, { chat: true });
      expect(document.querySelector('.ask-about')).toBeNull();
      r.unmount();
    }
    const unready = wrapBook(<PlanTabs on="overview" ready={false} />, { chat: true });
    expect(document.querySelector('.ask-about')).toBeNull();
    unready.unmount();
    wrapBook(<PlanTabs on="overview" />);
    expect(document.querySelector('.ask-about')).toBeNull();
  });
});
