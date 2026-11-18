import type { ReactNode } from 'react';
import './EmptyState.css';

/** Nothing to show yet. Its title is a sentence about the state, not a heading, so a screen reader moving by headings
 *  never lands on it (issue #21). `page`: the empty state is the whole screen (no book to open), so its title is the
 *  screen's one level 1 heading. */
export function EmptyState({ title, body, action, page = false }: { title: string; body?: string; action?: ReactNode; page?: boolean }) {
  const Title = page ? 'h1' : 'p';
  return (
    <div className="empty">
      <Title className="empty__title">{title}</Title>
      {body && <p className="empty__body">{body}</p>}
      {action && <div className="empty__action">{action}</div>}
    </div>
  );
}
