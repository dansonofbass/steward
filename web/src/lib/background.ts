import type { Background } from '../api/types';
import { BACKGROUND_PROGRESS, BACKGROUND_WAITING } from './copy';
import { gw } from './gatewayName';

/** The line for the model's background pass, or null when nothing is pending or no categorizer is coming (the rows
 *  wait in Review, which already says so). Review and Home share it. */
export function backgroundLine(bg: Background): string | null {
  if (bg.pending <= 0 || bg.expected === false) return null;
  if (bg.waiting) return gw(BACKGROUND_WAITING.replace('{n}', String(bg.pending)));
  return BACKGROUND_PROGRESS.replace('{done}', String(bg.done)).replace('{total}', String(bg.done + bg.pending));
}
