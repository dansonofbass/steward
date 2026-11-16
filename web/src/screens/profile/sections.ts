import type { LucideIcon } from 'lucide-react';
import type { QueryClient } from '@tanstack/react-query';
import type { ComponentType } from 'react';
import type { Names } from '../../api/household';
import type { ProfileState, SectionState } from '../../api/profile';
import { dateLabel, localYmd } from '../../lib/format';
import { SAVED_BY } from './copy';

export type BodyProps = { profile: ProfileState };
export type StepDef = {
  key: string;
  title: (names: Names, profile: ProfileState) => string;
  Body: ComponentType<BodyProps>;
  /** Runs on Done, before the section is answered (Social Security and Medicare confirms the premium estimate). A returned token keeps the flow here with Undo.. */
  beforeDone?: (profile: ProfileState) => Promise<{ text: string; token: string } | void>;
  /** True: the flow passes over this step, both ways (Home and cars' No skips to Cars, spec Step 1). */
  skip?: (qc: QueryClient) => boolean;
};
export type SectionDef = {
  icon: LucideIcon;
  steps: StepDef[];
  /** A card of its own; without one, the card is the steps' bodies, each under its title. */
  Card?: ComponentType<BodyProps>;
  /** The card's summary lines; the Profile row shows the first. Null while loading. */
  useSummary: (profile: ProfileState) => string[] | null;
};

/** Decision 2 of onboarding, kept: You and your partner was finished by someone else and this person hasn't confirmed. */
export function confirmOnly(p: ProfileState): boolean {
  const you = p.sections.find((s) => s.key === 'you')!;
  return p.me.role !== null && !p.me.confirmed && you.status === 'done' && you.by_id !== null && you.by_id !== p.me.user_id;
}

/** "Saved Oct 14 by JR" for a section someone finished; null when it is done from the data alone. */
export function savedByLine(s: SectionState, today: Date): string | null {
  if (s.status !== 'done' || !s.by || !s.at) return null;
  return SAVED_BY.replace('{date}', dateLabel(localYmd(s.at), today)).replace('{name}', s.by);
}
