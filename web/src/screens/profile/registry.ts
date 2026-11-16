import type { SectionKey } from '../../lib/profileSections';
import { BANKS_SECTION } from './banks/Banks';
import { BENEFITS_SECTION } from './benefits/Benefits';
import { HOME_SECTION } from './home/HomeCars';
import { KIDS_SECTION } from './kids/Kids';
import type { SectionDef } from './sections';
import { YOU_SECTION } from './you/You';

/** Each section's flow and card. */
export const SECTIONS: Record<SectionKey, SectionDef> = {
  you: YOU_SECTION, kids: KIDS_SECTION, home: HOME_SECTION, benefits: BENEFITS_SECTION, banks: BANKS_SECTION,
};
