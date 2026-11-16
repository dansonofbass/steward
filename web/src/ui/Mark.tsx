import { MARK, markSizeFor, tileRadius } from './markArt';
import './Mark.css';

type Props = { size: number; label?: string; className?: string };

/** Steward's mark, an acorn with its leaf on a rounded plum tile, inline. `size` is in CSS pixels and picks the
 *  drawing tuned for it (below 20 the pixel-aligned 16 grid one, otherwise the 32 grid one). The tile is the accent in
 *  light skies and #93446A in dark ones; the acorn a light tint (white in the dark), the leaf a softer one: tokens.css
 *  sets --mark-*. Decorative unless `label` is given. */
export function Mark({ size, label, className }: Props) {
  const which = markSizeFor(size);
  const a = MARK[which];
  return (
    <svg className={`brand-mark${className ? ` ${className}` : ''}`} data-size={which} width={size} height={size} viewBox={`0 0 ${a.grid} ${a.grid}`}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true, focusable: false })}>
      <rect className="brand-mark__tile" width={a.grid} height={a.grid} rx={tileRadius(a.grid)} />
      {a.parts.map((p) => (p.fill
        ? <path key={p.d} className={`brand-mark__${p.fill}`} d={p.d} />
        : <path key={p.d} className={`brand-mark__${p.stroke}-line`} d={p.d} fill="none" strokeWidth={p.width} strokeLinecap="round" />))}
    </svg>
  );
}
