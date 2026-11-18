import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { createMemoryRouter, Link, Navigate, RouterProvider, useNavigate, useParams, useSearchParams, type RouteObject } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useFocusOnMount } from '../lib/focus';
import { routes } from '../routes';
import { useItemTitle } from './itemTitle';
import { RouteFrame } from './RouteFrame';

afterEach(() => { vi.restoreAllMocks(); });

function List() {
  const [, setSp] = useSearchParams();
  return (
    <main>
      <h1>Transactions</h1>
      <Link to="/row">Open a row</Link>
      <button type="button" onClick={() => setSp({ q: 'groc' }, { replace: true, preventScrollReset: true })}>Filter</button>
    </main>
  );
}
const table: RouteObject[] = [{ element: <RouteFrame />, children: [
  { path: '/', element: <List /> },
  { path: '/row', element: <main><h1>A row</h1></main> },
] }];

let y = 0;
function mount() {
  vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => y);
  const to = vi.spyOn(window, 'scrollTo').mockImplementation(((_x: number, top: number) => { y = top; }) as typeof window.scrollTo);
  const router = createMemoryRouter(table, { initialEntries: ['/'] });
  render(<RouterProvider router={router} />);
  return { router, to };
}

describe('a page change and scroll (WEB-2)', () => {
  it('a new page opens at its top, and Back returns to where the list was', async () => {
    const { router, to } = mount();
    y = 1800;                                                  // scrolled far down the list
    await act(async () => { screen.getByRole('link', { name: 'Open a row' }).click(); });
    expect(await screen.findByRole('heading', { name: 'A row' })).toBeInTheDocument();
    expect(to).toHaveBeenLastCalledWith(0, 0);
    expect(y).toBe(0);
    await act(async () => { await router.navigate(-1); });
    expect(await screen.findByRole('heading', { name: 'Transactions' })).toBeInTheDocument();
    expect(to).toHaveBeenLastCalledWith(0, 1800);
  });

  it('a filter on the same page keeps the list where it is', async () => {
    const { to } = mount();
    y = 900;
    to.mockClear();
    await act(async () => { screen.getByRole('button', { name: 'Filter' }).click(); });
    expect(to).not.toHaveBeenCalled();
    expect(y).toBe(900);
  });

  it('every route sits under RouteFrame', () => {
    expect(routes[0].children!.length).toBeGreaterThan(5);
    expect(routes).toHaveLength(1);
    expect(routes[0].path).toBeUndefined();
    expect((routes[0].element as { type?: unknown }).type).toBe(RouteFrame);
  });
});

describe('a page change says where you are (WEB-3)', () => {
  function Step() {
    const ref = useFocusOnMount<HTMLHeadingElement>();
    return <main><h1>Profile</h1><h2 ref={ref} tabIndex={-1}>Your pay</h2></main>;
  }
  function Lazy() {
    const [ready, setReady] = useState(false);
    return <main>{ready ? <h1>Help</h1> : <button type="button" onClick={() => setReady(true)}>Load</button>}</main>;
  }
  const pages: RouteObject[] = [{ element: <RouteFrame />, children: [
    { path: '/', element: <main><h1>Home</h1><Link to="/spending">Spending</Link></main>, handle: { title: 'Home' } },
    { path: '/spending', element: <main><h1>October</h1></main>, handle: { title: 'Spending' } },
    { path: '/step', element: <Step />, handle: { title: 'Your pay' } },
    { path: '/help', element: <Lazy />, handle: { title: 'Help' } },
  ] }];
  const open = (at = '/') => {
    const router = createMemoryRouter(pages, { initialEntries: [at] });
    render(<RouterProvider router={router} />);
    return router;
  };
  /** The person's first input: the launch is over. */
  const person = () => fireEvent.pointerDown(document.body);

  it('the first page gets its title and keeps focus where the browser put it', () => {
    open();
    expect(document.title).toBe('Home · Steward');
    expect(document.body).toHaveFocus();
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();
  });

  it("a new page: the tab's title, focus on its h1 and its name said politely", async () => {
    const router = open();
    screen.getByRole('link', { name: 'Spending' }).focus();
    person();
    await act(async () => { await router.navigate('/spending'); });
    expect(document.title).toBe('Spending · Steward');
    expect(screen.getByRole('heading', { name: 'October' })).toHaveFocus();
    expect(screen.getByTestId('live-said')).toHaveTextContent('Spending');
  });

  it('a page that places focus itself keeps it', async () => {
    const router = open();
    person();
    await act(async () => { await router.navigate('/step'); });
    expect(screen.getByRole('heading', { name: 'Your pay' })).toHaveFocus();
  });

  it("a lazy page's h1 that arrives later still gets focus", async () => {
    const router = open();
    person();
    await act(async () => { await router.navigate('/help'); });
    expect(document.title).toBe('Help · Steward');
    const load = screen.getByRole('button', { name: 'Load' });
    act(() => { load.click(); });                 // the click focuses nothing in jsdom; the page's h1 arrives
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Help' })).toHaveFocus());
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();      // the h1 says "Help" already
  });

  it('a page whose h1 says its name is not said twice', async () => {
    const router = open('/spending');
    person();
    await act(async () => { await router.navigate('/'); });
    expect(screen.getByRole('heading', { name: 'Home' })).toHaveFocus();
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();
  });

  it('a launch at / that redirects (ToBook, sign-in, the welcome) moves nothing and says nothing (16i review I-3)', async () => {
    const launch: RouteObject[] = [{ element: <RouteFrame />, children: [
      { path: '/', element: <Navigate to="/b/ours" replace /> },
      { path: '/b/ours', element: <Navigate to="/b/ours/welcome" replace />, handle: { title: 'Home' } },
      { path: '/b/ours/welcome', element: <main><h1>Good morning</h1><Link to="/b/ours/spending">Spending</Link></main>, handle: { title: 'Welcome' } },
      { path: '/b/ours/spending', element: <main><h1>October</h1></main>, handle: { title: 'Spending' } },
    ] }];
    const router = createMemoryRouter(launch, { initialEntries: ['/'] });
    render(<RouterProvider router={router} />);
    expect(await screen.findByRole('heading', { name: 'Good morning' })).toBeInTheDocument();
    expect(document.title).toBe('Welcome · Steward');
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();
    expect(document.body).toHaveFocus();
    fireEvent.click(screen.getByRole('link', { name: 'Spending' }));          // the person's first page change
    expect(await screen.findByRole('heading', { name: 'October' })).toHaveFocus();
    expect(screen.getByTestId('live-said')).toHaveTextContent('Spending');
    expect(router.state.location.pathname).toBe('/b/ours/spending');
  });

  it('signing in after a launch redirect to /login is a page change, though it replaces the address (16i re-review R-3)', async () => {
    function LoginPage() {
      const nav = useNavigate();
      return <main><h1>Sign in</h1><button type="button" onClick={() => nav('/b/ours', { replace: true })}>Sign in</button></main>;
    }
    const table: RouteObject[] = [{ element: <RouteFrame />, children: [
      { path: '/', element: <Navigate to="/login" replace /> },
      { path: '/login', element: <LoginPage />, handle: { title: 'Sign in' } },
      { path: '/b/ours', element: <main><h1>Good morning</h1></main>, handle: { title: 'Home' } },
    ] }];
    const router = createMemoryRouter(table, { initialEntries: ['/'] });
    render(<RouterProvider router={router} />);
    const button = await screen.findByRole('button', { name: 'Sign in' });
    expect(screen.getByTestId('live-said')).toBeEmptyDOMElement();      // the launch redirect said nothing
    button.focus();
    await act(async () => { button.click(); });                          // the person signs in: a replace
    expect(await screen.findByRole('heading', { name: 'Good morning' })).toHaveFocus();
    expect(screen.getByTestId('live-said')).toHaveTextContent('Home');
    expect(router.state.historyAction).toBe('REPLACE');
  });
});

describe("a page for one item is titled by the item's name (issue #29)", () => {
  const NAMES: Record<string, string> = { 1: 'Joint checking', 2: 'Savings' };
  /** An item page whose name arrives after the page has opened, as a query's would; another id loads again. */
  function Item() {
    const { id = '' } = useParams();
    const [loaded, setLoaded] = useState<string[]>([]);
    const name = loaded.includes(id) ? NAMES[id] : undefined;
    useItemTitle(name);
    return <main><h1>{name ?? 'Loading'}</h1><button type="button" onClick={() => setLoaded((l) => [...l, id])}>Load</button></main>;
  }
  const pages: RouteObject[] = [{ element: <RouteFrame />, children: [
    { path: '/list', element: <main><h1>Items</h1></main>, handle: { title: 'Items' } },
    { path: '/items/:id', element: <Item />, handle: { title: 'Item' } },
  ] }];

  it('keeps the fixed noun while it loads, takes the name once loaded, and lets go of it on the next page', async () => {
    const router = createMemoryRouter(pages, { initialEntries: ['/items/1'] });
    render(<RouterProvider router={router} />);
    expect(document.title).toBe('Item · Steward');
    act(() => { screen.getByRole('button', { name: 'Load' }).click(); });
    expect(document.title).toBe('Joint checking · Steward');
    // Another item on the same route: the screen stays mounted, and the title is the noun again until it loads.
    await act(async () => { await router.navigate('/items/2'); });
    expect(document.title).toBe('Item · Steward');
    act(() => { screen.getByRole('button', { name: 'Load' }).click(); });
    expect(document.title).toBe('Savings · Steward');
    await act(async () => { await router.navigate('/list'); });
    expect(document.title).toBe('Items · Steward');
  });
});
