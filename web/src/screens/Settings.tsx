import { BadgeCheck, BookOpen, Briefcase, ChevronLeft, ChevronRight, Download, Flag, History, Landmark, Library, ListX, MessageCircle, ScrollText, Tags, Upload, UsersRound, type LucideIcon } from 'lucide-react';
import { Suspense, type ComponentType } from 'react';
import { lazyScreen } from '../lib/lazyScreen';
import { useLocation, useParams } from 'react-router-dom';
import { useMe } from '../api/hooks';
import { useBook } from '../book/BookContext';
import { Link, Navigate } from '../book/links';
import { ToProfile } from '../book/ToProfile';
import { BACK_TO_SETTINGS, G_FEATURES, G_HOUSEHOLD, G_MONEY, G_RECORDS, SETTINGS_FOR, SETTINGS_VIEWER_EMPTY } from '../lib/copy';
import { useWide } from '../lib/useWide';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';
import Banks from './settings/Banks';
import BookDetails from './settings/BookDetails';
import Books from './settings/Books';
import CategoryRules from './settings/CategoryRules';
import Log from './settings/Log';
import Members from './settings/Members';
import { InSettingsColumn } from './settings/column';
import { SECTION_RULES, type Group, type SectionRule } from './settings/sections';
import ThisBook from './settings/ThisBook';
import './Settings.css';

const DismissedPage = lazyScreen(() => import('./inventory/Inventory').then((m) => ({ default: m.Dismissed })));
function DismissedSection() {
  return <Suspense fallback={<Card><Skeleton lines={3} /></Card>}><DismissedPage /></Suspense>;
}

const ChangeRecordPage = lazyScreen(() => import('./inventory/Inventory').then((m) => ({ default: m.ChangeRecord })));
function ChangeRecordSection() {
  return <Suspense fallback={<Card><Skeleton lines={5} /></Card>}><ChangeRecordPage /></Suspense>;
}

const WatchingPage = lazyScreen(() => import('./inventory/Inventory').then((m) => ({ default: m.Watching })));
function WatchingSection() {
  return <Suspense fallback={<Card><Skeleton lines={6} /></Card>}><WatchingPage /></Suspense>;
}

// Books lists every book; with a step it is one book's details, read without switching to it (decision 10).
function BooksSection() {
  const { step } = useParams();
  return step ? <BookDetails slug={step} /> : <Books />;
}

const ChatPage = lazyScreen(() => import('./chat/ChatSettings'));
function ChatSection() {
  return <Suspense fallback={<Card><Skeleton lines={5} /></Card>}><ChatPage /></Suspense>;
}

// Guided setup spec 3: Get Steward ready is its own lazy chunk (the rows, their panels and the pairing form).
const ReadyPage = lazyScreen(() => import('./ready/Ready'));
function ReadySection() {
  return <Suspense fallback={<Card><Skeleton lines={8} /></Card>}><ReadyPage /></Suspense>;
}

// Import/export spec P23, P35: Import is its own lazy chunk (it was in the initial bundle).
const ImportPage = lazyScreen(() => import('./import/Import'));
function ImportSection() {
  return <Suspense fallback={<Card><Skeleton lines={4} /></Card>}><ImportPage /></Suspense>;
}

// Import/export spec P23: Export is its own section in Records, for managers, and its own lazy chunk (P35).
const ExportPage = lazyScreen(() => import('./export/Export'));
function ExportSection() {
  return <Suspense fallback={<Card><Skeleton lines={4} /></Card>}><ExportPage /></Suspense>;
}

const BusinessPage = lazyScreen(() => import('./business/BusinessSettings'));
function BusinessSection() {
  return <Suspense fallback={<Card><Skeleton lines={6} /></Card>}><BusinessPage /></Suspense>;
}

const GROUPS: { key: Group; label: string }[] = [
  { key: 'household', label: G_HOUSEHOLD }, { key: 'money', label: G_MONEY }, { key: 'features', label: G_FEATURES }, { key: 'records', label: G_RECORDS },
];
/** Each section's icon and page; who sees it, its name and its group are settings/sections.ts. */
const PAGES: Record<string, { icon: LucideIcon; page: ComponentType }> = {
  ready: { icon: BadgeCheck, page: ReadySection },
  members: { icon: UsersRound, page: Members },
  book: { icon: BookOpen, page: ThisBook },
  books: { icon: Library, page: BooksSection },
  banks: { icon: Landmark, page: Banks },
  import: { icon: Upload, page: ImportSection },
  rules: { icon: Tags, page: CategoryRules },
  business: { icon: Briefcase, page: BusinessSection },
  watching: { icon: Flag, page: WatchingSection },
  chat: { icon: MessageCircle, page: ChatSection },
  log: { icon: ScrollText, page: Log },
  export: { icon: Download, page: ExportSection },
  changes: { icon: History, page: ChangeRecordSection },
  dismissed: { icon: ListX, page: DismissedSection },
};
type Section = SectionRule & { icon: LucideIcon; page: ComponentType };
const SECTIONS: Section[] = SECTION_RULES.map((r) => ({ ...r, ...PAGES[r.slug] }));

// Old Settings addresses (decision 13): what moved out of Settings; Setup and Profile are the Profile screen now.
const MOVED: Record<string, string> = { accounts: '/accounts', people: '/you/devices', appearance: '/you/appearance' };

/** The sections in their groups, each group under its name: a card per group on a phone, one plain column on a laptop. */
function Groups({ sections, current, wide }: { sections: Section[]; current?: string; wide: boolean }) {
  return GROUPS.map(({ key, label }) => {
    const rows = sections.filter((s) => s.group === key);
    if (!rows.length) return null;
    const links = rows.map(({ slug, label: name, icon: Icon }) => (
      <Link key={slug} to={`/settings/${slug}`} aria-current={slug === current ? 'page' : undefined}>
        <Icon size={20} aria-hidden="true" />{name}{!wide && <ChevronRight size={20} aria-hidden="true" />}
      </Link>
    ));
    return (
      <div className="sgroup" key={key}>
        <h2 className="eyebrow">{label}</h2>
        {wide ? links : <div className="card slist">{links}</div>}
      </div>
    );
  });
}

export default function Settings() {
  const { section: slug, step } = useParams();
  const { search } = useLocation();
  const wide = useWide();
  const book = useBook();
  const me = useMe();
  const sections = SECTIONS.filter((s) => s.show(book, me.data));
  if (slug && Object.hasOwn(MOVED, slug)) return <Navigate to={`${MOVED[slug]}${search}`} replace />;
  if (slug === 'setup' || slug === 'profile') return <ToProfile />;
  const chosen = SECTIONS.find((s) => s.slug === slug && (s.show(book, me.data) || s.open?.(book, step)));
  if (!chosen && wide && sections.length) return <Navigate to={`/settings/${sections[0].slug}`} replace />;
  const Page = chosen?.page;
  const empty = <p className="muted">{SETTINGS_VIEWER_EMPTY.replace('{book}', book?.name ?? '')}</p>;
  return (
    <div className="screen settings">
      {/* On a phone a section's page has the way back above the title, as every other page does. */}
      {!wide && Page && sections.length > 0 && <Link className="settings__back" to="/settings"><ChevronLeft size={20} aria-hidden="true" />{BACK_TO_SETTINGS}</Link>}
      <h1>{SETTINGS_FOR.replace('{book}', book?.name ?? '')}</h1>
      {wide ? (
        sections.length ? (
          <div className="settings__wide">
            <nav className="sgroups" aria-label="Settings sections"><Groups sections={sections} current={chosen?.slug} wide /></nav>
            <div className="settings__page"><InSettingsColumn.Provider value>{Page && <Page />}</InSettingsColumn.Provider></div>
          </div>
        ) : Page ? <Page /> : empty
      ) : Page ? (
        <Page />
      ) : sections.length ? (
        <nav className="settings__groups" aria-label="Settings list"><Groups sections={sections} wide={false} /></nav>
      ) : empty}
    </div>
  );
}
