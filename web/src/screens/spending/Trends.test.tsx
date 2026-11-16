import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { callsTo, renderAt, stubFetch } from '../../test-utils';
import { TRENDS, TRENDS6 } from './fixtures';
import { Trends } from './Trends';

afterEach(() => vi.unstubAllGlobals());
const cards = () => screen.getAllByTestId('trend-card');
const card = (c: string) => cards().find((x) => x.getAttribute('data-category') === c)!;

describe('Spending over time', () => {
  it('lists flexible categories by target, then fixed costs that vary', async () => {
    stubFetch({ '/api/spending/trends': TRENDS });
    renderAt(<Trends />, {}, '/spending/trends');
    await screen.findAllByTestId('trend-card');
    expect(screen.getByRole('heading', { level: 1, name: 'Spending over time' })).toBeInTheDocument();
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual(['Flexible', 'Fixed costs that vary']);
    expect(cards().map((c) => c.getAttribute('data-category'))).toEqual(['dining', 'shopping', 'groceries', 'personal', 'utilities']);
    const dining = cards()[0];
    expect(within(dining).getByText('Over in 4 of the last 12 months')).toHaveClass('is-over');
    expect(dining).toHaveTextContent('Target $500 · typical month $470');
    expect(dining).toHaveAttribute('href', '/b/ours/spending/dining');
    expect(dining.querySelectorAll('rect.sp-chart__bar')).toHaveLength(12);
    expect(dining.querySelectorAll('rect.sp-chart__bar.is-over')).toHaveLength(4);
    expect(dining.querySelectorAll('rect.sp-chart__bar.so-far')).toHaveLength(1);
    expect(within(dining).queryByRole('img')).toBeNull();   // the link's own text says it once
    expect(dining).toHaveAccessibleName(/^Eating out\s*Over in 4 of the last 12 months\s*Target \$500/);
    expect(cards()[4].querySelectorAll('rect.sp-chart__bar.is-over')).toHaveLength(0);   // a fixed cost is never over
    expect(screen.getByText('Housing, Insurance and Giving are the same every month, so they are not drawn.')).toBeInTheDocument();
    expect(screen.queryByText('Taxes')).toBeNull();
    expect(screen.getByText(/October is the month so far\./)).toBeInTheDocument();
    expect(within(screen.getByRole('navigation', { name: 'Spending views' })).getByRole('link', { name: 'Over time' })).toHaveAttribute('aria-current', 'page');
  });

  it('draws the month so far faded and labelled, and does not count it as over', async () => {
    stubFetch({ '/api/spending/trends': TRENDS });
    renderAt(<Trends />, {}, '/spending/trends');
    await screen.findAllByTestId('trend-card');
    const shopping = card('shopping');
    // Shopping's October ($512) is above its $400 line, so its bar is red, but faded, and the count (from the API) leaves it out.
    const bars = shopping.querySelectorAll('rect.sp-chart__bar');
    const last = bars[bars.length - 1];
    expect(last).toHaveClass('is-over', 'so-far');
    expect(within(shopping).getByText('Over in 5 of the last 12 months')).toBeInTheDocument();
    expect(within(shopping).getByText('so far')).toHaveAttribute('title', 'October, so far');
    expect(within(shopping).getByText('so far')).toHaveClass('sp-chart__month');
    expect(card('groceries').querySelectorAll('rect.so-far')).toHaveLength(1);
  });

  it('reads a one-month window as last month', async () => {
    const one = { ...TRENDS, categories: TRENDS.categories.map((r) => (r.category === 'dining' ? { ...r, over_in: 1, over_of: 1 } : r)) };
    stubFetch({ '/api/spending/trends': one });
    renderAt(<Trends />, {}, '/spending/trends');
    await screen.findAllByTestId('trend-card');
    expect(within(card('dining')).getByText('Over last month')).toBeInTheDocument();
  });

  it('Last 6 months asks for six and draws six bars', async () => {
    const fetchMock = stubFetch({ '/api/spending/trends?months=6': TRENDS6, '/api/spending/trends': TRENDS });
    const { location } = renderAt(<Trends />, {}, '/spending/trends');
    await screen.findAllByTestId('trend-card');
    expect(screen.getByRole('button', { name: 'Last 12 months' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Last 6 months' }));
    await waitFor(() => expect(cards()[0].querySelectorAll('rect.sp-chart__bar')).toHaveLength(6));
    expect(location.current.search).toBe('?months=6');
    // The count follows the span: "of the last 12" before, "of the last 6" now.
    expect(within(cards()[0]).getByText('Over in 3 of the last 6 months')).toHaveClass('is-over');
    expect(callsTo(fetchMock, 'GET', '/api/spending/trends?months=6')).toHaveLength(1);
  });

  it('leaves out a fixed cost with nothing to judge it by: neither drawn nor named the same every month (ruling 24)', async () => {
    const unjudged = { category: 'childcare_education', kind: 'fixed' as const, group: 'unjudged' as const, target_cents: null,
      expected_cents: null, typical_cents: null, spent: [...Array(11).fill(0), 82_000], over_in: 0, over_of: 0, order: 9 };
    stubFetch({ '/api/spending/trends': { ...TRENDS, categories: [...TRENDS.categories, unjudged] } });
    renderAt(<Trends />, {}, '/spending/trends');
    await screen.findAllByTestId('trend-card');
    expect(cards().map((c) => c.getAttribute('data-category'))).toEqual(['dining', 'shopping', 'groceries', 'personal', 'utilities']);
    expect(screen.queryByText(/Childcare/)).toBeNull();
  });

  it('a book whose only fixed costs have nothing to judge them by has nothing to draw yet', async () => {
    const unjudged = { category: 'housing', kind: 'fixed' as const, group: 'unjudged' as const, target_cents: null,
      expected_cents: 268_000, typical_cents: null, spent: [...Array(11).fill(0), 268_000], over_in: 0, over_of: 0, order: 0 };
    stubFetch({ '/api/spending/trends': { ...TRENDS, categories: [unjudged] } });
    renderAt(<Trends />, {}, '/spending/trends');
    expect(await screen.findByText(/^Nothing to draw yet\./)).toBeInTheDocument();
    expect(screen.queryByTestId('trend-card')).toBeNull();
  });

  it('a book with nothing finished yet says so', async () => {
    stubFetch({ '/api/spending/trends': { ...TRENDS, categories: [] } });
    renderAt(<Trends />, {}, '/spending/trends');
    expect(await screen.findByText(/^Nothing to draw yet\./)).toBeInTheDocument();
  });
});
