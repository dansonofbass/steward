import { Link } from '../../book/links';
import type { ChangeRow } from './api';

/** "Robin edited <Homeowners>": the server's text with its one {item} turned into a link to the item. */
export function ChangeText({ row }: { row: ChangeRow }) {
  const [before, after = ''] = row.text.split('{item}');
  return (
    <span>
      {row.who && <><span className="chg__who">{row.who}</span>{' '}</>}
      {before}
      {row.item && <Link to={row.item.path ?? `/inventory/${row.item.id}`}>{row.item.label}</Link>}
      {after}
    </span>
  );
}

/** Old values struck through, new ones in bold, plain detail lines and a quoted "why". */
export function ChangeDetails({ row }: { row: ChangeRow }) {
  return (
    <>
      {row.diffs.map((d) => (
        <span key={d.label + (d.after ?? d.before ?? '')} className="diff-line">
          {d.label}: {d.after === null ? <del>{d.before}</del> : <>{d.before !== null && <><del>{d.before}</del> → </>}<ins>{d.after}</ins></>}
        </span>
      ))}
      {row.lines.map((l) => <span key={l} className="diff-line">{l}</span>)}
      {row.note && <span className="chg__note">"{row.note}"</span>}
    </>
  );
}
