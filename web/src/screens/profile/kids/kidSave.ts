import { useCallback, useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import type { ChildInput } from '../../../api/household';
import { undoToken } from '../../../api/profile';
import { failure } from '../../settings/shared';
import { changeChild } from '../api';
import { invalidateProfile, useFieldMode } from '../field';

/** One kid's changes, sent as they happen (a choice at once; a slider or typing after `delay`), and waited for by Next
 *  (Flow's flush). Keeps the last Undo token for the card's "Saved · Undo". */
export function useKidSave(id: number) {
  const { register } = useFieldMode();
  const qc = useQueryClient();
  const pending = useRef<ChildInput>({});
  const timer = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [undo, setUndo] = useState<string | null>(null);
  const flush = useCallback(async (): Promise<boolean> => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    const body = pending.current;
    if (Object.keys(body).length === 0) return true;
    pending.current = {};
    try {
      const r = await changeChild(id, body);
      setUndo(r.undo);
      setError(null);
      await invalidateProfile(qc);
      return true;
    } catch (e) {
      pending.current = { ...body, ...pending.current };
      setError(failure(e));
      return false;
    }
  }, [id, qc]);
  useEffect(() => register(flush), [register, flush]);
  const busy = useCallback(() => timer.current !== null || Object.keys(pending.current).length > 0, []);
  /** Undo the last save; the Undo stays (with the message) if the server refuses, e.g. 409 changed since. */
  const undoIt = useCallback(async () => {
    if (!undo) return;
    try {
      await undoToken(undo);
      setUndo(null);
      setError(null);
      await invalidateProfile(qc);
    } catch (e) {
      setError(failure(e));
    }
  }, [undo, qc]);
  const save = useCallback((body: ChildInput, delay = 0) => {
    pending.current = { ...pending.current, ...body };
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { timer.current = null; void flush(); }, delay);
  }, [flush]);
  return { save, flush, error, undo, setUndo, undoIt, busy };
}
