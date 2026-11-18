// Since you last looked: its heading, its nothing-new line and the last look's day in words. Not in sinceCopy.ts with
// the rest of Since's copy: Home's room for Since (rooms.tsx) sets the same heading and line before the HomeSince chunk
// lands (issue #24), so a heading that wraps takes the same room in both, and these few strings ship with Home.
export const SINCE_HEAD = 'Since you last looked';
export const WHEN_TODAY = 'earlier today';
export const WHEN_YESTERDAY = 'yesterday';
export const WHEN_OVER_MONTH = 'over a month ago';
export const NOTHING_NEW = 'Nothing new since {when}.';

const WEEKDAY = new Intl.DateTimeFormat('en-US', { weekday: 'long' });
const SHORT = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const DAY_MS = 86_400_000;
const local = (iso: string) => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
};

/** P34: the last look's day in words, from the server's days (as_of and from_day), never the browser's clock:
 *  earlier today, yesterday, a weekday up to 6 days back, then "Oct 12"; over a month ago when it was. */
export function whenWord(fromDay: string, asOf: string, overMonth: boolean): string {
  if (overMonth) return WHEN_OVER_MONTH;
  const n = Math.round((local(asOf).getTime() - local(fromDay).getTime()) / DAY_MS);
  if (n <= 0) return WHEN_TODAY;
  if (n === 1) return WHEN_YESTERDAY;
  return n <= 6 ? WEEKDAY.format(local(fromDay)) : SHORT.format(local(fromDay));
}

/** "Nothing new since yesterday." */
export const nothingNew = (when: string) => NOTHING_NEW.replace('{when}', when);
