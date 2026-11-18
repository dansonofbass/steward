// The Ask states the Ask tab and Ask about this's panel both show (phase 13 spec, What's there today): the gateway away
// or paused, chat off, the budget used up, and "Before you ask". Moved from Ask.tsx unchanged.
import { useQueryClient } from '@tanstack/react-query';
import { Gauge, LockKeyhole, PowerOff, ServerOff, Settings as SettingsIcon } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { currentBook } from '../../api/book';
import { ApiError } from '../../api/client';
import type { BookSummary } from '../../api/types';
import { bookHref } from '../../book/BookContext';
import { setQueryDataIfStillIn } from '../../queryClient';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import type { ChatStatus } from './api';
import { andList, fill, markSeen } from './askApi';
import * as C from './copy';
import { gw } from '../../lib/gatewayName';
import { today } from '../../lib/today';

// The household's month, not the device's (issue #26): read from the household's today (a YYYY-MM-DD) and named as
// that date in UTC, so a device in another zone, or anyone near midnight on the last of the month, sees home's month.
const MONTH_DAY = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'short', day: 'numeric' });
const MONTH_NAME = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', month: 'long' });
const ymd = (now: Date) => today(now).split('-').map(Number);

/** The 1st of the household's next month, "Dec 1". */
export const nextMonth = (now = new Date()) => { const [y, m] = ymd(now); return MONTH_DAY.format(Date.UTC(y, m, 1)); };

/** The household's month today: its name, today's day of it and how many days it has. */
export function thisMonth(now = new Date()): { name: string; day: number; days: number } {
  const [y, m, d] = ymd(now);
  return { name: MONTH_NAME.format(Date.UTC(y, m - 1, 1)), day: d, days: new Date(Date.UTC(y, m, 0)).getUTCDate() };
}

export function GatewayState({ s }: { s: ChatStatus }) {
  if (s.gateway.state === 'away') {
    return (
      <div className="state">
        <ServerOff size={24} aria-hidden="true" />
        <h2>{gw(C.AWAY_TITLE)}</h2>
        <p>{s.gateway.line}</p>
        <p>{C.AWAY_BODY}</p>
        <p className="small muted">{C.AWAY_NOTE}{s.gateway.last_answered && ` ${fill(gw(C.AWAY_LAST), { when: s.gateway.last_answered })}`}</p>
      </div>
    );
  }
  return <div className="state"><LockKeyhole size={24} aria-hidden="true" /><h2>{C.PAUSED_TITLE}</h2><p>{s.gateway.line}</p></div>;
}

export function OffState({ viewer, slug, sample }: { viewer: boolean; slug: string; sample?: boolean }) {
  if (sample) return <div className="state"><p>{C.ASK_OFF_SAMPLE}</p></div>;
  return (
    <div className="state">
      <PowerOff size={24} aria-hidden="true" /><h2>{C.OFF_TITLE}</h2><p>{C.OFF_BODY}</p>
      {!viewer && <Link className="link" to={bookHref(slug, '/settings/chat')}><SettingsIcon size={20} aria-hidden="true" />{C.GO_SETTINGS}</Link>}
    </div>
  );
}

export function CapState({ s, slug }: { s: ChatStatus; slug: string }) {
  return (
    <div className="state">
      <Gauge size={24} aria-hidden="true" /><h2>{C.CAP_TITLE}</h2><p>{s.budget?.cap_line}</p>
      {s.can_budget && <Link className="link" to={bookHref(slug, '/settings/chat')}><SettingsIcon size={20} aria-hidden="true" />{C.CHANGE_BUDGET}</Link>}
    </div>
  );
}

/** "Before you ask" (spec 5.1), once per person per book. Start marks it read; Not now is the caller's: the Ask tab
 *  opens the book's Home, the panel closes (P22). */
export function Disclosure({ s, book, onNotNow }: { s: ChatStatus; book: BookSummary; onNotNow: () => void }) {
  const qc = useQueryClient();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const start = async () => {
    setStarting(true);
    setError(null);
    const bookAtStart = currentBook();
    try {
      await markSeen();
      setQueryDataIfStillIn<ChatStatus>(qc, bookAtStart, ['chat', 'status'], (old) => old && { ...old, seen: true });
    } catch (e) {         // shown, never an unhandled rejection (final review, Task 15)
      setError(e instanceof ApiError ? e.message : C.START_FAILED);
    } finally {
      setStarting(false);
    }
  };
  return (
    <>
      <h2 className="before__title" tabIndex={-1}><LockKeyhole size={24} aria-hidden="true" />{C.BEFORE_TITLE}</h2>
      <p className="before__text">{s.disclosure}</p>
      <p className="small muted">{fill(C.BEFORE_MEMBERS, { book: book.name, names: andList(s.members) })}</p>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="confirm__acts">
        <Button busy={starting} onClick={() => void start()}>{C.START}</Button>
        <Button variant="quiet" onClick={onNotNow}>{C.NOT_NOW}</Button>
      </div>
    </>
  );
}
