import type { PlanLevel } from '../api/household';

/** The Plan's college levels (the engine's four; Profile's Not sure yet is costed as in-state public). */
export const LEVEL_NAME: Record<PlanLevel, string> = {
  two_year: 'Trade or community college', in_state_public: 'In-state public', out_of_state_public: 'Out-of-state public', private: 'Private',
};
export const LEVELS: PlanLevel[] = ['two_year', 'in_state_public', 'out_of_state_public', 'private'];
