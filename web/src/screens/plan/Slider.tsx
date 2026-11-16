import type { ReactNode } from 'react';
import type { Scale } from './api';
import { SAVED_PLAN_MARK } from './copy';
import { sliderPct } from './levers';

type Props = {
  lever: string; value: number; scale: Scale; labels: [string, string, string]; valueText: string; onChange: (v: number) => void;
  label?: string; variant?: 'assumed' | 'try'; ghost?: number | null; saved?: string; note?: ReactNode; actions?: ReactNode; testId: string;
};

/** One slider per lever (design decision 4). Value, rail, scale ends and actions share the `.slider` grid from m2.css,
 *  so their edges line up at 390 px. The drawn rail is decoration; a transparent native range input on top does the work. */
export function Slider({ lever, value, scale, labels, valueText, onChange, label, variant = 'assumed', ghost = null, saved, note, actions, testId }: Props) {
  const pct = sliderPct(value, scale);
  return (
    <div className={`slider${variant === 'try' ? ' slider--try' : ''}`}>
      <div className="slider__top">
        <span className="slider__value">{label && <><span className="slider__label">{label}</span>{' '}</>}{valueText}</span>
        {saved && <span className="slider__saved">{saved}</span>}
      </div>
      <div className="slider__track">
        <span className="slider__rail" aria-hidden="true">
          <span className="slider__ticks">{Array.from({ length: 5 }, (_, i) => <i key={i} />)}</span>
          <span className="slider__fill" style={{ width: `${pct}%` }} />
          {ghost !== null && ghost !== value && <span className="slider__ghost" style={{ left: `${sliderPct(ghost, scale)}%` }} title={SAVED_PLAN_MARK} />}
          <span className="slider__thumb" style={{ left: `${pct}%` }} />
        </span>
        <input type="range" className="slider__input" min={scale.lo} max={scale.hi} step={scale.step} value={value}
          aria-label={label ? `${label}: ${lever}` : lever} aria-valuetext={valueText} data-testid={testId}
          onChange={(e) => onChange(Number(e.target.value))} />
      </div>
      <div className="slider__scale" aria-hidden="true"><span>{labels[0]}</span><span>{labels[1]}</span><span>{labels[2]}</span></div>
      {note && <p className="slider__note">{note}</p>}
      {actions && <div className="slider__actions">{actions}</div>}
    </div>
  );
}
