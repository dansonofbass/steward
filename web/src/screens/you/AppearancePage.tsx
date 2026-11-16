import { S_APPEARANCE } from '../../lib/copy';
import { AppearanceOptions } from '../settings/Appearance';

export default function AppearancePage() {
  return (
    <div className="screen">
      <h1>{S_APPEARANCE}</h1>
      <div className="spage"><AppearanceOptions /></div>
    </div>
  );
}
