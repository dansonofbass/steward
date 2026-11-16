import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { undoToken } from '../../../api/profile';
import { Notice } from '../../../ui/Notice';
import { UndoToast } from '../../../ui/UndoToast';
import { failure } from '../../settings/shared';
import { invalidateProfile } from '../field';

export type Offer = (text: string, ...tokens: (string | null)[]) => void;

/** Nothing vanishes unseen: a write outside a ProfileField names itself with Undo. One Undo reverts every token, last first. */
export function useOffer(onUndone?: () => void) {
  const qc = useQueryClient();
  const [toast, setToast] = useState<{ text: string; tokens: string[] } | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const offer: Offer = (text, ...tokens) => {
    const real = tokens.filter((t): t is string => !!t);
    setFailed(null);
    setToast(real.length ? { text, tokens: real } : null);
  };
  const view = (
    <>
      {failed && <Notice tone="error">{failed}</Notice>}
      {toast && <UndoToast text={toast.text} onClose={() => setToast(null)} onUndo={() => {
        const { tokens } = toast;
        setToast(null);
        void (async () => {
          try {
            for (const t of [...tokens].reverse()) await undoToken(t);
            onUndone?.();
            await invalidateProfile(qc);
          } catch (e) { setToast({ text: toast.text, tokens }); setFailed(failure(e)); }   // Undo stays, with why
        })();
      }} />}
    </>
  );
  return { offer, view };
}
