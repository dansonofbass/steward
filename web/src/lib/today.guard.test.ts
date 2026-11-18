// Issue #26: every date default and relative label uses the household's today (lib/today.ts). A day or a year built
// from the device's own clock fields comes back the way the issue found it, one screen at a time, so this reads the
// app's source and fails on the shapes that did it.
import { readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const src = (rel: string) => new URL(rel, import.meta.url);
const ALLOWED = new Set(['lib/today.ts']);
const FILES = readdirSync(src('../'), { recursive: true, encoding: 'utf8' })
  .map((f) => f.replace(/\\/g, '/'))
  .filter((f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f) && !/(^|\/)test-[^/]*$/.test(f) && !ALLOWED.has(f));
const read = (rel: string) => readFileSync(src(`../${rel}`), 'utf8');

const SHAPES: [string, RegExp][] = [
  ['a YYYY-MM-DD built from Date fields', /\$\{\s*\w+\.getFullYear\(\)\s*\}-/],
  ["the device's year as a default", /new Date\(\)\.getFullYear\(\)/],
  ["the device's day from a timestamp of now", /localYmd\(\s*new Date\(\)/],
  // A day or a month moved on the device calendar: the same day, the next month's 1st, this month's last day.
  ['a day moved on the device calendar', /new Date\(\s*\w+\.getFullYear\(\),\s*\w+\.getMonth\(\)/],
  // "Is it the same day?" asked of the device's calendar (plan's savedWhen did, beside a household "on Nov 16").
  ["the device's day compared", /\.toDateString\(\)/],
];

/** The arguments of a call starting at `open` (the index of its "("), split at its own commas. */
function args(text: string, open: number): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = open + 1;
  for (let i = open; i < text.length; i++) {
    const c = text[i];
    if (c === '(' || c === '[' || c === '{') depth++;
    else if (c === ')' || c === ']' || c === '}') {
      depth--;
      if (depth === 0) { out.push(text.slice(start, i).trim()); return out; }
    } else if (c === ',' && depth === 1) { out.push(text.slice(start, i).trim()); start = i + 1; }
  }
  return out;
}

// The relative-label helpers take "today" as their second argument. A Date built from a year and a month is the
// device's midnight, which is another day at home for a household west of the device (Signs passed one, so all of
// January the plan sign compared against last year). Pass the day as a YYYY-MM-DD string instead.
const TODAY_TAKERS = /\b(?:dateLabel|dateLabelFromIso|relativeDays|updatedLabel)\(/g;
function deviceMidnights(text: string): string[] {
  const found: string[] = [];
  for (const m of text.matchAll(TODAY_TAKERS)) {
    const today = args(text, m.index + m[0].length - 1)[1] ?? '';
    const made = /^new Date\(/.exec(today);
    if (made && args(today, made[0].length - 1).length >= 2) found.push(`${m[0]}…, ${today})`);
  }
  return found;
}

// A household day beside a device clock time: the day says Nov 16 while the time is already Nov 17 on the device.
// lib/today's clockTime is the household's clock.
const HOUSEHOLD_DAY = /\b(?:dayOf|localYmd|dateLabelFromIso|today|thisYear)\(/;
const DEVICE_TIME = /\.toLocaleTimeString\(/;

describe("the household's today is the only today (issue #26)", () => {
  it('reads the whole app', () => { expect(FILES.length).toBeGreaterThan(300); });

  it('no screen builds a day or a year from the device clock', () => {
    const found: string[] = [];
    for (const rel of FILES) {
      read(rel).split('\n').forEach((line, i) => {
        for (const [what, re] of SHAPES) if (re.test(line)) found.push(`${rel}:${i + 1} ${what}`);
      });
    }
    expect(found).toEqual([]);
  });

  it("no relative label is handed the device's midnight as today", () => {
    expect(FILES.flatMap((rel) => deviceMidnights(read(rel)).map((call) => `${rel}: ${call}`))).toEqual([]);
  });

  it("no screen pairs the household's day with the device's clock time", () => {
    expect(FILES.filter((rel) => { const t = read(rel); return HOUSEHOLD_DAY.test(t) && DEVICE_TIME.test(t); })).toEqual([]);
  });

  it('catches each shape it names', () => {
    // The two lines the review found, as they were.
    expect(deviceMidnights("dateLabelFromIso(p.saved_at, new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1))")).toHaveLength(1);
    expect(SHAPES.some(([, re]) => re.test('if (d.toDateString() !== now.toDateString()) return x;'))).toBe(true);
    // Chat's cap date and budget pace, as they were: the next month and the month's length on the device calendar.
    expect(SHAPES.some(([, re]) => re.test('export const nextMonth = (now = new Date()) => new Date(now.getFullYear(), now.getMonth() + 1, 1)'))).toBe(true);
    expect(SHAPES.some(([, re]) => re.test('  const days = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();'))).toBe(true);
    // An instant as today is fine, and so is a day as a string.
    expect(deviceMidnights('relativeDays(iso, new Date(now))')).toEqual([]);
    expect(deviceMidnights('dateLabelFromIso(p.saved_at, `${month}-01`)')).toEqual([]);
    expect(HOUSEHOLD_DAY.test('const key = dayOf(r.at);') && DEVICE_TIME.test("new Date(iso).toLocaleTimeString('en-US')")).toBe(true);
  });
});
