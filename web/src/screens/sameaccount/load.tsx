import { type ComponentType } from 'react';
import { lazyScreen } from '../../lib/lazyScreen';
import { MERGE_UNAVAILABLE } from '../../lib/copy';
import { Notice } from '../../ui/Notice';
import type { MergeReply } from './api';
import type { MergeIntoProps } from './MergeInto';

// The card and the sheet are small chunks of their own (spec, Privacy and performance): Home, Accounts and an account's
// page are in the first download. A chunk that can't be fetched (a deploy replaced it while the page was open) shows
// nothing for the card, and a one-line notice for the sheet, which a person asked for.
const Nothing = () => null;
function Missing() { return <Notice tone="error">{MERGE_UNAVAILABLE}</Notice>; }

export const loadSameAccount = (load: () => Promise<{ default: ComponentType }> = () => import('./SameAccount')) =>
  load().catch(() => ({ default: Nothing }));
export const SameAccount = lazyScreen(() => loadSameAccount());
export const MergeInto = lazyScreen<ComponentType<MergeIntoProps>>(() => import('./MergeInto').catch(() => ({ default: Missing })));
export const MergedNote = lazyScreen<ComponentType<{ reply: MergeReply }>>(() =>
  import('./MergeInto').then((m) => ({ default: m.MergedNote }), () => ({ default: Nothing })));
