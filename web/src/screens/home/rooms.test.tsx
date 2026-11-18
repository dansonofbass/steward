import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { SinceData } from '../../api/home';
import { wrapBook } from '../../test-utils';
import HomeSince from './HomeSince';
import MonthStrip from './MonthStrip';
import { HOME } from './fixtures';
import { BLANK, SinceRoom, StripRoom } from './rooms';

const SINCE: SinceData = {
  from: '2026-10-27T19:00:00+00:00', from_day: '2026-10-27', over_month: false, more: 4, net_worth_cents: 210_000,
  lines: [
    { kind: 'pay', category: 'income', name: 'Northwind payroll', n: 1, places: 1, cents: 421_200 },
    { kind: 'bill', category: 'utilities', name: 'City Power', n: 1, places: 1, cents: -18_600 },
    { kind: 'group', category: 'dining', name: null, n: 3, places: 3, cents: -18_000 },
  ],
};
const NOTHING: SinceData = { ...SINCE, lines: [], net_worth_cents: null, more: 0 };
const AS_OF = '2026-10-30';
// What decides the strip's height: its children's layout classes, in order.
const shape = (el: Element) => [...el.children].map((n) => n.classList[0]);
// The room's lines with nothing in them yet. Each must hold a character CSS doesn't collapse: a line of plain spaces,
// or an empty flex box, lays out 0 px tall, and the part that lands is a line taller.
const emptyLines = (room: Element) => [...room.querySelectorAll('*')]
  .filter((el) => el.children.length === 0 && !el.classList.contains('strip'))
  .filter((el) => (el.textContent ?? '').replace(/[ \t\n\r\f]/g, '') === '')
  .map((el) => el.outerHTML);
const sinceRoom = (since: SinceData) => render(<SinceRoom since={since} asOf={AS_OF} />).getByTestId('since-room');
const realSince = (since: SinceData) => wrapBook(<HomeSince since={since} asOf={AS_OF} />).getByTestId('since');

describe("the strip's and Since's rooms (issue #24)", () => {
  it("the strip room has the strip's boxes, a line of month names' height, and nothing to read", () => {
    const room = render(<StripRoom />).getByTestId('strip-room');
    expect(room).toHaveAttribute('aria-hidden', 'true');
    expect(room).toHaveClass('mstrip');
    const { container } = wrapBook(<MonthStrip months={HOME.flow.months} asOf={HOME.as_of} />);
    const strip = container.querySelector('.mstrip')!;
    expect(shape(room)).toEqual(['strip', 'mstrip__foot']);
    expect(shape(strip)).toEqual(shape(room));
    // The foot is a flex box: its line is a child holding a no-break space, as the real foot's month names are.
    expect(room.querySelector('.mstrip__foot > span')?.textContent).toBe(BLANK);
    expect(emptyLines(room)).toEqual([]);
  });

  it('the Since room has the same heading, a row for each line HomeSince shows, and its More line', () => {
    const room = sinceRoom(SINCE);
    expect(room).toHaveAttribute('aria-hidden', 'true');
    const real = realSince(SINCE);
    // The when word too: "Since you last looked (Tuesday)" can wrap on a phone where the bare heading doesn't.
    expect(room.querySelector('.since__head')).toHaveTextContent(real.querySelector('h2')!.textContent!);
    expect(room.querySelectorAll('.since__row')).toHaveLength(real.querySelectorAll('.since__row').length);
    expect(room.querySelectorAll('.since__more')).toHaveLength(1);
    expect(real.querySelectorAll('.since__more')).toHaveLength(1);
    expect(emptyLines(room)).toEqual([]);
  });

  it('with nothing new, the Since room is the heading and the same nothing-new line', () => {
    const room = sinceRoom(NOTHING);
    const real = realSince(NOTHING);
    expect(room.querySelectorAll('.since__row')).toHaveLength(0);
    expect(room.querySelector('.since__head')).toHaveTextContent(real.querySelector('h2')!.textContent!);
    expect(room.querySelectorAll('p')).toHaveLength(2);
    expect(room.querySelectorAll('p')[1]).toHaveTextContent(real.querySelector('[data-testid=since-nothing]')!.textContent!);
    expect(emptyLines(room)).toEqual([]);
  });

  it('over a month ago, the heading says so in both', () => {
    const since = { ...SINCE, from_day: '2026-09-01', over_month: true };
    expect(sinceRoom(since).querySelector('.since__head')).toHaveTextContent('Since you last looked (over a month ago)');
    expect(realSince(since).querySelector('h2')).toHaveTextContent('Since you last looked (over a month ago)');
  });
});
