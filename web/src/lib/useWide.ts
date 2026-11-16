import { useEffect, useState } from 'react';

export const WIDE = '(min-width: 900px)';

/** True from 900 px, where Settings shows tabs and the setup list sits beside the open step. */
export function useWide(query: string = WIDE): boolean {
  const read = () => (typeof window.matchMedia === 'function' ? window.matchMedia(query).matches : false);
  const [wide, setWide] = useState(read);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia(query);
    const on = () => setWide(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [query]);
  return wide;
}

/** True when the device has a real pointer that hovers (a mouse), so hover can hold or reveal things. */
export const canHover = () => typeof window.matchMedia === 'function' && window.matchMedia('(hover: hover)').matches;
