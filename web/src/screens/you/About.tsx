import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { S_ABOUT } from '../../lib/copy';
import { NotAdvice } from '../../ui/NotAdvice';
import { LICENSE_LINE, NOT_AFFILIATED, SITE_URL, SOURCE, SOURCE_URL, VERSION } from './aboutCopy';

/** You › About Steward: the version, the not-advice line, the license and where the source is. */
export default function About() {
  const health = useQuery({ queryKey: ['health'], queryFn: () => api<{ ok: boolean; version: string }>('/api/health'), retry: false });
  return (
    <div className="screen">
      <h1>{S_ABOUT}</h1>
      <div className="card stack">
        {health.data && <p>{VERSION.replace('{version}', health.data.version)}</p>}
        <NotAdvice />
        <p>{LICENSE_LINE} <a className="link" href={SOURCE_URL} rel="noreferrer">{SOURCE}</a></p>
        <p>{NOT_AFFILIATED}</p>
        <p><a className="link" href={SITE_URL} rel="noreferrer">{SITE_URL.replace('https://', '')}</a></p>
      </div>
    </div>
  );
}
