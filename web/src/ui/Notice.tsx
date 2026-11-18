import { useRef, type ReactNode } from 'react';
import { useSayShown } from './Live';
import './Notice.css';

/** Inline only. It stays until the state that caused it changes; it never dismisses itself. An error is an alert. An
 *  info or warn notice is not a live region of its own (one that appears with its text in it is often not read, issue
 *  #23): its words are said through the page's polite region when it appears and when they change. */
export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode }) {
  const el = useRef<HTMLDivElement>(null);
  useSayShown(el, tone !== 'error');
  return (
    <div ref={el} className={`notice notice--${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      {children}
    </div>
  );
}
