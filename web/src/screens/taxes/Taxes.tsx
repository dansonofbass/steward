import { usePlanSetup } from '../../api/household';
import { NotAdvice } from '../../ui/NotAdvice';
import * as C from './copy';
import { PlansCard } from './PlansCard';
import { QuarterlyCard } from './QuarterlyCard';
import { RothCard } from './RothCard';
import { PlanTabs } from '../plan/PlanTabs';
import './taxes.css';

/** Spec 7: the household's Taxes page (ruling 1). Loaded on demand; household books only (routes.tsx). */
export default function Taxes() {
  const setup = usePlanSetup();                      // the row hides the plan pages while setup is unfinished
  return (
    <div className="screen taxes">
      <PlanTabs on="taxes" ready={setup.data?.ready ?? true} />
      <h1>{C.TAXES_TITLE}</h1>
      <div className="tax-cols">
        <div><QuarterlyCard /></div>
        <div><PlansCard /><RothCard /></div>
      </div>
      <NotAdvice />
    </div>
  );
}
