import { beforeEach, describe, expect, it } from 'vitest';
import { addSorts, NO_RUN, readTally, runAfter, type Run } from './sorts';

beforeEach(() => localStorage.clear());

describe('Ten in a row (review focus P18: sorted cards this visit, no time window)', () => {
  const sorts = (run: Run, n: number) => {
    const labels: (string | null)[] = [];
    for (let i = 0; i < n; i++) { const r = runAfter(run, 'sort'); run = r.run; labels.push(r.label); }
    return { run, labels };
  };

  it('says Ten in a row at the tenth sort, once per run', () => {
    const { run, labels } = sorts(NO_RUN, 12);
    expect(labels).toEqual([null, null, null, null, null, null, null, null, null, 'Ten in a row', null, null]);
    expect(run).toEqual({ n: 12, shown: true });
  });

  it('an Undo, a Snooze or an Ignore breaks the run, and a new run can say it again', () => {
    const nine = sorts(NO_RUN, 9).run;
    const broken = runAfter(nine, 'break');
    expect(broken).toEqual({ run: NO_RUN, label: null });
    expect(sorts(broken.run, 9).labels.every((l) => l === null)).toBe(true);
    expect(sorts(runAfter(sorts(NO_RUN, 10).run, 'break').run, 10).labels[9]).toBe('Ten in a row');
  });
});

describe('the tally and milestones (per device; no streaks to lose)', () => {
  const day = new Date(2026, 9, 28, 12);

  it('counts what was sorted today and in all, and a new day starts today at 0', () => {
    addSorts(1, day);
    expect(addSorts(7, day).tally).toEqual({ total: 8, day: '2026-10-28', today: 8 });
    expect(readTally(new Date(2026, 9, 29, 9))).toEqual({ total: 8, day: '2026-10-29', today: 0 });
  });

  it('marks each milestone once, the highest when one sort crosses several', () => {
    localStorage.setItem('steward-sorts', JSON.stringify({ total: 99, day: '2026-10-28', today: 0 }));
    expect(addSorts(1, day).milestone).toBe(100);
    expect(addSorts(1, day).milestone).toBeNull();
    localStorage.setItem('steward-sorts', JSON.stringify({ total: 240, day: '2026-10-28', today: 0 }));
    expect(addSorts(300, day).milestone).toBe(500);
  });

  it('reads a broken tally as nothing yet', () => {
    localStorage.setItem('steward-sorts', 'null');
    expect(readTally(day)).toEqual({ total: 0, day: '2026-10-28', today: 0 });
  });
});
