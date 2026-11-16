// Three questions that fit the page (P21, Engineering choices 6-8): accounts by kind; a category's first question by
// whether it is over this month; a viewer's third category question avoids store names; a transaction's by whether it
// is sorted yet.
import type { Surface } from '../../../ask/about';
import { label } from '../../../lib/categories';
import { monthWord } from '../aboutChip';
import { fill } from '../askApi';
import * as P from './copy';

export function suggestionsFor(s: Surface, viewer: boolean, today: Date): string[] {
  switch (s.kind) {
    case 'account': return s.group === 'card' ? P.ACCOUNT_CARD : s.group === 'invest' ? P.ACCOUNT_INVEST : P.ACCOUNT_EVERYDAY;
    case 'category': {
      const name = label(s.category);
      const first = s.over ? fill(P.CATEGORY_OVER, { label: name }) : fill(P.CATEGORY_MADE_UP, { label: name, month: monthWord(s.month, today) });
      return [first, P.CATEGORY_HIGHER, viewer ? P.CATEGORY_LAST_YEAR : P.CATEGORY_PLACES];
    }
    case 'transaction':
      return s.category === 'uncategorized' ? P.TXN_UNSORTED : P.TXN_SORTED.map((q) => fill(q, { label: label(s.category) }));
    case 'plan': return s.page === 'how' ? P.PLAN_HOW : P.PLAN_OVERVIEW;
    case 'flag': return P.FLAG;
    case 'care': return P.CARE;
    case 'care-scenario': return P.CARE_SCENARIO;
  }
}
