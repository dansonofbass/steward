import type { KeyboardEvent } from 'react';

// WEB-12: a group of role="radio" buttons keeps a native radio group's keys. The checked radio is the group's one Tab
// stop (radioTab), and the arrow keys move between them and choose (radioKeys on the radiogroup). radioKeys.test.ts
// scans every source for a radio without them.

const STEP: Record<string, number> = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };

/** A radiogroup's onKeyDown: an arrow moves to the next or previous radio, wrapping, and Home and End to the first and
 *  last; each chooses the radio it lands on. `choose` false only moves focus (Transactions' dates, where choosing closes
 *  the sheet). */
export function radioKeys(e: KeyboardEvent<HTMLElement>, choose = true) {
  const from = e.target;
  if (!(from instanceof HTMLElement) || from.getAttribute('role') !== 'radio') return;
  const radios = [...e.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]:not([disabled])')];
  const at = radios.indexOf(from);
  if (at < 0) return;
  const to = e.key in STEP ? (at + STEP[e.key] + radios.length) % radios.length
    : e.key === 'Home' ? 0 : e.key === 'End' ? radios.length - 1 : -1;
  if (to < 0) return;
  e.preventDefault();
  radios[to].focus();
  if (choose && to !== at) radios[to].click();
}

/** Moves focus only. */
export const radioFocusKeys = (e: KeyboardEvent<HTMLElement>) => radioKeys(e, false);

/** A radio's tabIndex: the checked one is the group's only Tab stop. */
export const radioTab = (checked: boolean) => (checked ? 0 : -1);
