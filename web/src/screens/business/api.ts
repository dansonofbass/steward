import { useQuery } from '@tanstack/react-query';
import { api, put } from '../../api/client';
import type { BusinessType } from '../../api/types';

export type HomeOfficeOut = { method: 'none' | 'simplified' | 'actual'; office_sqft: number; home_sqft: number; home_costs_cents: number };
export type MilesOut = { from: string; to: string; rate_tenths: number; miles: number };
export type BusinessSettingsOut = {
  year: number; this_year: number; type: BusinessType; home_office: HomeOfficeOut; car_method: 'standard' | 'actual'; miles: MilesOut[];
  expect: { low_cents: number; high_cents: number } | null; s_corp: { salary_pct: number; cost_cents: number };
  /** Who runs the business, one of `adults` (final review ruling I2). */
  owner: 'jr' | 'spouse'; adults: { key: 'jr' | 'spouse'; name: string }[];
  rules: { year: number; using_note: string | null; home_office_rate_cents: number; home_office_max_sqft: number; meals_pct: number };
};

export const saveBusinessSettings = (body: Record<string, unknown>) => api<BusinessSettingsOut>('/api/business/settings', put(body));
/** With no year, the household's this year (final review M6). */
export const businessSettingsKey = (year: number | null) => ['business', year ?? 'now', 'settings'];
export const useBusinessSettings = (year: number | null) =>
  useQuery({
    queryKey: businessSettingsKey(year),
    queryFn: () => api<BusinessSettingsOut>(year === null ? '/api/business/settings' : `/api/business/settings?year=${year}`),
  });
