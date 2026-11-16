import type { APIRequestContext } from '@playwright/test';

// Every screen in the app, one entry per screen (not per route pattern), for the axe check (axe.spec.ts, claim T7) and
// the release gate's screenshots. src/routes.screens.test.ts fails when a route in routes.tsx has no entry here.
// Read by Vitest as well as Playwright, so nothing here may import a runtime module.

/** One screen to open. `route` is the routes.tsx pattern it covers, with its parents' paths joined on. `url` is
 *  what the browser opens: ids are the demo vault's (server.sh's seeds, plus addDemoRecords). `heading` must be on
 *  screen once it has opened, so the check never passes on a page that didn't load. */
export type Screen = { name: string; route: string; url: string; server: 'demo' | 'empty'; signedIn: boolean; heading: string | RegExp };

/** The demo household's book and one of the seeded parent books (both projects open the desktop one: nothing here writes). */
const OURS = '/b/ours';
const PARENT_SLUG = 'margaret-ellis-seed-desktop';
const PARENT = `/b/${PARENT_SLUG}`;
const B = '/b/:slug';

/** The set-aside and the trip that addDemoRecords adds: the seeds have neither, and each is the first of its kind. */
const SET_ASIDE_ID = 1;
const TRIP_ID = 1;

const demo = (name: string, route: string, url: string, heading: string | RegExp): Screen =>
  ({ name, route, url, server: 'demo', signedIn: true, heading });
const signedOut = (name: string, route: string, heading: string | RegExp): Screen =>
  ({ name, route, url: route, server: 'demo', signedIn: false, heading });

const PROFILE_SECTIONS = [
  ['you', 'You and your partner', 'you'], ['kids', 'Kids and college', 'kids'], ['home', 'Home and cars', 'own'],
  ['benefits', 'Social Security and Medicare', 'ss'], ['banks', 'Banks and accounts', 'link'],
] as const;

const HOUSEHOLD_SETTINGS = [
  ['ready', 'Get Steward ready'], ['members', 'Book members'], ['book', 'This book'], ['books', 'Books'],
  ['banks', 'Banks and accounts'], ['import', 'Import'], ['rules', 'Category rules'], ['business', 'Business type'],
  ['chat', 'Chat'], ['log', 'Log'], ['export', /^Export/],
] as const;
const PARENT_SETTINGS = [['watching', 'Watching'], ['changes', 'Change record'], ['dismissed', 'Dismissed suggestions']] as const;

export const SCREENS: Screen[] = [
  // Signed out. /reset and /setup without a token show their own no-link states.
  signedOut('login', '/login', 'Steward'),
  signedOut('forgot', '/forgot', 'Forgot your password?'),
  signedOut('reset', '/reset', 'Change password'),
  signedOut('design', '/design', 'Design'),
  signedOut('setup', '/setup', 'Set up Steward'),
  // An invitation link sits behind sign-in (routes.tsx); a made-up token shows its no-longer-good state.
  demo('invite', '/invite', '/invite?token=not-a-real-invite', 'Invitation'),

  // The household book.
  demo('home', B, OURS, 'Accounts'),
  demo('spending', `${B}/spending`, `${OURS}/spending`, /^[A-Z][a-z]+ \d{4}$/),
  demo('spending-trends', `${B}/spending/trends`, `${OURS}/spending/trends`, 'Spending over time'),
  demo('spending-targets', `${B}/spending/targets`, `${OURS}/spending/targets`, 'Set targets'),
  demo('setasides', `${B}/spending/setasides`, `${OURS}/spending/setasides`, 'Setting aside'),
  demo('setaside-new', `${B}/spending/setasides/new`, `${OURS}/spending/setasides/new`, 'Add a set-aside'),
  demo('setaside', `${B}/spending/setasides/:id`, `${OURS}/spending/setasides/${SET_ASIDE_ID}`, 'Water heater'),
  demo('reimbursements', `${B}/spending/reimbursements`, `${OURS}/spending/reimbursements`, 'Reimbursements'),
  demo('trip', `${B}/spending/reimbursements/trips/:id`, `${OURS}/spending/reimbursements/trips/${TRIP_ID}`, 'Denver trip'),
  demo('spending-category', `${B}/spending/:category`, `${OURS}/spending/dining`, /^Eating out · /i),
  demo('accounts', `${B}/accounts`, `${OURS}/accounts`, 'Accounts'),
  demo('account', `${B}/accounts/:id`, `${OURS}/accounts/1`, 'Checking'),
  demo('transactions', `${B}/transactions`, `${OURS}/transactions`, 'All transactions'),
  demo('review', `${B}/review`, `${OURS}/review`, 'Review'),
  demo('plan', `${B}/plan`, `${OURS}/plan`, 'What would help most'),
  demo('plan-try', `${B}/plan/try`, `${OURS}/plan/try`, /^What would change it/),
  demo('plan-next', `${B}/plan/next`, `${OURS}/plan/next`, 'Next dollar'),
  demo('plan-how', `${B}/plan/how`, `${OURS}/plan/how`, 'Where your numbers come from'),
  demo('business', `${B}/business`, `${OURS}/business`, 'Business'),
  demo('taxes', `${B}/taxes`, `${OURS}/taxes`, 'Taxes'),
  demo('profile', `${B}/profile`, `${OURS}/profile`, 'Profile'),
  ...PROFILE_SECTIONS.map(([key, title]) => demo(`profile-${key}`, `${B}/profile/:section`, `${OURS}/profile/${key}`, title)),
  // Each guided flow's first step.
  ...PROFILE_SECTIONS.map(([key, title, step]) => demo(`profile-${key}-${step}`, `${B}/profile/:section/:step`, `${OURS}/profile/${key}/${step}`, title)),
  demo('devices', `${B}/you/devices`, `${OURS}/you/devices`, 'Sign-in and devices'),
  demo('appearance', `${B}/you/appearance`, `${OURS}/you/appearance`, 'Appearance'),
  demo('help', `${B}/you/help`, `${OURS}/you/help`, 'Help'),
  demo('about', `${B}/you/about`, `${OURS}/you/about`, 'About Steward'),
  demo('settings', `${B}/settings`, `${OURS}/settings`, 'Settings for Ours'),
  ...HOUSEHOLD_SETTINGS.map(([key, heading]) => demo(`settings-${key}`, `${B}/settings/:section`, `${OURS}/settings/${key}`, heading)),
  demo('settings-book-details', `${B}/settings/:section/:step`, `${OURS}/settings/books/ours`, 'Ours'),
  demo('settings-chat-sent', `${B}/settings/:section/:step`, `${OURS}/settings/chat/sent`, 'Everything sent so far'),
  demo('ask', `${B}/ask/*`, `${OURS}/ask`, 'Ask about Ours'),

  // The parent book.
  demo('parent-home', B, PARENT, 'Recent changes'),
  demo('inventory', `${B}/inventory`, `${PARENT}/inventory`, 'Inventory'),
  demo('inventory-new', `${B}/inventory/new`, `${PARENT}/inventory/new`, 'Add an item'),
  demo('inventory-suggestions', `${B}/inventory/suggestions`, `${PARENT}/inventory/suggestions`, /^Is this one of /),
  demo('inventory-tax-form', `${B}/inventory/tax-form`, `${PARENT}/inventory/tax-form`, 'Type in a tax form'),
  demo('inventory-item', `${B}/inventory/:id`, `${PARENT}/inventory/1`, 'Joint checking'),
  demo('inventory-edit', `${B}/inventory/:id/edit`, `${PARENT}/inventory/1/edit`, 'Edit Joint checking'),
  demo('inventory-attach', `${B}/inventory/:id/attach`, `${PARENT}/inventory/1/attach`, 'Attach a file'),
  demo('care', `${B}/care`, `${PARENT}/care`, 'Care'),
  demo('look-into', `${B}/look-into`, `${PARENT}/look-into`, 'Look into'),
  // Flag ids follow the order the replayed morning runs raised them (seed_watching), which moves with the date, so
  // the check waits for the heading every flag page has, not one flag's title.
  demo('flag', `${B}/look-into/:id`, `${PARENT}/look-into/2`, 'Why it was flagged'),
  ...PARENT_SETTINGS.map(([key, heading]) => demo(`parent-settings-${key}`, `${B}/settings/:section`, `${PARENT}/settings/${key}`, heading)),
  demo('parent-settings-known', `${B}/settings/:section/:step`, `${PARENT}/settings/watching/known`, /^Known payees/),

  // The first run's welcome, on the empty household, asked for again (alex has seen it).
  { name: 'welcome', route: `${B}/welcome`, url: `${OURS}/welcome?again=1`, server: 'empty', signedIn: true, heading: 'Steward' },
];

/** Routes that only send the browser on to another address, which has its own screen above. The routes test checks
 *  that each of these renders a redirect and nothing else. */
export const REDIRECTS: string[] = [
  '/setup/*', `${B}/cashflow`, `${B}/setup`, `${B}/setup/:step`,
  '/', '/cashflow', '/spending', '/spending/*', '/transactions', '/review', '/plan', '/plan/*', '/settings', '/settings/*',
  '/profile', '/profile/*', '/accounts', '/accounts/*', '/you/*', '/taxes', '/ask', '/ask/*',
];

/** Adds what the demo seeds leave out and two screens need: a set-aside and a work trip, each the first of its kind,
 *  so their ids are SET_ASIDE_ID and TRIP_ID. Run on a freshly restored demo vault, signed in as alex. */
export async function addDemoRecords(request: APIRequestContext): Promise<void> {
  const day = ((await (await request.get('/api/b/ours/spending')).json()) as { as_of: string }).as_of;
  const year = Number(day.slice(0, 4));
  const sa = await request.post('/api/b/ours/setasides', { data: { name: 'Water heater', kind: 'one_off', amount_cents: 225_000, due_year: year + 2, due_month: 12 } });
  if (!sa.ok()) throw new Error(`adding the set-aside answered ${sa.status()}`);
  if ((await sa.json()).id !== SET_ASIDE_ID) throw new Error('the set-aside is not the first: restore the vault first');
  await request.post('/api/b/ours/reimburse/payers', { data: { name: 'Acme' } });
  const start = new Date(Date.UTC(year, Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)) - 20));
  const end = new Date(start.getTime() + 3 * 86_400_000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  const trip = await request.post('/api/b/ours/reimburse/trips', { data: { start: iso(start), end: iso(end), city: 'Denver, CO' } });
  if (!trip.ok()) throw new Error(`adding the trip answered ${trip.status()}`);
  if ((await trip.json()).trip.id !== TRIP_ID) throw new Error('the trip is not the first: restore the vault first');
}
