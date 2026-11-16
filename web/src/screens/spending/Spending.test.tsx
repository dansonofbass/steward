import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { letTestingLibraryDriveFakeTimers, useFakeTimers } from '../../test-clock';
import { callsTo, renderAt, reply, stubFetch } from '../../test-utils';
import { OCT, SEP } from './fixtures';
import { NOV_SECTION, OCT_SECTION } from './setasides/fixtures';
import { Spending } from './Spending';

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const ACCOUNTS = { '/api/accounts': { accounts: [] } };
const rows = () => screen.getAllByTestId('pace-row');
const row = (c: string) => rows().find((r) => r.getAttribute('data-category') === c)!;
/** The page's own way back to this month, not the This month tab above it. */
const backToThisMonth = () => screen.queryAllByRole('link', { name: 'This month' }).find((a) => !a.closest('nav')) ?? null;

describe('Spending, this month', () => {
  it("the Fixed costs section is the #fixed anchor Home's Bills sign opens", async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    const rows = await screen.findAllByTestId('fixed-row');
    expect(document.getElementById('fixed')).toContainElement(rows[0]);
  });

  it('heads the month with its one figure and lists everyday categories in the fixed order', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByRole('heading', { level: 1, name: 'October 2026' })).toBeInTheDocument();
    expect(screen.getByTestId('sp-total')).toHaveTextContent('$7,974 of $8,140');
    expect(screen.getByTestId('sp-line')).toHaveTextContent(/^6 days left\s*·\s*Flexible \$3,391 of \$3,550\s*·\s*Fixed costs \$4,583$/);
    expect(screen.getByTestId('sp-in-out')).toHaveTextContent(/^\$7,974 out · \$10,254 in$/);
    expect(rows().map((r) => r.getAttribute('data-category'))).toEqual(['groceries', 'dining', 'transport', 'shopping', 'home', 'kids', 'health', 'entertainment', 'personal', 'gifts']);
    expect(row('dining')).toHaveTextContent('On track');
    expect(row('dining')).toHaveTextContent('$468 of $500');
    expect(row('shopping')).toHaveTextContent('Over by $112');
    expect(row('personal')).toHaveTextContent('No target · typically $90 a month');
    expect(within(row('personal')).getByRole('link', { name: /Set one/ })).toHaveAttribute('href', '/b/ours/spending/targets');
    expect(within(row('dining')).getByRole('link', { name: 'Eating out' })).toHaveAttribute('href', '/b/ours/spending/dining?month=2026-10');
    expect(screen.getByTestId('unsorted-row')).toHaveTextContent('7 transactions without a category');
    expect(screen.getByTestId('unsorted-row')).toHaveAttribute('href', '/b/ours/review');
    expect(screen.getByText(/is today, Oct 25: 25 of 31 days\./)).toBeInTheDocument();
    // THO-10: the hidden mark sits between spaces, so a screen reader doesn't hear "The markis today".
    expect(document.querySelector('.sp-pace-key')!.textContent!.replace(/\s+/g, ' ')).toContain('The mark is today, Oct 25');
    expect(document.querySelectorAll('.sp-pace__today')).toHaveLength(8);
    expect(screen.getByText(/^Refunds count against their category\./)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Setting aside' })).toBeNull();
  });

  it('lists bills, then commitments under their label, each opening its category; only income is tinted', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    const fixed = await screen.findAllByTestId('fixed-row');
    expect(fixed.map((r) => r.getAttribute('data-category'))).toEqual(['housing', 'utilities', 'insurance', 'subscriptions', 'childcare_education', 'giving']);
    expect(fixed[0]).toHaveTextContent('Home loan · came out Oct 1');
    expect(within(fixed[0]).getByRole('link', { name: 'Housing' })).toHaveAttribute('href', '/b/ours/spending/housing?month=2026-10');
    expect(fixed[3]).toHaveTextContent('Streamflix · came out Oct 3 · New this month · StreamBox $7.99');
    expect(fixed[3]).toHaveClass('is-amber');
    expect(fixed[4]).toHaveClass('is-check');
    const label = screen.getByText('Commitments');
    expect(fixed[3].compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(fixed[4].compareDocumentPosition(label) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    expect(screen.getByText('Usual is the middle of the last 6 months with a payment.')).toBeInTheDocument();
    expect(screen.getByText('$4,590 expected')).toBeInTheDocument();
    expect(screen.getByText('Giving outside these accounts?', { exact: false })).toBeInTheDocument();
    const income = screen.getAllByTestId('income-row');
    expect(income[0]).toHaveAttribute('href', '/b/ours/transactions?category=income&dates=custom&from=2026-10-01&to=2026-10-25');
    expect(income[0].querySelector('.money--in')).toHaveTextContent('$10,240');
    expect(document.querySelectorAll('[data-testid="fixed-row"] .money--in, [data-testid="pace-row"] .money--in')).toHaveLength(0);
    expect(screen.getByTestId('sp-total').querySelector('.money--in')).toBeNull();
  });

  it('a bill waiting or late shows what is to come; a closed month with none paid shows no $0', async () => {
    const fixed = [
      { ...OCT.fixed[1], state: 'waiting' as const, tone: 'ring' as const, spent_cents: 0, came_out_on: null, merchant: null },
      { ...OCT.fixed[2], state: 'late' as const, tone: 'amber' as const, spent_cents: 0, came_out_on: null, merchant: null, typical_day: 5 },
    ];
    stubFetch({ '/api/spending': { ...OCT, fixed, head: { ...OCT.head, fixed_summary: 'to_come' as const, fixed_not_yet: 2 } }, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    const rows = await screen.findAllByTestId('fixed-row');
    expect(rows[0]).toHaveTextContent(/^UtilitiesUsually around the 12th\$410$/);
    expect(rows[0]).toHaveClass('is-ring');
    expect(rows[1]).toHaveTextContent(/^InsuranceNot seen yet · usually by the 5th\$360$/);
    expect(rows[1]).toHaveClass('is-amber');
    expect(screen.getByTestId('sp-line')).toHaveTextContent('Fixed costs $4,583 so far, 2 still to come');
  });

  it.each([
    ['this month', '/spending', '/api/spending', OCT, /^6 days left\s*·\s*Flexible \$3,391\s*·\s*Fixed costs \$4,583$/, '$7,974 spent'],
    ['a finished month', '/spending?month=2026-09', '/api/spending?month=2026-09', SEP, /^Flexible \$3,722\s*·\s*Fixed costs \$4,590$/, '$8,312 spent'],
  ])('without everyday targets, %s says what was spent and is never over (ruling 26)', async (_, path, api, base, line, total) => {
    stubFetch({ [api]: { ...base, has_targets: false, head: { ...base.head, everyday_target_cents: 0, planned_cents: 459_000 } }, ...ACCOUNTS });
    renderAt(<Spending />, {}, path);
    expect(await screen.findByTestId('sp-total')).toHaveTextContent(total);
    expect(screen.getByTestId('sp-total')).not.toHaveTextContent(/of/);
    expect(screen.getByTestId('sp-line')).toHaveTextContent(line);
    expect(screen.getByTestId('sp-line')).not.toHaveTextContent(/over|under/);
  });

  it('a wrapped head line never starts with a dot: each separator ends the part before it', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    const parts = (await screen.findByTestId('sp-line')).querySelectorAll('.sp-total__part');
    expect([...parts].map((p) => p.textContent)).toEqual(['6 days left · ', 'Flexible $3,391 of $3,550 · ', 'Fixed costs $4,583']);
  });

  it('names the month while it loads', async () => {
    stubFetch({ '/api/spending': () => new Promise<Response>(() => {}), ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2026-09');
    expect(screen.getByRole('heading', { level: 1, name: 'September 2026' })).toBeInTheDocument();
  });

  it('moves between months, stops at this one, and offers Over time and Targets', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByRole('link', { name: 'September 2026' })).toHaveAttribute('href', '/b/ours/spending?month=2026-09');
    expect(screen.getByRole('button', { name: 'Next month' })).toBeDisabled();
    const pills = screen.getByRole('navigation', { name: 'Spending views' });
    expect(within(pills).getByRole('link', { name: 'This month' })).toHaveAttribute('aria-current', 'page');
    expect(within(pills).getByRole('link', { name: 'Over time' })).toHaveAttribute('href', '/b/ours/spending/trends');
    expect(within(pills).getByRole('link', { name: 'Targets' })).toHaveAttribute('href', '/b/ours/spending/targets');
    expect(within(pills).getByRole('link', { name: 'Setting aside' })).toHaveAttribute('href', '/b/ours/spending/setasides');
    expect(screen.queryByRole('link', { name: 'Home' })).toBeNull();   // Spending is a tab of its own, not a page under Home
  });

  it('stops going back at the first month with data (ruling 22)', async () => {
    stubFetch({ '/api/spending?month=2024-10': { ...SEP, month: '2024-10', earliest: '2024-10' }, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2024-10');
    await screen.findByTestId('sp-total');   // the loading state already names the month
    expect(screen.getByRole('heading', { level: 1, name: 'October 2024' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'September 2024' })).toBeDisabled();
    expect(screen.queryByRole('link', { name: 'September 2024' })).toBeNull();
    expect(screen.getByRole('link', { name: 'November 2024' })).toHaveAttribute('href', '/b/ours/spending?month=2024-11');
  });

  it('a finished month has no today mark and no days left, and says how it ended', async () => {
    stubFetch({ '/api/spending?month=2026-09': SEP, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2026-09');
    await screen.findByTestId('sp-total');
    expect(screen.getByRole('heading', { level: 1, name: 'September 2026' })).toBeInTheDocument();
    expect(screen.getByTestId('sp-total')).toHaveTextContent('$8,312 of $8,140');
    expect(screen.getByTestId('sp-line')).toHaveTextContent(/^\$172 over\s*·\s*Flexible \$3,722 of \$3,550/);
    expect(document.querySelector('.sp-pace__today')).toBeNull();
    expect(screen.queryByText(/is today/)).toBeNull();
    expect(row('transport')).toHaveTextContent('Over by $5');
    expect(row('groceries')).toHaveTextContent('$80 to spare');
    expect(screen.getByRole('link', { name: 'October 2026' })).toHaveAttribute('href', '/b/ours/spending?month=2026-10');
  });

  it('an over state is amber when clear and ink when a little over, never red, and the Flexible section opens with the line', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    await screen.findAllByTestId('pace-row');
    expect(row('shopping').querySelector('.sp-pace__state')).toHaveClass('is-clear');
    expect(row('shopping').querySelector('.sp-pace__fill')).toHaveClass('is-clear');
    expect(document.querySelectorAll('.is-ahead, .is-over.sp-pace__fill')).toHaveLength(0);
    const section = document.getElementById('flexible')!;
    expect(within(section).getByTestId('over-line')).toHaveTextContent('Shopping is $112 over its target · See Shopping');
  });

  describe('the monthly target check (P19)', () => {
    const CHECKED = { ...OCT, target_check: { category: 'dining', target_cents: 30_000, typical_cents: 42_000 } };
    it('Set writes the typical month and says so, with Undo', async () => {
      const fetchMock = stubFetch({ '/api/spending': CHECKED, ...ACCOUNTS, 'POST /api/spending/targets/dining/check': { target_cents: 42_000, until: null, undo: 'tok-s' }, 'POST /api/undo/tok-s': { undone: 0, transaction: null } });
      renderAt(<Spending />, {}, '/spending');
      const card = await screen.findByTestId('target-check');
      expect(card).toHaveTextContent("Eating out's target is below a typical month · Target $300 · typical $420");
      fireEvent.click(within(card).getByRole('button', { name: 'Set to $420' }));
      expect(await screen.findByRole('status')).toHaveTextContent("Eating out's target is $420 · Undo");
      expect(callsTo(fetchMock, 'POST', '/api/spending/targets/dining/check')[0].body).toEqual({ answer: 'set', target_cents: 30_000 });
      expect(screen.queryByTestId('target-check')).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
      await waitFor(() => expect(callsTo(fetchMock, 'POST', '/api/undo/tok-s')).toHaveLength(1));
    });
    it('Keep folds the card away, names the month it comes back, and the toast leaves after 10 seconds', async () => {
      useFakeTimers();
      letTestingLibraryDriveFakeTimers();
      stubFetch({ '/api/spending': CHECKED, ...ACCOUNTS, 'POST /api/spending/targets/dining/check': { target_cents: 30_000, until: '2027-01-01', undo: 'tok-k' } });
      renderAt(<Spending />, {}, '/spending');
      fireEvent.click(within(await screen.findByTestId('target-check')).getByRole('button', { name: 'Keep $300' }));
      expect(await screen.findByRole('status')).toHaveTextContent('Kept at $300 until Jan · Undo');
      expect(screen.queryByTestId('target-check')).toBeNull();
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(screen.queryByRole('status')).toBeNull();
    });
    it('a viewer sees no card', async () => {
      stubFetch({ '/api/spending': CHECKED, ...ACCOUNTS });
      renderAt(<Spending />, { role: 'viewer' }, '/spending');
      await screen.findAllByTestId('pace-row');
      expect(screen.queryByTestId('target-check')).toBeNull();
    });
  });

  it("the household's month, not the browser's: just after midnight it still shows the server's month", async () => {
    useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date('2026-11-01T02:00:00'));
    const fetchMock = stubFetch({ '/api/spending': { ...OCT, as_of: '2026-10-31', day: 31, days_left: 0 }, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByRole('heading', { level: 1, name: 'October 2026' })).toBeInTheDocument();
    expect(callsTo(fetchMock, 'GET', '/api/spending').map((c) => c.url)).toEqual(['/api/spending']);
    expect(screen.getByTestId('sp-line')).toHaveTextContent(/^Last day/);
    expect(screen.getByRole('button', { name: 'Next month' })).toBeDisabled();
  });

  it('a viewer sees no Set one and cannot sort from here', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, { role: 'viewer' }, '/spending');
    await screen.findByTestId('sp-total');
    expect(screen.queryByRole('link', { name: /Set one/ })).toBeNull();
    expect(screen.getByTestId('unsorted-row').tagName).toBe('DIV');
    expect(screen.queryByText('Sort them')).toBeNull();
  });

  it("money out and money in sit under the figure as one quiet line (Home's figures), none in a month with neither", async () => {
    const taxes = { ...OCT, head: { ...OCT.head, occasional_cents: 421_000, money_out_cents: 1_218_400, money_in_cents: 1_225_400 } };
    stubFetch({ '/api/spending': taxes, ...ACCOUNTS });
    const { unmount } = renderAt(<Spending />, {}, '/spending');
    const line = await screen.findByTestId('sp-in-out');
    expect(line).toHaveTextContent(/^\$12,184 out · \$12,254 in$/);
    expect(line).toHaveClass('muted');
    expect(line.querySelector('.money--in, .money--out')).toBeNull();
    unmount();
    const quiet = { ...OCT, head: { ...OCT.head, money_out_cents: 0, money_in_cents: 0 } };
    stubFetch({ '/api/spending': quiet, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    await screen.findByTestId('sp-total');
    expect(screen.queryByTestId('sp-in-out')).toBeNull();
  });

  it('names a payment made once in a while under the figure and in its own section, outside the plan', async () => {
    const taxes = { ...OCT, occasional: [{ category: 'taxes', kind: 'occasional' as const, spent_cents: 421_000, paid_on: '2026-10-20' }], head: { ...OCT.head, occasional_cents: 421_000, money_out_cents: 1_218_400 } };
    stubFetch({ '/api/spending': taxes, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByText('and $4,210 in Taxes, paid once in a while')).toBeInTheDocument();
    expect(screen.getByTestId('sp-total')).toHaveTextContent('$7,974 of $8,140');
    expect(screen.getByRole('heading', { level: 2, name: 'Paid once in a while' })).toBeInTheDocument();
    expect(screen.getByTestId('occasional-row')).toHaveTextContent('Paid Oct 20');
  });

  it('a month it cannot show says why and offers this month', async () => {
    stubFetch({ '/api/spending': () => reply({ error: 'Choose a month like 2026-10: this month or an earlier one.' }, 422), ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2030-01');
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a month like 2026-10');
    expect(backToThisMonth()).toHaveAttribute('href', '/b/ours/spending');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();   // asking again gets the same answer
  });

  it('a month before the book began is a plain line, not an error, with a way back to this month (ruling 22)', async () => {
    stubFetch({ '/api/spending': () => reply({ error: 'Spending has nothing to show before October 2024.' }, 404), ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2023-05');
    expect(await screen.findByText('Spending has nothing to show before October 2024.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1, name: 'May 2023' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).toBeNull();
    expect(backToThisMonth()).toHaveAttribute('href', '/b/ours/spending');
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  });

  it.each([500, 429, 409])('a failed call (%i) offers to try again', async (status) => {
    stubFetch({ '/api/spending': () => reply({ error: 'Something went wrong.' }, status), ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByRole('alert')).toHaveTextContent('Something went wrong.');
    expect(screen.getByRole('heading', { level: 1, name: 'Spending' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
    expect(backToThisMonth()).toBeNull();   // already on it
    expect(within(screen.getByRole('navigation', { name: 'Spending views' })).getByRole('link', { name: 'This month' })).toHaveAttribute('aria-current', 'page');
  });
});

describe('Spending with set-asides (11c)', () => {
  const oct = { ...OCT, set_aside: OCT_SECTION, head: { ...OCT.head, set_aside_cents: 154_400, spent_cents: 951_800, planned_cents: 968_400 } };
  const nov = { ...oct, month: '2026-11', set_aside: NOV_SECTION, head: { ...oct.head, paid_from_set_aside_cents: 421_000, occasional_cents: 0 }, occasional: [] };

  it('counts the monthly amount in the head and lists the summary row and the rows that need a look', async () => {
    stubFetch({ '/api/spending': oct, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    expect(await screen.findByTestId('sp-total')).toHaveTextContent('$9,518 of $9,684');
    expect(screen.getByTestId('sp-line')).toHaveTextContent(/Fixed costs \$4,583\s*·\s*Set aside \$1,544$/);
    expect(screen.getByRole('heading', { level: 2, name: 'Setting aside' })).toBeInTheDocument();
    expect(screen.getByText('$1,544 this month')).toBeInTheDocument();
    const sum = screen.getByTestId('sa-summary');
    expect(sum).toHaveTextContent('7 costs, set aside this month');
    expect(sum).toHaveTextContent('Property tax, Holidays, Car registration and 4 more · $14,592 a year, $20,200 in one-offs');
    expect(sum).toHaveAttribute('href', '/b/ours/spending/setasides');
    const look = screen.getAllByTestId('sa-look');
    expect(look).toHaveLength(2);
    expect(look[0]).toHaveTextContent('Property tax');
    expect(look[0]).toHaveTextContent('Due in 7 days · $110 short · House fund');
    expect(look[0]).toHaveAttribute('href', '/b/ours/spending/setasides/1');
    expect(look[0]).toHaveClass('is-soon');
    expect(look[1]).toHaveTextContent('Behind by $200 · $600 put away, $800 should be by now · Kids fund');
    expect(look[1]).toHaveClass('is-behind');
    expect(screen.queryByTestId('sa-paid-row')).toBeNull();
    expect(screen.queryByTestId('sp-set-aside-line')).toBeNull();
    expect(screen.getByText(/^Counted in the month's figure as if spent/)).toBeInTheDocument();
  });

  it('a month with a matched payment names it under the figure and lists it with an undo', async () => {
    const fetchMock = stubFetch({ '/api/spending?month=2026-11': nov, ...ACCOUNTS, 'DELETE /api/setasides/match/305': () => new Response(null, { status: 204 }) });
    renderAt(<Spending />, {}, '/spending?month=2026-11');
    expect(await screen.findByTestId('sp-set-aside-line')).toHaveTextContent('and $4,210 property tax, paid from Setting aside');
    expect(screen.getByRole('heading', { level: 2, name: 'Paid from Setting aside' })).toBeInTheDocument();
    expect(screen.getByText("Not against this month's targets")).toBeInTheDocument();
    const paid = screen.getByTestId('sa-paid-row');
    expect(paid).toHaveTextContent('County Tax Collector · Nov 1 · paid from Setting aside');
    expect(paid).toHaveTextContent('$4,210');
    expect(within(paid).getByRole('link', { name: 'Open the set-aside: Property tax' })).toHaveAttribute('href', '/b/ours/spending/setasides/1');
    expect(screen.getByTestId('sa-summary')).toHaveTextContent('Property tax paid Nov 1 · next: Holidays, December');
    expect(screen.queryByRole('heading', { level: 2, name: 'Paid once in a while' })).toBeNull();
    fireEvent.click(within(paid).getByRole('button', { name: 'Not this one? Property tax, County Tax Collector, Nov 1' }));
    await waitFor(() => expect(callsTo(fetchMock, 'DELETE', '/api/setasides/match/305')).toHaveLength(1));
  });

  it('a refused undo (a stopped set-aside) shows the server words', async () => {
    stubFetch({ '/api/spending?month=2026-11': nov, ...ACCOUNTS, 'DELETE /api/setasides/match/305': () => new Response(JSON.stringify({ error: 'That set-aside was stopped.' }), { status: 409, headers: { 'Content-Type': 'application/json' } }) });
    renderAt(<Spending />, {}, '/spending?month=2026-11');
    fireEvent.click(await screen.findByRole('button', { name: /^Not this one\?/ }));
    expect(await screen.findByText('That set-aside was stopped.')).toBeInTheDocument();
  });

  it('writes invalidate through invalidateSetAsides', async () => {
    stubFetch({ '/api/spending?month=2026-11': nov, ...ACCOUNTS, 'DELETE /api/setasides/match/305': () => new Response(null, { status: 204 }) });
    const { qc } = renderAt(<Spending />, {}, '/spending?month=2026-11');
    const spy = vi.spyOn(qc, 'invalidateQueries');
    fireEvent.click(await screen.findByRole('button', { name: /^Not this one\?/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ['spending'] }));
    for (const k of ['setasides', 'plan', 'transactions', 'summary']) expect(spy).toHaveBeenCalledWith({ queryKey: [k] });
  });

  it('a payment matched to a stopped set-aside has no undo', async () => {
    const stopped = { ...nov, set_aside: { ...NOV_SECTION, paid: [{ ...NOV_SECTION.paid[0], archived: true }] } };
    stubFetch({ '/api/spending?month=2026-11': stopped, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2026-11');
    expect(await screen.findByTestId('sa-paid-row')).toHaveTextContent('paid from Setting aside');
    expect(screen.queryByRole('button', { name: /Not this one/ })).toBeNull();
  });

  it('a late payment says so, and a viewer has no undo', async () => {
    const late = { ...nov, set_aside: { ...NOV_SECTION, paid: [{ ...NOV_SECTION.paid[0], posted_at: '2026-11-20', late: true }] } };
    stubFetch({ '/api/spending?month=2026-11': late, ...ACCOUNTS });
    renderAt(<Spending />, { role: 'viewer' }, '/spending?month=2026-11');
    expect(await screen.findByTestId('sa-paid-row')).toHaveTextContent('County Tax Collector · Nov 20, late · paid from Setting aside');
    expect(screen.queryByRole('button', { name: /Not this one/ })).toBeNull();
  });

  it('a month before the first set-aside shows no section and the head as before', async () => {
    stubFetch({ '/api/spending?month=2026-09': { ...SEP, set_aside: null }, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending?month=2026-09');
    expect(await screen.findByTestId('sp-total')).toHaveTextContent('$8,312 of $8,140');
    expect(screen.queryByRole('heading', { level: 2, name: 'Setting aside' })).toBeNull();
    expect(screen.getByTestId('sp-line').textContent).not.toMatch(/Set aside/);
    expect(screen.queryByTestId('sp-set-aside-line')).toBeNull();
    expect(screen.getByRole('navigation', { name: 'Spending views' })).toHaveTextContent('Setting aside');
  });

  it('with no set-asides the pill still leads to the list', async () => {
    stubFetch({ '/api/spending': OCT, ...ACCOUNTS });
    renderAt(<Spending />, {}, '/spending');
    const pills = await screen.findByRole('navigation', { name: 'Spending views' });
    expect(within(pills).getByRole('link', { name: 'Setting aside' })).toHaveAttribute('href', '/b/ours/spending/setasides');
    expect(screen.queryByRole('heading', { level: 2, name: 'Setting aside' })).toBeNull();
  });
});
