import { useQuery } from '@tanstack/react-query';
import { api, del, json, put } from '../../api/client';

export type Status = 'done' | 'needs' | 'optional';
export type BootLine = { name: string; line: string; running: string | null; note: string | null; where: 'steward' | 'gateway' };
export type RowKey = 'household' | 'money' | 'ask' | 'email' | 'backups' | 'someone' | 'address' | 'key';
export type ReadyRow = { key: RowKey; status: Status; detail: string; go: string | null; lines: BootLine[]; extra: Record<string, unknown> };
export type Ready = { rows: ReadyRow[]; need: number };
export type Source = 'env' | 'app' | 'default';
type Owned<T> = { value: T; source: Source; env: string };
export type InstallSettings = {
  email: { source: Source; env: string; host: string; port: number; user: string; from: string; password_set: boolean; password_unreadable: boolean };
  backups: { at: Owned<string>; ping_url: { set: boolean; shown: string | null; source: Source; env: string }; dir: string };
  general: { timezone: Owned<string> & { running: string }; gateway_name: Owned<string> };
};

export const useReady = () => useQuery({ queryKey: ['ready'], refetchOnWindowFocus: true,
  queryFn: () => api<Ready>(`/api/ready?origin=${encodeURIComponent(window.location.origin)}`) });
export const useInstallSettings = () => useQuery({ queryKey: ['install', 'settings'], queryFn: () => api<InstallSettings>('/api/install/settings') });
export const saveEmail = (b: { host: string; port: number; user: string; from: string; password?: string }) => api<InstallSettings>('/api/install/settings/email', put(b));
export const removeEmail = () => api<InstallSettings>('/api/install/settings/email', del());
export const saveBackups = (b: { at?: string | null; ping_url?: string | null }) => api<InstallSettings>('/api/install/settings/backups', put(b));
export const saveGeneral = (b: { timezone?: string | null; gateway_name?: string | null }) => api<InstallSettings>('/api/install/settings/general', put(b));
export const sendTest = () => api<{ line: string }>('/api/install/email/test', json({}));
export const pairCode = (code: string) => api<{ line: string }>('/api/install/gateway/pair', json({ code }));
