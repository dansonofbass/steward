import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { LEDE } from '../lib/copy';
import { Mark } from '../ui/Mark';
import './Auth.css';

/** Shared frame for sign-in, forgot and reset. Sign-in shows the mark and the wordmark above the card; the others show
 *  a small wordmark and their own heading inside it. */
export function AuthPanel({ heading, lede, children }: { heading?: string; lede?: string; children: ReactNode }) {
  return (
    <main className="login">
      {!heading && (
        <div className="login__brand">
          <Mark size={64} />
          <h1 className="wordmark">Steward</h1>
        </div>
      )}
      <div className="login__panel login__panel--card">
        <header>
          {heading && (
            <>
              <p className="wordmark wordmark--small"><Link to="/login">Steward</Link></p>
              <h1 className="login__heading">{heading}</h1>
            </>
          )}
          <p className="login__lede">{lede ?? LEDE}</p>
        </header>
        {children}
      </div>
    </main>
  );
}

/** Only same-origin paths: it must start with one slash and not be protocol-relative. */
export function safeNext(next: string | null): string {
  return next && next.startsWith('/') && !next.startsWith('//') && !next.startsWith('/\\') ? next : '/';
}
