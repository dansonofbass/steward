import type { ReactNode } from 'react';
import './Notice.css';

/** Inline only. It stays until the state that caused it changes; it never dismisses itself. */
export function Notice({ tone = 'info', children }: { tone?: 'info' | 'warn' | 'error'; children: ReactNode }) {
  return (
    <div className={`notice notice--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </div>
  );
}
