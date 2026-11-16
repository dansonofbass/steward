import { TriangleAlert } from 'lucide-react';
import { Link } from '../../book/links';
import type { OverLine } from '../../lib/spendingLine';
import './overline.css';

/** The over-target line (decision 2, P15): on Home under "this month so far", and atop Spending's Flexible section.
 *  The triangle only when a category is clearly over, in amber; never red. Each link opens its category. */
export function OverLineView({ line }: { line: OverLine }) {
  return (
    <p className={`overline is-${line.tone}`} data-testid="over-line">
      {line.tone === 'amber' && <TriangleAlert className="i" size={20} aria-hidden="true" />}
      <span>{line.bits.map((b, i) => (b.to
        ? <Link key={i} className="link overline__link" to={b.to}>{b.text}</Link>
        : <span key={i}>{b.text}</span>))}</span>
    </p>
  );
}
