import { useQuery } from '@tanstack/react-query';
import type { MilestoneKey } from '../lib/lines';
import { api, json } from './client';

/** GET /api/growth (phase 17 spec 3.4): the book's stage 0 to 5, its five milestones in order, and whether this person
 *  has seen this stage. Warmed with Home's other requests (routes.tsx HOME_WARM): same key, path and options. */
export type Growth = { stage: number; milestones: { key: MilestoneKey; met: boolean; month?: string }[]; seen: boolean };
export const GROWTH_PATH = '/api/growth';
export const GROWTH_OPTIONS = { retry: false, staleTime: 60_000 } as const;
export const useGrowth = (enabled = true) =>
  useQuery({ queryKey: ['growth'], queryFn: () => api<Growth>(GROWTH_PATH), ...GROWTH_OPTIONS, enabled });
/** POST /api/growth/seen: Home showed this person this stage. */
export const seeGrowth = (stage: number) => api<void>('/api/growth/seen', json({ stage }));
