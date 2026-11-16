// The first-use tip (Ask about this P23): beside What Claude will see, with Got it. Not modal, and it takes no focus:
// the box points to it with aria-describedby. While the gateway is away or paused there is no live preview, so it shows
// mockup 4's example with the same chips.
import { Button } from '../../ui/Button';
import type { Chip } from './askApi';
import { ChipText } from './Chip';
import * as C from './copy';

const chip = (label: string): Chip => {
  const start = C.TOUR_EXAMPLE_SENT.indexOf(label);
  return { start, end: start + label.length, label, layer: 'steward' };
};
const EXAMPLE_CHIPS = ['Person 2', 'Payee 4', 'Account 2'].map(chip);
const EXAMPLE_LABELS = { 'Person 2': 'Sam', 'Payee 4': 'Costco', 'Account 2': 'Chase card' };

export function TourTip({ id, chips, example, onDone }: { id: string; chips: boolean; example: boolean; onDone: () => void }) {
  return (
    <div id={id} className="ask-tour" role="note" data-testid="ask-tour">
      <p>{C.TOUR}{chips || example ? ` ${C.TOUR_TAP}` : ''}</p>
      {example && (
        <div className="ask-tour__example">
          <span className="eyebrow">{C.TOUR_EXAMPLE}</span>
          <span className="small muted">{C.TOUR_EXAMPLE_ASKED}</span>
          <ChipText text={C.TOUR_EXAMPLE_SENT} chips={EXAMPLE_CHIPS} labels={EXAMPLE_LABELS} />
        </div>
      )}
      <Button variant="quiet" onClick={onDone}>{C.GOT_IT}</Button>
    </div>
  );
}
