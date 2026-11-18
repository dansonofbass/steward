import type { QueryKey } from '@tanstack/react-query';
import { Suspense, type ReactNode } from 'react';
import { lazyScreen } from './lib/lazyScreen';
import { createBrowserRouter, Navigate, type RouteObject } from 'react-router-dom';
import { GROWTH_OPTIONS, GROWTH_PATH } from './api/growth';
import { warmHome } from './api/home';
import { RequireAuth } from './auth/RequireAuth';
import { useIsHousehold } from './book/BookContext';
import { BookScope, HouseholdOnly, ParentOnly } from './book/BookScope';
import { RouteFrame } from './frame/RouteFrame';
import { ToBook } from './book/ToBook';
import { ToProfile } from './book/ToProfile';
import AccountPage from './screens/accounts/AccountPage';
import Accounts from './screens/accounts/Accounts';
import Home, { preloadHomeParts } from './screens/Home';
import Login from './screens/Login';
import { settingsTitle } from './screens/settings/sections';
import { T } from './lib/routeTitles';
import { ToSpending } from './screens/spending/ToSpending';
import Transactions from './screens/Transactions';
import type { Want, Warm } from './warm';

// Review (review focus P26 fallback, JR: "On demand is fine"): its own chunk, so the initial bundle stays under its limit.
const Design = lazyScreen(() => import('./screens/Design'));
// The first run's page (release spec 2026-11-05, section 6): before anyone can sign in, so outside RequireAuth.
const Setup = lazyScreen(() => import('./screens/setup/Setup'));
const Welcome = lazyScreen(() => import('./screens/welcome/Welcome'));
const Help = lazyScreen(() => import('./screens/you/Help'));
const About = lazyScreen(() => import('./screens/you/About'));
const Review = lazyScreen(() => import('./screens/Review'));
const Settings = lazyScreen(() => import('./screens/Settings'));
// WEB-19: screens opened rarely, each its own chunk, started as the address is reached (codeOf, below).
const SignInDevices = lazyScreen(() => import('./screens/you/SignInDevices'));
const AppearancePage = lazyScreen(() => import('./screens/you/AppearancePage'));
const Invite = lazyScreen(() => import('./screens/Invite'));
const Forgot = lazyScreen(() => import('./screens/Forgot'));
const Reset = lazyScreen(() => import('./screens/Reset'));
const Plan = lazyScreen(() => import('./screens/Plan'));
// Plan subpages: the four pages come from the same module as the layout, so they share its chunk.
const planPage = (name: 'OverviewRoute' | 'TryRoute' | 'NextRoute' | 'HowRoute') =>
  lazyScreen(() => import('./screens/Plan').then((m) => ({ default: m[name] })));
const PlanOverview = planPage('OverviewRoute');
const PlanTry = planPage('TryRoute');
const PlanNext = planPage('NextRoute');
const PlanHow = planPage('HowRoute');
const Business = lazyScreen(() => import('./screens/business/Business'));
const Care = lazyScreen(() => import('./screens/care/Care'));
const Taxes = lazyScreen(() => import('./screens/taxes/Taxes'));
const Profile = lazyScreen(() => import('./screens/profile/Profile'));
const Spending = lazyScreen(() => import('./screens/spending/Spending'));
const Trends = lazyScreen(() => import('./screens/spending/Trends'));
const Targets = lazyScreen(() => import('./screens/spending/Targets'));
const SetAsides = lazyScreen(() => import('./screens/spending/setasides/SetAsides'));
const AddSetAside = lazyScreen(() => import('./screens/spending/setasides/AddSetAside'));
const SetAsidePage = lazyScreen(() => import('./screens/spending/setasides/SetAside'));
const Category = lazyScreen(() => import('./screens/spending/Category'));
const Reimbursements = lazyScreen(() => import('./screens/reimburse/Reimbursements'));
const TripPage = lazyScreen(() => import('./screens/reimburse/Trip'));
const InventoryList = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.InventoryList })));
const ItemPage = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.ItemPage })));
const ItemForm = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.ItemForm })));
const AttachFile = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.AttachFile })));
const TaxForm = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.TaxForm })));
const Suggestions = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.Suggestions })));
const LookInto = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.LookInto })));
const FlagPage = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.FlagPage })));
const loading = <div className="screen" aria-busy="true" />;
const parent = (el: ReactNode) => <ParentOnly><Suspense fallback={loading}>{el}</Suspense></ParentOnly>;
const household = (el: ReactNode) => <HouseholdOnly><Suspense fallback={loading}>{el}</Suspense></HouseholdOnly>;
const ParentHome = lazyScreen(() => import('./screens/inventory/Inventory').then((m) => ({ default: m.ParentHome })));

// Phase 18: what each screen asks for as it opens, started by warm.ts as the address is reached, beside /me. Keys,
// paths and options are the screens' own hooks' (api/hooks.ts, screens/import), so the hooks find them in flight.
const want = (key: QueryKey, path: string, options?: Want['options']): Want => ({ key, path, options });
const ACCOUNTS = want(['accounts'], '/api/accounts');
const spendingMonth = (month: string | null) =>
  want(['spending', month ?? 'now'], month ? `/api/spending?month=${encodeURIComponent(month)}` : '/api/spending');
const BOOK_WARM: Warm = { wants: () => [want(['review'], '/api/review', { staleTime: 60_000 })] };
const GROWTH = want(['growth'], GROWTH_PATH, GROWTH_OPTIONS);
const HOME_WARM: Warm = { code: () => preloadHomeParts(), run: (at) => warmHome(at.key), wants: () => [ACCOUNTS, GROWTH] };
const SPENDING_WARM: Warm = { code: () => Spending.preload(), wants: (_p, q) => [spendingMonth(q.get('month')), ACCOUNTS] };
const REVIEW_WARM: Warm = { code: () => Review.preload(), wants: () => [want(['usual'], '/api/categorize/usual', { staleTime: 300_000 })] };
const PLAN_WARM: Warm = {
  code: () => Plan.preload(),
  wants: () => [want(['plan'], '/api/plan', { retry: false }), want(['facts'], '/api/facts'), want(['next-dollar'], '/api/next-dollar')],
};
// WEB-19: Settings and its sections, and the screens opened rarely, are their own chunks, started as the address is
// reached, beside /me.
const codeOf = (screen: { preload: () => Promise<unknown> }): Warm => ({ code: () => screen.preload() });
const SETTINGS_WARM: Warm = codeOf(Settings);
const IMPORT_WARM: Warm = {
  code: (p) => Promise.all([Settings.preload(), p.section === 'import' ? import('./screens/import/Import') : undefined]),
  wants: (p) => (p.section === 'import' ? [ACCOUNTS, want(['batches'], '/api/import/batches'), want(['import-layouts'], '/api/import/layouts')] : []),
};

/** A household's Home as before; a parent book's Home is its overview (design pass decision 2). */
function BookHome() {
  return useIsHousehold() ? <Home /> : <Suspense fallback={loading}><ParentHome /></Suspense>;
}

// Each screen's handle names it (WEB-3, lib/routeTitles.ts): RouteFrame titles the page and focuses its heading.
const SCREENS: RouteObject[] = [
  { index: true, element: <BookHome />, handle: { title: T.home, warm: HOME_WARM } },
  { path: 'spending', element: household(<Spending />), handle: { title: T.spending, warm: SPENDING_WARM } },
  { path: 'spending/trends', element: household(<Trends />), handle: { title: T.trends } },
  { path: 'spending/targets', element: household(<Targets />), handle: { title: T.targets } },
  { path: 'spending/setasides', element: household(<SetAsides />), handle: { title: T.setAsides } },
  { path: 'spending/setasides/new', element: household(<AddSetAside />), handle: { title: T.newSetAside } },
  { path: 'spending/setasides/:id', element: household(<SetAsidePage />), handle: { title: T.setAside } },
  { path: 'spending/reimbursements', element: household(<Reimbursements />), handle: { title: T.reimbursements } },
  { path: 'spending/reimbursements/trips/:id', element: household(<TripPage />), handle: { title: T.trip } },
  { path: 'spending/:category', element: household(<Category />), handle: { title: T.category } },
  // Cash flow became Spending (decision 2): an old address keeps its ?month=.
  { path: 'cashflow', element: <HouseholdOnly><ToSpending /></HouseholdOnly> },
  { path: 'accounts', element: <HouseholdOnly to="/inventory"><Accounts /></HouseholdOnly>, handle: { title: T.accounts } },
  { path: 'accounts/:id', element: <HouseholdOnly to="/inventory"><AccountPage /></HouseholdOnly>, handle: { title: T.account } },
  { path: 'transactions', element: <Transactions />, handle: { title: T.transactions } },
  { path: 'review', element: <Suspense fallback={loading}><Review /></Suspense>, handle: { title: T.review, warm: REVIEW_WARM } },
  { path: 'plan', element: <HouseholdOnly><Suspense fallback={loading}><Plan /></Suspense></HouseholdOnly>, handle: { title: T.plan, warm: PLAN_WARM }, children: [
    { index: true, element: <PlanOverview />, handle: { title: T.plan } },
    { path: 'try', element: <PlanTry />, handle: { title: T.tryChanges } },
    { path: 'next', element: <PlanNext />, handle: { title: T.nextDollar } },
    { path: 'how', element: <PlanHow />, handle: { title: T.howItWorks } },
  ] },
  { path: 'business', element: <HouseholdOnly><Suspense fallback={loading}><Business /></Suspense></HouseholdOnly>, handle: { title: T.business } },
  { path: 'taxes', element: <HouseholdOnly><Suspense fallback={loading}><Taxes /></Suspense></HouseholdOnly>, handle: { title: T.taxes } },
  { path: 'inventory', element: parent(<InventoryList />), handle: { title: T.inventory } },
  { path: 'inventory/new', element: parent(<ItemForm />), handle: { title: T.newItem } },
  { path: 'inventory/suggestions', element: parent(<Suggestions />), handle: { title: T.suggestions } },
  { path: 'inventory/tax-form', element: parent(<TaxForm />), handle: { title: T.taxForm } },
  { path: 'inventory/:id', element: parent(<ItemPage />), handle: { title: T.item } },
  { path: 'inventory/:id/edit', element: parent(<ItemForm />), handle: { title: T.editItem } },
  { path: 'inventory/:id/attach', element: parent(<AttachFile />), handle: { title: T.attach } },
  { path: 'care', element: parent(<Care />), handle: { title: T.care } },
  { path: 'look-into', element: parent(<LookInto />), handle: { title: T.lookInto } },
  { path: 'look-into/:id', element: parent(<FlagPage />), handle: { title: T.flag } },
  // Profile (profile spec): household books only; the section and step are the Profile chunk's.
  { path: 'profile', element: household(<Profile />), handle: { title: T.profile } },
  { path: 'profile/:section', element: household(<Profile />), handle: { title: T.profileSection } },
  { path: 'profile/:section/:step', element: household(<Profile />), handle: { title: T.profileStep } },
  // Set up Steward is Profile (P2): the old addresses keep their step and ?from=.
  { path: 'setup', element: <ToProfile /> },
  { path: 'setup/:step', element: <ToProfile /> },
  { path: 'you/devices', element: <Suspense fallback={loading}><SignInDevices /></Suspense>, handle: { title: T.devices, warm: codeOf(SignInDevices) } },
  { path: 'you/appearance', element: <Suspense fallback={loading}><AppearancePage /></Suspense>, handle: { title: T.appearance, warm: codeOf(AppearancePage) } },
  { path: 'you/help', element: <Suspense fallback={loading}><Help /></Suspense>, handle: { title: T.help } },
  { path: 'you/about', element: <Suspense fallback={loading}><About /></Suspense>, handle: { title: T.about } },
  // The welcome (guided setup spec 2): BookScope sends a person with an unmarked one here from Home.
  { path: 'welcome', element: <Suspense fallback={loading}><Welcome /></Suspense>, handle: { title: T.welcome } },
  { path: 'settings', element: <Suspense fallback={loading}><Settings /></Suspense>, handle: { title: T.settings, warm: SETTINGS_WARM } },
  { path: 'settings/:section', element: <Suspense fallback={loading}><Settings /></Suspense>, handle: { title: settingsTitle, warm: IMPORT_WARM } },
  { path: 'settings/:section/:step', element: <Suspense fallback={loading}><Settings /></Suspense>, handle: { title: settingsTitle, warm: SETTINGS_WARM } },
];

const Ask = lazyScreen(() => import('./screens/chat/Ask'));
const BOOK_SCREENS: RouteObject[] = [...SCREENS, { path: 'ask/*', element: <Suspense fallback={loading}><Ask /></Suspense>, handle: { title: T.ask } }];

// Addresses from before books: the same screen in the last-used book (spec 2.4).
const OLD = ['/', '/cashflow', '/spending', '/spending/*', '/transactions', '/review', '/plan', '/plan/*', '/settings', '/settings/*','/profile', '/profile/*', '/accounts', '/accounts/*', '/you/*', '/taxes', '/ask', '/ask/*'];

/** The whole route list; exported so a test can mount it in a memory router. RouteFrame, a layout with no path, holds
 *  what every page change does (scroll, title, focus). */
export const routes: RouteObject[] = [{ element: <RouteFrame />, children: [
  { path: '/login', element: <Login />, handle: { title: T.login } },
  { path: '/forgot', element: <Suspense fallback={loading}><Forgot /></Suspense>, handle: { title: T.forgot, warm: codeOf(Forgot) } },
  { path: '/reset', element: <Suspense fallback={loading}><Reset /></Suspense>, handle: { title: T.reset, warm: codeOf(Reset) } },
  { path: '/design', element: <Design />, handle: { title: T.design } },
  { path: '/setup', element: <Suspense fallback={loading}><Setup /></Suspense>, handle: { title: T.setup } },
  // The old pre-books Set up Steward addresses (/setup/{step}) were Profile's; with /setup the first run's, they go Home.
  { path: '/setup/*', element: <Navigate to="/" replace /> },
  {
    element: <RequireAuth />,
    children: [
      { path: '/b/:slug', element: <BookScope />, handle: { warm: BOOK_WARM }, children: BOOK_SCREENS },
      // An invitation link: signed out goes to sign-in and comes back here (RequireAuth keeps the address).
      { path: '/invite', element: <Suspense fallback={loading}><Invite /></Suspense>, handle: { title: T.invite, warm: codeOf(Invite) } },
      ...OLD.map((path) => ({ path, element: <ToBook /> })),
    ],
  },
] }];

export const router = createBrowserRouter(routes);
