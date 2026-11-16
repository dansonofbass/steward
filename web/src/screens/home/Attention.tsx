import { useMutation, useQueryClient } from '@tanstack/react-query';
import { TriangleAlert } from 'lucide-react';
import { useCanEdit } from '../../book/BookContext';
import { Link } from '../../book/links';
import { api } from '../../api/client';
import type { Summary } from '../../api/types';
import { ATTENTION_VIEWER, DISMISS, GO_TO_SETTINGS, NEEDS_A_LOOK } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import './attention.css';

type Item = Summary['needs_attention'][number];

function Row({ item, canEdit }: { item: Item; canEdit: boolean }) {
  const qc = useQueryClient();
  const resolve = useMutation({
    mutationFn: () => api<void>(`/api/events/${item.id}/resolve`, { method: 'POST' }),
    onSuccess: () => Promise.all([qc.invalidateQueries({ queryKey: ['summary'] }), qc.invalidateQueries({ queryKey: ['events'] })]),
  });
  const to = '/settings/banks'; // bank problems and new-account setup (type and owner) both live on Banks
  return (
    <li className="attention__item">
      <span>{item.message}</span>
      {canEdit && (
        <span className="attention__actions">
          <Link to={to}>{GO_TO_SETTINGS}</Link>
          <Button variant="quiet" busy={resolve.isPending} aria-label={`${DISMISS}: ${item.message}`} onClick={() => resolve.mutate()}>{DISMISS}</Button>
        </span>
      )}
      {resolve.isError && <span role="alert" className="muted">{resolve.error.message}</span>}
    </li>
  );
}

export function Attention({ items }: { items: Item[] }) {
  const canEdit = useCanEdit();   // Banks and dismissing are a manager's; a viewer reads the rows
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="attention-h">
      <Notice tone="warn">
        <div className="attention">
          <TriangleAlert className="attention__icon" size={20} aria-hidden="true" />
          <div className="attention__body">
            <h2 id="attention-h" className="eyebrow">{NEEDS_A_LOOK}</h2>
            <ul className="attention__list">{items.map((i) => <Row key={i.id} item={i} canEdit={canEdit} />)}</ul>
            {!canEdit && <p className="small muted">{ATTENTION_VIEWER}</p>}
          </div>
        </div>
      </Notice>
    </section>
  );
}
