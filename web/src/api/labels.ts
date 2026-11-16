import { api, put } from './client';
import type { LabelBody, LabelReply, LabelView } from './types';

export const getLabel = (id: number) => api<LabelView>(`/api/transactions/${id}/label`);
/** One Save, one Undo: the note on each row reached, the name on each, and on the rule when future is set. */
export const saveLabel = (id: number, body: LabelBody) => api<LabelReply>(`/api/transactions/${id}/label`, put(body));
