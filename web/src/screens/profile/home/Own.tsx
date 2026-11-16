import { useQueryClient } from '@tanstack/react-query';
import { Link } from '../../../book/links';
import { Notice } from '../../../ui/Notice';
import { Skeleton } from '../../../ui/Skeleton';
import { saveFact, useProfileHome, type HomeData } from '../api';
import { NO, OPEN_MORTGAGE, OWN, YES } from '../copy';
import { ProfileField } from '../field';
import type { BodyProps } from '../sections';

export const ownsNo = (h: HomeData | undefined) => h?.owns_home === false;

/** Every active mortgage: the ones on a property and the ones on none. */
export const openMortgages = (h: HomeData) => [...h.properties.flatMap((p) => (p.mortgage ? [p.mortgage] : [])), ...h.mortgages];

export function Own(_: BodyProps) {
  const home = useProfileHome();
  const qc = useQueryClient();
  if (home.error) return <Notice tone="error">{home.error.message}</Notice>;
  if (!home.data) return <Skeleton lines={2} />;
  const h = home.data;
  const answer = h.owns_home === null ? '' : h.owns_home ? 'yes' : 'no';
  return (
    <div className="stack">
      <ProfileField label={OWN} input="radios" text={answer} shown={answer === 'yes' ? YES : answer === 'no' ? NO : ''}
        options={[{ value: 'yes', label: YES }, { value: 'no', label: NO }]} check={(t) => (t ? null : OWN)}
        save={async (t) => { const token = await saveFact('home.owns', t); await qc.invalidateQueries({ queryKey: ['profile-home'] }); return token; }} />
      {ownsNo(h) && openMortgages(h).map((m) => (
        <Notice key={m.account_id} tone="warn">
          <Link className="link" to={`/accounts/${m.account_id}`}>{OPEN_MORTGAGE.replace('{mortgage}', m.name)}</Link>
        </Notice>
      ))}
    </div>
  );
}
