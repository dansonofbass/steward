/** Sorting redesign, Seasonal; phase 17 spec 3.1: the season from the device's local date, as the sky reads its own.
 *  Snow in December, leaves from October 1 to November 30, fireworks on January 1. Here, not in the celebrate chunk,
 *  so the still acorn (ui/Acorn.tsx) can tint itself without loading any motion. */
export function season(now: Date): 'snow' | 'leaves' | 'fireworks' | null {
  const m = now.getMonth();
  if (m === 0 && now.getDate() === 1) return 'fireworks';
  if (m === 11) return 'snow';
  if (m === 9 || m === 10) return 'leaves';
  return null;
}
