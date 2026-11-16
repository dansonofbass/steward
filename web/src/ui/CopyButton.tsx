import type { LucideIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { COPIED_IT, COPY_FAILED } from '../lib/copy';
import { Button } from './Button';
import './CopyButton.css';

export const COPY_NOTE_MS = 2000;

type Props = {
  text: string;
  /** The button's word; it stays the same, and the note beside it says what happened. */
  label: string;
  icon?: LucideIcon;
  variant?: 'primary' | 'quiet';
  /** What the note says when the copy fails; the button's own fallback (selecting the text) runs first. */
  failed?: string;
  onFail?: () => void;
};

/** WEB-21: a Copy button whose result is said and shown. The note beside it is a status that is in the page, empty,
 *  before the press (a live region inside a button isn't read), and says both outcomes: Copied, or that it couldn't.
 *  It empties after two seconds, so no stale "Copied" is left to find; a second press says it again. */
export function CopyButton({ text, label, icon, variant = 'quiet', failed = COPY_FAILED, onFail }: Props) {
  const [note, setNote] = useState('');
  const timer = useRef<number | undefined>(undefined);
  const last = useRef({ text: '', alt: false });
  useEffect(() => () => window.clearTimeout(timer.current), []);
  async function copy() {
    let ok = true;
    try {
      await navigator.clipboard.writeText(text);   // no clipboard (plain http) throws here too
    } catch {
      ok = false;
      onFail?.();
    }
    const said = ok ? COPIED_IT : failed;
    // VoiceOver skips a note the same as the last; a no-break space makes it differ and isn't read.
    const alt = said === last.current.text ? !last.current.alt : false;
    last.current = { text: said, alt };
    setNote(alt ? `${said} ` : said);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setNote(''), COPY_NOTE_MS);
  }
  return (
    <span className="copy">
      <Button variant={variant} icon={icon} onClick={() => void copy()}>{label}</Button>
      <span className="copy__note small" role="status">{note}</span>
    </span>
  );
}
