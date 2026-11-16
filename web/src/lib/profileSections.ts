// Profile's five sections in JR's order (profile spec, P1-P4) and their guided flows' step keys (the server's
// services/profile.SECTION_STEPS). Eager: Home's line, the Plan's checklist and the old setup addresses read these.
export type SectionKey = 'you' | 'kids' | 'home' | 'benefits' | 'banks';
export type SectionStatus = 'done' | 'skipped' | 'doesnt_apply' | 'todo';

export const SECTION_ORDER: SectionKey[] = ['you', 'kids', 'home', 'benefits', 'banks'];
export const SECTION_NAME: Record<SectionKey, string> = {
  you: 'You and your partner', kids: 'Kids and college', home: 'Home and cars',
  benefits: 'Social Security and Medicare', banks: 'Banks and accounts',
};
export const SECTION_STEPS: Record<SectionKey, string[]> = {
  you: ['you', 'partner', 'taxes', 'pay'], kids: ['kids', 'cover', 'plans'], home: ['own', 'homes', 'mortgages', 'cars'],
  benefits: ['ss', 'health'], banks: ['link', 'types', 'history'],
};

export const isFinished = (s: SectionStatus): boolean => s === 'done' || s === 'doesnt_apply';
export const isSection = (s: string | undefined): s is SectionKey => SECTION_ORDER.includes(s as SectionKey);
export const sectionPath = (key: SectionKey, step?: string | null, from?: 'plan'): string =>
  `/profile/${key}${step ? `/${step}` : ''}${from ? `?from=${from}` : ''}`;

/** The Plan's setup items (services/plan_inputs.setup_items) and the section that answers each (P7); Spending history has none. */
export const PLAN_ITEM_SECTION: Partial<Record<string, SectionKey>> = {
  household: 'you', pay: 'you', children: 'kids', mortgage: 'home', health: 'benefits', earnings: 'benefits', earnings_spouse: 'benefits',
};
/** Set up Steward's old step keys, for the old /setup/{step} and /settings/profile/{step} addresses (P1, P2). */
export const OLD_STEP_SECTION: Record<string, SectionKey> = {
  about: 'you', pay: 'you', children: 'kids', home: 'home', health: 'benefits', earnings: 'benefits', banks: 'banks',
};
