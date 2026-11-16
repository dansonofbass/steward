import {
  Archive, ArchiveRestore, ArrowDownLeft, Banknote, CalendarCheck, Check, CircleCheck, CircleDashed, Contact, Copy, Download, Eye, FileText,
  Flag, Hourglass, Landmark, Link2, ListChecks, Mail, MessageSquare, Paperclip, Pencil, Plus, Receipt, RefreshCw, Shield, TrendingDown, Trash2, Undo2, Unplug, Upload, Users, X, type LucideIcon,
} from 'lucide-react';
import type { DataSource, ItemKind, ItemStatus } from './api';
import { SOURCE_LABELS, STATUS_LABELS } from './copy';

const STATUS_ICONS: Record<ItemStatus, LucideIcon> = { confirmed: CircleCheck, needs_checking: CircleDashed, closed: Archive };
const SOURCE_ICONS: Record<DataSource, LucideIcon> = { feed: RefreshCw, statement: FileText, manual: Pencil };

/** Status is always an icon and a word (README, "The frame"). */
export function StatusMark({ status }: { status: ItemStatus }) {
  const Icon = STATUS_ICONS[status];
  return <span className={`st st--${status}`}><Icon size={20} aria-hidden="true" />{STATUS_LABELS[status]}</span>;
}

export function SourceMark({ source }: { source: DataSource | null }) {
  if (!source) return <span className="src">—</span>;
  const Icon = SOURCE_ICONS[source];
  return <span className="src"><Icon size={20} aria-hidden="true" />{SOURCE_LABELS[source]}</span>;
}

export const KIND_ICONS: Record<ItemKind, LucideIcon> = { account: Landmark, income: ArrowDownLeft, insurance: Shield, document: FileText, contact: Contact };

export const CHANGE_ICONS: Record<string, LucideIcon> = {
  plus: Plus, pencil: Pencil, 'circle-check': CircleCheck, archive: Archive, 'archive-restore': ArchiveRestore, eye: Eye,
  paperclip: Paperclip, trash: Trash2, x: X, link: Link2, undo: Undo2, receipt: Receipt, 'list-checks': ListChecks,
  copy: Copy, download: Download, upload: Upload, refresh: RefreshCw, unplug: Unplug, users: Users,
  flag: Flag, hourglass: Hourglass, check: Check, banknote: Banknote, 'trending-down': TrendingDown, mail: Mail, 'message-square': MessageSquare, 'calendar-check': CalendarCheck,
};
