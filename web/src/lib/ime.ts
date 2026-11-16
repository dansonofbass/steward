import type { KeyboardEvent as ReactKeyboardEvent } from 'react';

/** WEB-17: an Enter that confirms an input method's conversion (Japanese, Chinese, Korean), not one that means Save.
 *  isComposing says so; Safari can end the composition just before the key arrives, but still reports keyCode 229. A
 *  handler that saves on Enter returns early when this is true. ime.test.ts scans for one that doesn't. */
export function composing(e: ReactKeyboardEvent | KeyboardEvent): boolean {
  const key = 'nativeEvent' in e ? e.nativeEvent : e;
  return key.isComposing || key.keyCode === 229;
}
