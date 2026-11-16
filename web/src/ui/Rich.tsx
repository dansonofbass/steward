import { Fragment } from 'react';
import type { Part } from '../lib/receipt';

/** Copy with bold runs (lib/receipt.ts rich()). */
export function Rich({ parts }: { parts: Part[] }) {
  return <>{parts.map((p, i) => (p.bold ? <strong key={i}>{p.text}</strong> : <Fragment key={i}>{p.text}</Fragment>))}</>;
}
