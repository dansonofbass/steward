// Settings → Chat → Claude Code (src/steward/api/grants.py).
import { useQuery } from '@tanstack/react-query';
import { api, json } from '../../api/client';

export type Grant = { id: number; person: string; issued_by: string; issued: string; state: 'active' | 'revoked' | 'expired'; line: string; can_revoke: boolean };
export type Grants = { grants: Grant[]; can_issue: boolean; days: number };
export type Issued = { grant: string; command: string; row: Grant };

const base = (slug: string) => `/api/b/${encodeURIComponent(slug)}/chat/grants`;
export const useGrants = (slug: string) => useQuery({ queryKey: ['chat', 'grants-of', slug], queryFn: () => api<Grants>(base(slug)) });
// A grant is always for the signed-in manager (final review M6).
export const issueGrant = (slug: string) => api<Issued>(base(slug), json({}));
export const revokeGrant = (slug: string, id: number) => api<{ row: Grant }>(`${base(slug)}/${id}/revoke`, json({}));
