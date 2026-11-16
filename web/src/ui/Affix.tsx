import type { InputHTMLAttributes, Ref } from 'react';
import './Affix.css';

type Props = InputHTMLAttributes<HTMLInputElement> & { pre?: string; post?: string; inputRef?: Ref<HTMLInputElement> };

/** An input with a fixed "$" before or "a year" after. Field clones it with id and aria props, which land on the input. */
export function Affix({ pre, post, className, inputRef, ...input }: Props) {
  const cls = ['affix', pre ? 'affix--pre' : '', post ? 'affix--post' : '', className ?? ''].filter(Boolean).join(' ');
  return (
    <div className={cls}>
      {pre && <span className="affix__pre" aria-hidden="true">{pre}</span>}
      <input autoComplete="off" ref={inputRef} {...input} />
      {post && <span className="affix__post" aria-hidden="true">{post}</span>}
    </div>
  );
}

export type { Props as AffixProps };
