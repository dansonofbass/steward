import { Pencil, Plus } from 'lucide-react';
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useChildren } from '../../../api/household';
import { Link } from '../../../book/links';
import { sectionPath } from '../../../lib/profileSections';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { ADD_KID, EDIT, KID_CARD, KID_CARD_SUB, LIVING_WORD, NO_529, SCHOOLS } from '../copy';
import { useFieldMode } from '../field';
import type { BodyProps } from '../sections';
import { KidCover, useLine, choiceOf } from './Cover';
import { KidPlan } from './Plans';

/** One row per kid (spec, The card): who, what you plan to cover and their 529, the consequence line, and a pencil
 *  that opens that kid's fields in place. */
export function KidsCard(_: BodyProps) {
  const kids = useChildren();
  const { canEdit } = useFieldMode();
  const [params] = useSearchParams();
  const fromPlan = params.get('from') === 'plan';
  const [open, setOpen] = useState<number | null>(null);
  if (kids.error) return <Notice tone="error">{kids.error.message}</Notice>;
  if (!kids.data) return <Skeleton lines={4} />;
  const data = kids.data;
  return (
    <div className="stack">
      {data.children.length > 0 && (
        <ul className="plain stack">
          {data.children.map((k) => {
            const plan = data.plans.find((p) => p.account_id === k.account_id);
            return (
              <li key={k.id} className="card prof-card__step">
                <div className="prof-value">
                  <span className="prof-value__text"><strong>{KID_CARD.replace('{name}', k.label).replace('{year}', String(k.birth_year))}</strong></span>
                  <span className="prof-value__label">{KID_CARD_SUB.replace('{school}', SCHOOLS[k.cost_level]).replace('{share}', String(k.share_pct))
                    .replace('{living}', k.covers_living ? LIVING_WORD.in : LIVING_WORD.out).replace('{plan}', plan?.name ?? NO_529)}</span>
                  {canEdit && (
                    <button type="button" className="prof-icon-btn" aria-label={`${EDIT} ${k.label}`} aria-expanded={open === k.id}
                      onClick={() => setOpen(open === k.id ? null : k.id)}><Pencil size={20} aria-hidden="true" /></button>
                  )}
                </div>
                <Line kidId={k.id} />
                {open === k.id && <><KidCover kid={k} table={data.college} /><KidPlan kid={k} data={data} /></>}
              </li>
            );
          })}
        </ul>
      )}
      {canEdit && (      // the Kids step adds a kid (with Undo), and is the way back in after No kids
        <div className="ob-form-actions">
          <Link className="btn btn--quiet" to={sectionPath('kids', 'kids', fromPlan ? 'plan' : undefined)}>
            <span className="btn__content"><Plus size={20} aria-hidden="true" /><span>{ADD_KID}</span></span>
          </Link>
        </div>
      )}
    </div>
  );
}

function Line({ kidId }: { kidId: number }) {
  const data = useChildren().data!;
  const k = data.children.find((c) => c.id === kidId)!;
  return <p className="kid-line">{useLine(choiceOf(k), k.label, k.account_id !== null, data.college)}</p>;
}
