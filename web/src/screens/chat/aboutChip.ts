// The chip's words and the "About: …" line over a question (Ask about this, Copy), from POST /chat/about's wire object:
// the alias's real name from labels, and the web's own words for categories, flag checks and care levels. Only values
// that are sent are shown, so the chip never suggests that a store, a nickname or an account's name goes.
import { label } from '../../lib/categories';
import { dateLabel, money } from '../../lib/format';
import { fill, type AboutWire } from './askApi';
import * as C from './copy';
import { thisYear } from '../../lib/today';

const LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

/** "October", or "October 2025" when it isn't this year. */
export function monthWord(ym: string, today: Date): string {
  const name = LONG[Number(ym.slice(5, 7)) - 1];
  return Number(ym.slice(0, 4)) === thisYear(today) ? name : `${name} ${ym.slice(0, 4)}`;
}

export type Thing = { thing: string; alias: string | null };

export function aboutThing(w: AboutWire, labels: Record<string, string>, today: Date): Thing {
  switch (w.kind) {
    case 'account': return { thing: labels[w.account] ?? w.account, alias: w.account };
    case 'category': return { thing: `${label(w.category)} · ${monthWord(w.month, today)}`, alias: null };
    case 'plan': return { thing: C.ABOUT_PLAN, alias: null };
    case 'transaction': {
      const amount = fill(w.amount_cents > 0 ? C.ABOUT_MONEY_IN : C.ABOUT_MONEY_OUT, { amount: money(w.amount_cents, { sign: 'never' }) });
      return { thing: `${amount} · ${dateLabel(w.date, today)}`, alias: null };
    }
    case 'flag': return { thing: `${fill(C.ABOUT_FLAG, { check: C.CHECK_WORDS[w.check] ?? w.check })} · ${dateLabel(w.date, today)}`, alias: null };
    case 'care': return { thing: w.level ? (C.CARE_LEVEL_WORDS[w.level] ?? w.level) : C.ABOUT_CARE, alias: null };
  }
}

/** "About: Checking · sent as Account 3": the line over a question in a conversation. */
export function aboutLine(w: AboutWire, labels: Record<string, string>, today: Date): string {
  const t = aboutThing(w, labels, today);
  return fill(C.ABOUT_CHIP, { thing: t.thing }) + (t.alias ? fill(C.ABOUT_SENT_AS, { alias: t.alias }) : '');
}
