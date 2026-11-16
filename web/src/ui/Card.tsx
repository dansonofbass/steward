import type { HTMLAttributes } from 'react';
import './Card.css';

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div {...rest} className={['card', className].filter(Boolean).join(' ')} />;
}
