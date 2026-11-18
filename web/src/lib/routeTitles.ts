// Each route's name for the browser tab and a screen reader (WEB-3): "<Screen> · Steward". routes.tsx puts one in every
// route's handle; RouteFrame sets document.title from the deepest match that has one, and routeTitles.test.ts fails on
// a route without one. Plain nouns, the page's own name where it has one. A page for one item (an account, a trip)
// shows its noun only while the item loads, then the item's name (frame/itemTitle.ts, issue #29).
import type { Params } from 'react-router-dom';
import { SECTION_NAME, SECTION_STEPS, isSection } from './profileSections';
import { ACCOUNTS, ASK, BUSINESS, CARE, HELP, HOME, INVENTORY, PLAN, REVIEW, S_ABOUT, S_APPEARANCE, SIGN_IN_AND_DEVICES, SPENDING, TAXES } from './copy';

export type RouteTitle = string | ((params: Params) => string);

const APP = 'Steward';
export const titled = (name: string) => (name ? `${name} · ${APP}` : APP);

const profileSection = (p: Params) => (isSection(p.section) ? SECTION_NAME[p.section] : 'Profile');
const profileStep = (p: Params) => {
  if (!isSection(p.section)) return 'Profile';
  const steps = SECTION_STEPS[p.section];
  const at = steps.indexOf(p.step ?? '');
  return at < 0 ? SECTION_NAME[p.section] : `${SECTION_NAME[p.section]}, step ${at + 1} of ${steps.length}`;
};

export const T = {
  home: HOME,
  spending: SPENDING,
  trends: 'Spending over time',
  targets: 'Spending targets',
  setAsides: 'Set-asides',
  newSetAside: 'New set-aside',
  setAside: 'Set-aside',
  reimbursements: 'Reimbursements',
  trip: 'Trip',
  category: 'Spending by category',
  accounts: ACCOUNTS,
  account: 'Account',
  transactions: 'Transactions',
  review: REVIEW,
  plan: PLAN,
  tryChanges: 'Try changes',
  nextDollar: 'Next dollar',
  howItWorks: 'How the plan works',
  business: BUSINESS,
  taxes: TAXES,
  inventory: INVENTORY,
  newItem: 'New item',
  suggestions: 'Suggestions',
  taxForm: 'Tax form',
  item: 'Item',
  editItem: 'Edit item',
  attach: 'Attach a file',
  care: CARE,
  lookInto: 'Look into',
  flag: 'Something to look into',
  profile: 'Profile',
  profileSection,
  profileStep,
  devices: SIGN_IN_AND_DEVICES,
  appearance: S_APPEARANCE,
  help: HELP,
  about: S_ABOUT,
  welcome: 'Welcome',
  settings: 'Settings',
  ask: ASK,
  login: 'Sign in',
  forgot: 'Forgot password',
  reset: 'Reset password',
  design: 'Design',
  setup: 'Set up Steward',
  invite: 'Invitation',
} as const;

/** A route's title for these params; '' when it has none. */
export const titleFor = (t: RouteTitle | undefined, params: Params): string => (typeof t === 'function' ? t(params) : t ?? '');
