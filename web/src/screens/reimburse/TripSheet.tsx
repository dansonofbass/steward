import { ChevronDown } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { addPayer, addTrip, editTrip } from '../../api/reimburse';
import type { Payer, TripBody, TripSummary } from '../../api/types';
import { SAVE } from '../../lib/copy';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';
import { Sheet } from '../../ui/Sheet';
import * as C from './copy';
import { defaultTripName } from './model';

type Props = { trip?: TripSummary; payers: Payer[]; onClose: () => void; onSaved: (t: TripSummary) => void };

/** Making or editing a trip (spec, Making a trip): Name (from the city until the person types one), Start, End, City,
 *  and the payer when there are two or more. With no payer yet it asks who pays you back, once. */
export function TripSheet({ trip, payers, onClose, onSaved }: Props) {
  const [name, setName] = useState(trip?.name ?? '');
  const [named, setNamed] = useState(trip !== undefined);
  const [start, setStart] = useState(trip?.start ?? '');
  const [end, setEnd] = useState(trip?.end ?? '');
  const [city, setCity] = useState(trip?.city ?? '');
  const [payer, setPayer] = useState<number | null>(trip?.reimburser_id ?? (payers.length === 1 ? payers[0].id : null));
  const [newPayer, setNewPayer] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const asking = !trip && payers.length === 0;
  const shown = named ? name : defaultTripName(city);
  const ready = start !== '' && end !== '' && shown.trim() !== '' && (asking ? newPayer.trim() !== '' : payer !== null);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (busy || !ready) return;
    setBusy(true);
    setError(null);
    try {
      const pid = asking ? (await addPayer(newPayer.trim())).id : payer;
      const body: TripBody = { name: shown.trim(), start, end, city: city.trim() || null };
      // The server takes the only payer itself; it needs one named when there were none, or two or more.
      if (pid !== null && (asking || payers.length >= 2)) body.reimburser_id = pid;
      const r = trip ? await editTrip(trip.id, body) : await addTrip(body);
      onSaved(r.trip);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Sheet open onClose={onClose} title={trip ? C.EDIT_TRIP : C.ADD_TRIP}>
      <form className="stack" onSubmit={(e) => { void save(e); }}>
        <Field label={C.NAME}>
          <input value={shown} maxLength={80} onChange={(e) => { setName(e.target.value); setNamed(true); }} />
        </Field>
        <div className="grid-2">
          <Field label={C.START}><input type="date" value={start} onChange={(e) => { setStart(e.target.value); }} /></Field>
          <Field label={C.END}><input type="date" value={end} min={start || undefined} onChange={(e) => { setEnd(e.target.value); }} /></Field>
        </div>
        <Field label={C.CITY}><input value={city} maxLength={60} onChange={(e) => { setCity(e.target.value); }} /></Field>
        {asking && (
          <Field label={C.WHO_PAYS}>
            <input value={newPayer} placeholder={C.PAYER_HINT} maxLength={60} onChange={(e) => { setNewPayer(e.target.value); }} />
          </Field>
        )}
        {payers.length >= 2 && (
          <div className="select">
            <Field label={C.WHO_PAYS}>
              <select value={payer ?? ''} onChange={(e) => { setPayer(Number(e.target.value)); }}>
                {payer === null && <option value="" disabled>{C.CHOOSE_ONE}</option>}
                {payers.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </Field>
            <ChevronDown size={20} aria-hidden="true" />
          </div>
        )}
        {error && <Notice tone="error">{error}</Notice>}
        <Button type="submit" busy={busy} disabled={!ready}>{SAVE}</Button>
      </form>
    </Sheet>
  );
}
