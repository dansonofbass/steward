import { useEffect, useRef } from 'react';

/** A ref for a page or step heading: it takes focus when the screen mounts, so keyboard and screen-reader users land
 *  on the new content rather than on <body>. Give the element tabIndex={-1} so it can hold focus. */
export function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => { ref.current?.focus({ preventScroll: true }); }, []);
  return ref;
}

/** True when nothing holds focus (a button that was disabled or removed hands it to <body>). */
export const focusIsLost = () => typeof document !== 'undefined' && (!document.activeElement || document.activeElement === document.body);
