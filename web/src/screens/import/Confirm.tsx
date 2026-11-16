import { useId } from 'react';
import type { Account } from '../../api/types';
import { Button } from '../../ui/Button';
import type { Field } from './api';
import * as C from './copy';
import { contradicted, fieldAt, kindOf, moveField, negateOf, questions, signCopy, signShows, validity, type Answers, type Row } from './logic';

type Props = { row: Row; account: Account | null; onChange: (a: Answers) => void; onUse: () => void };

/** P12: a new layout's one confirm, with the guessed columns pre-set and its questions inside it. A remembered layout
 *  the evidence contradicts shows its sign question alone (P14). Saved at commit, not here. */
export function Confirm({ row, account, onChange, onUse }: Props) {
  const id = useId();
  const f = row.file!;
  const lay = f.layout!;
  const ans = row.answers!;
  const kind = kindOf(account);
  const again = contradicted(f, account);
  const negate = negateOf(row, account);
  const copy = signCopy(kind, kind ? lay.sign[kind].lean : null);
  const invalid = validity(ans.mapping) !== 'ok';
  const dq = f.state === 'new' ? lay.date_question : null;
  const reading = ans.dateFormat ? (dq?.options.find((o) => o.format === ans.dateFormat)?.reading ?? lay.reading) : null;
  return (
    <div className="imp-confirm">
      {!again && (
        <div className="table-wrap">
          <table className="table imp-confirm__table" style={{ minWidth: `${C.COL_REM * lay.header.length}rem` }}>
            <caption className="sr-only">{C.COLUMNS_IN.replace('{file}', f.name)}</caption>
            <thead>
              <tr>
                {lay.header.map((h, i) => (
                  <th key={i} scope="col">
                    <select aria-label={C.COLUMN_N.replace('{n}', String(i + 1)).replace('{header}', h)} value={fieldAt(ans.mapping, i)}
                      onChange={(e) => onChange({ ...ans, mapping: moveField(ans.mapping, i, e.target.value as Field | 'ignore') })}>
                      {C.OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
                    </select>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {lay.sample.map((cells, r) => (
                <tr key={r}>{lay.header.map((_, i) => <td key={i} className="raw-cell">{cells[i] ?? ''}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!again && invalid && <p className="imp-confirm__warn">{C.INVALID}</p>}
      {!again && f.held && <p className="imp-confirm__warn">{f.held}</p>}
      {signShows(row, account) && (
        <fieldset className="imp-confirm__q">
          <legend>{kind ? copy.legend : C.NO_ACCOUNT}</legend>
          {again && <p className="small">{C.SIGN_CHANGED}</p>}
          {kind && copy.options.map((label, i) => (
            <label key={label} className="imp-confirm__choice">
              <input type="radio" name={`${id}-sign`} checked={negate === (i === 0)} onChange={() => onChange({ ...ans, negate: i === 0 })} />
              {label}
            </label>
          ))}
        </fieldset>
      )}
      {dq && (
        <fieldset className="imp-confirm__q">
          <legend>{C.DATE_QUESTION.replace('{value}', dq.example).replace('{a}', dq.options[0].label).replace('{b}', dq.options[1].label)}</legend>
          {dq.options.map((o) => (
            <label key={o.format} className="imp-confirm__choice">
              <input type="radio" name={`${id}-date`} checked={ans.dateFormat === o.format} onChange={() => onChange({ ...ans, dateFormat: o.format })} />
              {o.label}
            </label>
          ))}
        </fieldset>
      )}
      {!again && reading && <p className="small">{C.DATES_READ.replace('{reading}', reading)}</p>}
      {!again && <p className="small muted">{C.REMEMBERED_NOTE}</p>}
      {!again && <Button onClick={onUse} disabled={invalid || questions(row, account) > 0}>{C.USE}</Button>}
    </div>
  );
}
