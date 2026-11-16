import { GraduationCap } from 'lucide-react';
import { useChildren } from '../../../api/household';
import { joinNames } from '../joinNames';
import { STEP_COVER, STEP_KIDS, STEP_PLANS } from '../copy';
import type { SectionDef } from '../sections';
import { Cover } from './Cover';
import { KidsCard } from './KidsCard';
import { KidsList } from './KidsList';
import { Plans } from './Plans';

function useKidsSummary(): string[] | null {
  const kids = useChildren().data;
  return kids ? [joinNames(kids.children.map((k) => k.label))] : null;
}

/** Profile's second section (decision 2): three steps, and a card of its own. */
export const KIDS_SECTION: SectionDef = {
  icon: GraduationCap,
  steps: [
    { key: 'kids', title: () => STEP_KIDS, Body: KidsList },
    { key: 'cover', title: () => STEP_COVER, Body: Cover },
    { key: 'plans', title: () => STEP_PLANS, Body: Plans },
  ],
  Card: KidsCard,
  useSummary: useKidsSummary,
};
