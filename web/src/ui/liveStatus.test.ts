// Issue #23: a role="status" node that mounts with its words already in it is often not announced. Notice and Review's
// caught-up state now say their words through the page's polite region (Live.tsx, useSayShown). The other status nodes
// below were there before; this list may only shrink. A new line to announce uses useSayShown, or a region that is in
// the page before its words (as Review's review-said is).
import { describe, expect, it } from 'vitest';

const SOURCES: Record<string, string> = Object.fromEntries(
  Object.entries(import.meta.glob<string>('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }))
    .filter(([path]) => !/\.test\.[jt]sx?$/.test(path)),
);

const STATUS = /role=(?:"status"|\{[^}]*'status'[^}]*\})/g;

/** Status nodes from before issue #23, per file. */
const KNOWN: Record<string, number> = {
  '/src/screens/Review.tsx': 1,   // review-said: always mounted, its words change
  '/src/screens/bulk/BulkSort.tsx': 1,
  '/src/screens/business/BusinessSettings.tsx': 1,
  '/src/screens/chat/AboutChip.tsx': 1,
  '/src/screens/chat/Chip.tsx': 1,
  '/src/screens/chat/TurnView.tsx': 1,
  '/src/screens/chat/aliasText.tsx': 1,
  '/src/screens/export/Export.tsx': 1,
  '/src/screens/home/BackgroundLine.tsx': 1,
  '/src/screens/home/HomeMoments.tsx': 1,
  '/src/screens/import/Import.tsx': 1,
  '/src/screens/import/ImportDone.tsx': 1,
  '/src/screens/plan/PlanReady.tsx': 1,
  '/src/screens/plan/SaveBar.tsx': 1,
  '/src/screens/profile/ProfilePage.tsx': 2,
  '/src/screens/profile/benefits/Benefits.tsx': 1,
  '/src/screens/profile/field.tsx': 1,
  '/src/screens/profile/home/Payoff.tsx': 2,
  '/src/screens/profile/kids/SavedUndo.tsx': 1,
  '/src/screens/ready/Ready.tsx': 1,
  '/src/screens/reimburse/Reimbursements.tsx': 1,
  '/src/screens/reimburse/Trip.tsx': 1,
  '/src/screens/review/ReviewCard.tsx': 2,
  '/src/screens/review/focus/FocusCard.tsx': 2,
  '/src/screens/sameaccount/MergeInto.tsx': 1,
  '/src/screens/sameaccount/Said.tsx': 1,
  '/src/screens/settings/Banks.tsx': 1,
  '/src/screens/spending/Targets.tsx': 1,
  '/src/screens/spending/setasides/Moments.tsx': 2,
  '/src/screens/transactions/TxnDetail.tsx': 1,
  '/src/screens/welcome/Extras.tsx': 4,
  '/src/screens/welcome/FirstRun.tsx': 1,
  '/src/ui/CategoryMenu.tsx': 1,
  '/src/ui/CopyButton.tsx': 1,   // in the page before the press; its words change
  '/src/ui/UndoToast.tsx': 1,    // only outside LiveRegions (a component test)
};

function grown(sources: Record<string, string>): string[] {
  return Object.entries(sources).flatMap(([path, src]) => {
    const n = src.match(STATUS)?.length ?? 0;
    return n > (KNOWN[path] ?? 0) ? [`${path}: ${n}`] : [];
  });
}

describe('no new status node that mounts with its words (issue #23)', () => {
  it('Notice and the caught-up state have none', () => {
    expect(SOURCES['/src/ui/Notice.tsx'].match(STATUS)).toBeNull();
    expect(SOURCES['/src/screens/Review.tsx'].match(STATUS)).toHaveLength(1);
  });

  it('no file has more than it had', () => {
    expect(grown(SOURCES)).toEqual([]);
  });

  it('catches a new one', () => {
    expect(grown({ '/src/ui/New.tsx': '<p role="status">{line}</p>', '/src/ui/CopyButton.tsx': 'role="status" role={x ? \'alert\' : \'status\'}' }))
      .toEqual(['/src/ui/New.tsx: 1', '/src/ui/CopyButton.tsx: 2']);
  });
});
