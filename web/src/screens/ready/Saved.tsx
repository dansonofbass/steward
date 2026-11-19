import { useRef } from 'react';
import { SAVED } from '../../lib/copy';
import { useSayShown } from '../../ui/Live';

/** Mounts for each save, so a later identical confirmation is said again. */
export function Saved() {
  const el = useRef<HTMLSpanElement>(null);
  useSayShown(el);
  return <span ref={el}>{SAVED}</span>;
}
