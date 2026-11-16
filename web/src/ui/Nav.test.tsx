import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { preloadFocus } from '../screens/review/focus/load';
import { Nav, NAV_ITEMS, navItems } from './Nav';

const count = (n: number) =>
  render(<MemoryRouter><Nav items={NAV_ITEMS} count={n} /></MemoryRouter>).container.querySelector('.nav__count')?.textContent ?? null;

describe('Nav review count', () => {
  it('is hidden at 0, exact up to 99, and 99+ above', () => {
    expect(count(0)).toBeNull();
    expect(count(99)).toBe('99');
    expect(count(438)).toBe('99+');
  });
});

describe('Nav tabs', () => {
  it('has six tabs in a household book: Home, Spending, Accounts, Ask, Plan, Review', () => {
    const { getAllByRole } = render(<MemoryRouter><Nav items={navItems('ours', 'household')} /></MemoryRouter>);
    const links = getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Home', 'Spending', 'Accounts', 'Ask', 'Plan', 'Review']);
    expect(links.map((a) => a.getAttribute('href'))).toEqual(
      ['/b/ours', '/b/ours/spending', '/b/ours/accounts', '/b/ours/ask', '/b/ours/plan', '/b/ours/review']);
  });
  it('has five tabs in a parent book: Home, Inventory, Care, Ask, Review', () => {
    const { getAllByRole } = render(<MemoryRouter><Nav items={navItems('mom', 'parent')} /></MemoryRouter>);
    expect(getAllByRole('link').map((a) => a.textContent)).toEqual(['Home', 'Inventory', 'Care', 'Ask', 'Review']);
  });
  it('renders the foot after the tabs', () => {
    const r = render(<MemoryRouter><Nav items={NAV_ITEMS} foot={<span>JH</span>} /></MemoryRouter>);
    expect(r.container.querySelector('.nav__foot')).toHaveTextContent('JH');
  });
});

describe('Nav active tab', () => {
  const current = (path: string) => {
    const r = render(<MemoryRouter initialEntries={[path]}><Nav items={NAV_ITEMS} /></MemoryRouter>);
    const out = r.getAllByRole('link').filter((a) => a.getAttribute('aria-current') === 'page' && a.classList.contains('active')).map((a) => a.textContent);
    r.unmount();
    return out;
  };
  it('marks Spending on its pages, and Plan on Taxes, which sits under Plan', () => {
    expect(current('/b/ours/spending')).toEqual(['Spending']);
    expect(current('/b/ours/spending/targets')).toEqual(['Spending']);
    expect(current('/b/ours/spending/setasides/3')).toEqual(['Spending']);
    expect(current('/b/ours/taxes')).toEqual(['Plan']);
  });
  it('marks one tab per screen', () => {
    expect(current('/b/ours')).toEqual(['Home']);
    expect(current('/b/ours/plan')).toEqual(['Plan']);
    for (const page of ['try', 'next', 'how']) expect(current(`/b/ours/plan/${page}`)).toEqual(['Plan']);   // plan subpages
    expect(current('/b/ours/accounts')).toEqual(['Accounts']);
    expect(current('/b/ours/accounts/12')).toEqual(['Accounts']);
    expect(current('/b/ours/transactions')).toEqual(['Accounts']);    // All transactions belongs to Accounts
    expect(current('/b/ours/ask/history')).toEqual(['Ask']);
    expect(current('/b/ours/settings/members')).toEqual([]);          // Settings is under the initials, not a tab
    expect(current('/b/ours/accountsx')).toEqual([]);
  });
  it("marks Inventory on a parent book's All transactions", () => {
    const r = render(<MemoryRouter initialEntries={['/b/mom/transactions']}><Nav items={navItems('mom', 'parent')} /></MemoryRouter>);
    expect(r.getByRole('link', { name: 'Inventory' })).toHaveAttribute('aria-current', 'page');
  });
});

describe("Home's flag count (decision 5)", () => {
  const home = (flags?: { count: number; urgent: boolean }) =>
    render(<MemoryRouter><Nav items={navItems('margaret-ellis', 'parent')} flags={flags} /></MemoryRouter>)
      .container.querySelector('a') as HTMLElement;
  it('shows open plus Still checking, red while any is urgent and plum otherwise', () => {
    const urgent = home({ count: 6, urgent: true });
    expect(urgent).toHaveAccessibleName('Home, 6 to look into');
    expect(urgent.querySelector('.nav__count')).toHaveClass('nav__count--urgent');
    expect(urgent.querySelector('.nav__count')?.textContent).toBe('6');
  });
  it('is plum when nothing urgent is open, and hidden at 0', () => {
    expect(home({ count: 2, urgent: false }).querySelector('.nav__count')).not.toHaveClass('nav__count--urgent');
    expect(home({ count: 0, urgent: false }).querySelector('.nav__count')).toBeNull();
    expect(home(undefined).querySelector('.nav__count')).toBeNull();
  });
});

describe('The brand at the top of the rail', () => {
  it("links the mark and \"Steward\" to the book's Home, above the book switcher", () => {
    const r = render(<MemoryRouter><Nav items={navItems('ours', 'household')} layout="rail" home="/b/ours" header={<span>Ours</span>} /></MemoryRouter>);
    const brand = r.getByRole('link', { name: 'Steward' });
    expect(brand).toHaveAttribute('href', '/b/ours');
    expect(brand).toHaveClass('nav__brand');
    const mark = brand.querySelector('svg.brand-mark');
    expect(mark).toHaveAttribute('width', '28');
    expect(mark).toHaveAttribute('aria-hidden', 'true');
    expect(mark).toHaveAttribute('data-size', 'medium');
    expect(r.getByRole('navigation').firstElementChild).toBe(brand);
    expect(brand.nextElementSibling).toHaveClass('nav__header');
  });
  it('is in the auto layout too, where the CSS shows it from 900 px', () => {
    const r = render(<MemoryRouter><Nav items={NAV_ITEMS} home="/b/ours" /></MemoryRouter>);
    expect(r.getByRole('link', { name: 'Steward' })).toHaveClass('nav__brand');
  });
  it('is not in the phone bar, which has no room for it', () => {
    const r = render(<MemoryRouter><Nav items={NAV_ITEMS} layout="bar" home="/b/ours" /></MemoryRouter>);
    expect(r.queryByRole('link', { name: 'Steward' })).toBeNull();
    expect(r.container.querySelector('.brand-mark')).toBeNull();
  });
  it('is left out without a Home to link to', () => {
    const r = render(<MemoryRouter><Nav items={NAV_ITEMS} layout="rail" /></MemoryRouter>);
    expect(r.queryByRole('link', { name: 'Steward' })).toBeNull();
  });
});

describe('Nav preloads Review focus (review focus P26)', () => {
  it('the Review tab preloads the Focus chunk on hover or focus', () => {
    expect(navItems('ours', 'household').find((i) => i.label === 'Review')?.preload).toBe(preloadFocus);
    expect(navItems('mom', 'parent').find((i) => i.label === 'Review')?.preload).toBe(preloadFocus);
  });
});
