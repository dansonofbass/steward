import { useQueryClient } from '@tanstack/react-query';
import { ClipboardList, Contrast, Info, LogOut, MonitorSmartphone, Settings as SettingsIcon, type LucideIcon } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import { useMe } from '../api/hooks';
import type { BookSummary } from '../api/types';
import { useBook } from '../book/BookContext';
import { Link } from '../book/links';
import { forgetSignedOut } from '../lib/signedOut';
import { anchoredStyle, anchorName, anchorStyle, canAnchor, canPopover, hide, invokerProps, placeByTrigger, usePopoverOpen } from '../lib/popover';
import { HELP, S_ABOUT, S_APPEARANCE, S_PROFILE, SETTINGS_FOR, SIGN_IN_AND_DEVICES, SIGN_OUT, SIGN_OUT_HERE_BODY, SIGN_OUT_HERE_TITLE, YOU } from '../lib/copy';
import { settingsVisible } from '../screens/settings/sections';
import { failure } from '../screens/settings/shared';
import { ConfirmSheet } from '../ui/ConfirmSheet';
import { BACK_TO_OPENER } from '../lib/useRemoval';
import { Sheet } from '../ui/Sheet';
import { initials } from './initials';
import './YouMenu.css';

export type YouRow = { key: string; label: string; icon: LucideIcon; to?: string };

/** The You menu's rows in order (decision 4). A row with `to` is a link in the open book; Sign out has none. */
export function youRows(book: BookSummary, hasSettings: boolean): YouRow[] {
  return [
    ...(book.kind === 'household' ? [{ key: 'profile', label: S_PROFILE, icon: ClipboardList, to: '/profile' }] : []),
    ...(hasSettings ? [{ key: 'settings', label: SETTINGS_FOR.replace('{book}', book.name), icon: SettingsIcon, to: '/settings' }] : []),
    { key: 'devices', label: SIGN_IN_AND_DEVICES, icon: MonitorSmartphone, to: '/you/devices' },
    { key: 'appearance', label: S_APPEARANCE, icon: Contrast, to: '/you/appearance' },
    // Info, not a new icon: the first download already carries it (Log), and the entry stays as it was (spec 11).
    { key: 'help', label: HELP, icon: Info, to: '/you/help' },
    { key: 'about', label: S_ABOUT, icon: Info, to: '/you/about' },
    { key: 'sign-out', label: SIGN_OUT, icon: LogOut },
  ];
}

function Rows({ rows, onPick, onSignOut }: { rows: YouRow[]; onPick: () => void; onSignOut: () => void }) {
  return (
    <ul className="you__list">
      {rows.map(({ key, label, icon: Icon, to }) => (
        <li key={key}>
          {to
            ? <Link className="you__row" to={to} onClick={onPick}><Icon size={20} aria-hidden="true" /><span>{label}</span></Link>
            : <button type="button" className="you__row" onClick={onSignOut}><Icon size={20} aria-hidden="true" /><span>{label}</span></button>}
        </li>
      ))}
    </ul>
  );
}

/** The person's initials, on every screen (decision 4): in the phone's top bar (a bottom sheet) and at the foot of the
 *  laptop rail, with the name beside them (a menu above the button). */
export function YouMenu({ variant }: { variant: 'bar' | 'rail' }) {
  const book = useBook();
  const me = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const [panel, setPanel] = useState<HTMLDivElement | null>(null);
  const menuId = useId();
  const anchor = anchorName(menuId);
  // The rail's menu is a popover (issue #27): the browser opens it from the initials and closes it on a press or tap
  // outside, or Escape. Without anchor positioning it is placed from the initials' box as it opens; without popovers
  // (or in a test), it is mounted while open and these listeners close it.
  const popover = variant === 'rail' && canPopover();
  const popoverOpen = usePopoverOpen(popover ? panel : null, {
    before: () => { if (panel && button.current && !canAnchor()) placeByTrigger(panel, button.current, 'above', 'stretch'); },
    // Closed with focus inside (Escape, a pick): focus goes back to the initials, as the browser does for an invoker.
    after: (now) => { if (!now && (document.activeElement === document.body || panel?.contains(document.activeElement))) button.current?.focus(); },
  });
  const open = variant === 'rail' && popover ? popoverOpen : sheetOpen;

  useEffect(() => {
    if (!open || variant !== 'rail' || popover) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setSheetOpen(false); button.current?.focus(); } };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panel?.contains(t) && !button.current?.contains(t)) setSheetOpen(false);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown); };
  }, [open, variant, popover, panel]);

  if (!book || !me.data) return null;
  const { user } = me.data;
  const name = user.display_name.trim() || user.username;
  const close = () => { if (popover) hide(panel); else setSheetOpen(false); };
  // The rail's menu hides its Sign out button; focus moves to the initials first, so the confirm gives it back there.
  const askSignOut = () => { button.current?.focus(); close(); setError(null); setConfirming(true); };

  // The same as signing out this device from Sign-in and devices.
  async function signOut() {
    setBusy(true);
    setError(null);
    try {
      await api('/api/auth/logout', { method: 'POST' });
      queryClient.clear();
      forgetSignedOut(); // the next person on this tab sees none of this person's draft, cheers or switches
      navigate('/login', { replace: true });
    } catch (e) {
      setError(failure(e));
      setBusy(false);
    }
  }

  const content = (
    <>
      {user.email && <p className="muted you__email">{user.email}</p>}
      <Rows rows={youRows(book, settingsVisible(book, me.data))} onPick={close} onSignOut={askSignOut} />
    </>
  );
  return (
    <div className={`you you--${variant}`}>
      <button ref={button} type="button" className="you__btn" aria-label={`${YOU}: ${name}`} aria-expanded={open}
        aria-controls={variant === 'rail' && open ? menuId : undefined} style={popover ? anchorStyle(anchor) : undefined}
        {...(popover ? invokerProps(menuId) : { onClick: () => setSheetOpen((o) => !o) })}>
        {/* The initials are drawn from the attribute, so the button's visible words are its name's (WCAG 2.5.3, T7). */}
        <span className="you__initials" aria-hidden="true" data-initials={initials(user.display_name, user.username)} />
        {variant === 'rail' && <span className="you__name">{name}</span>}
      </button>
      {variant === 'rail' && (popover || open) && (
        <div ref={setPanel} id={menuId} role="dialog" aria-label={name} className="you__menu"
          {...(popover ? { popover: 'auto' as const, style: anchoredStyle(anchor) } : {})}>{content}</div>
      )}
      {variant === 'bar' && <Sheet open={open} onClose={close} title={name}>{content}</Sheet>}
      <ConfirmSheet open={confirming} title={SIGN_OUT_HERE_TITLE} body={SIGN_OUT_HERE_BODY} action={SIGN_OUT} variant="danger"
        busy={busy} error={error} onConfirm={() => void signOut()} onClose={() => setConfirming(false)} returnTo={BACK_TO_OPENER} />
    </div>
  );
}
