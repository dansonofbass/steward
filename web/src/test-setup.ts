import '@testing-library/jest-dom/vitest';
import { afterEach, beforeAll, beforeEach, vi } from 'vitest';

import { setCurrentBook } from './api/book';
import { setUnauthorizedHandler } from './api/client';
import { forgetHome } from './api/home';
import { forgetGatewayWatch } from './lib/gateway';
import { forgetGatewayName } from './lib/gatewayName';
import { forgetHouseholdZone } from './lib/today';
import { forgetPersonPrefs } from './lib/celebrations';
import { forgetLines } from './lib/lines';
import { preloadAllScreens } from './lib/lazyScreen';
import { forgetDemoLoad } from './lib/reviewPrefs';
import { forgetJoy } from './screens/accounts/joy';
import { forgetCloser } from './screens/plan/change';
import { clearKeptDraft } from './screens/plan/planMemory';
import { freezeDate, letTestingLibraryDriveFakeTimers } from './test-clock';
import { forgetDialogs, installDialog } from './test-dialog';

letTestingLibraryDriveFakeTimers();
// jsdom's <dialog> can't open as a modal; Sheet is one (WEB-1).
installDialog();
// jsdom lays nothing out and logs "not implemented" for scrollTo; the router's scroll restoration calls it on every page
// change (WEB-2). A test that cares spies on it.
window.scrollTo = () => {};
// Unit tests render screens without the /b/:slug route; they run in the household book "ours".
setCurrentBook('ours');
// Every lazy screen the test file's imports registered, loaded before its first test: a findBy never races a chunk
// being transformed (flaky-test audit S1). The hook's own ceiling (hookTimeout) covers the load.
beforeAll(preloadAllScreens);
// Every test starts on TEST_NOW with real timers; useFakeTimers() (test-clock.ts) fakes the rest on that date.
beforeEach(freezeDate);
// What a test leaves behind never reaches the next (flaky-test audit S4). This runs after the file's own afterEach
// and Testing Library's cleanup.
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  localStorage.clear();
  sessionStorage.clear();
  setCurrentBook('ours');
  setUnauthorizedHandler(null);
  clearKeptDraft();
  forgetJoy();
  forgetLines();
  forgetPersonPrefs();
  forgetCloser();
  forgetDemoLoad();
  forgetHome();
  forgetGatewayWatch();
  forgetGatewayName();
  forgetHouseholdZone();
  forgetDialogs();
});

// Spec 2026-11-05, section 7: a screen never shows {gateway} unfilled. Every node and attribute a test renders is
// read as it lands (and the pending records once more at the end), so a constant that skipped gw() fails the test
// that rendered it, whichever screen it was.
let leaked: string | null = null;
const lookAt = (s: string | null | undefined) => { if (!leaked && s && s.includes('{gateway}')) leaked = s.slice(0, 160); };
function look(r: MutationRecord) {
  if (r.type === 'attributes') lookAt((r.target as Element).getAttribute(r.attributeName ?? ''));
  else if (r.type === 'characterData') lookAt(r.target.textContent);
  else r.addedNodes.forEach((n) => lookAt(n instanceof Element ? n.outerHTML : n.textContent));
}
const slotWatch = new MutationObserver((records) => records.forEach(look));
beforeEach(() => {
  leaked = null;
  slotWatch.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
});
afterEach(() => {
  slotWatch.takeRecords().forEach(look);
  slotWatch.disconnect();
  if (leaked) throw new Error(`A screen showed {gateway} unfilled: ${leaked}`);
});
