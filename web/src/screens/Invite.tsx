import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { api, json } from '../api/client';
import type { Me } from '../api/types';
import { bookHref } from '../book/BookContext';
import { HOME, INVITE_HEADING, INVITE_JOINED_NO_BOOKS, INVITE_NO_TOKEN, INVITE_WORKING } from '../lib/copy';
import { Notice } from '../ui/Notice';
import { failure } from './settings/shared';

/** An invitation link (spec 2.7, Task 9.5). Signed-out visitors are sent to sign-in by RequireAuth and come back
 *  here; once signed in, the token is accepted once and the person lands in the book. */
export default function Invite() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [error, setError] = useState(token ? '' : INVITE_NO_TOKEN);
  const [joinedNote, setJoinedNote] = useState('');   // the accept worked; only the books refresh failed
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return; // a token works once, so never send it twice
    started.current = true;
    (async () => {
      let joined: { slug: string; name: string };
      try {
        joined = (await api<{ book: { slug: string; name: string } }>('/api/invites/accept', json({ token }))).book;
      } catch (e) {
        setError(failure(e));
        return;
      }
      // BookScope sends an unknown book to another one, so the new book must be in the list first.
      try {
        await qc.fetchQuery({ queryKey: ['me'], queryFn: () => api<Me>('/api/auth/me'), staleTime: 0 });
      } catch {
        // The accept worked: say so, rather than showing an error for a person who is in.
        setJoinedNote(INVITE_JOINED_NO_BOOKS.replace('{book}', joined.name));
        return;
      }
      navigate(bookHref(joined.slug, '/'), { replace: true, state: { joined: joined.name } });
    })();
  }, [token, qc, navigate]);

  return (
    <main className="screen" aria-busy={!error && !joinedNote}>
      <h1>{INVITE_HEADING}</h1>
      {joinedNote
        ? <><Notice tone="warn">{joinedNote}</Notice><p><Link to="/">{HOME}</Link></p></>
        : error
        ? <><Notice tone="error">{error}</Notice><p><Link to="/">{HOME}</Link></p></>
        : <p className="muted">{INVITE_WORKING}</p>}
    </main>
  );
}
