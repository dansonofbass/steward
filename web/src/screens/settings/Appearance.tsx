import { useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { useMe } from '../../api/hooks';
import { useNavigate } from '../../book/links';
import { celebrationsChosen, reducedMotion, savePref, soundOn, type Prefs } from '../../lib/celebrations';
import { CELEBRATIONS, CELEBRATIONS_REDUCED, REPLAY_SWIPE_DEMO, S_APPEARANCE, SOUND, SWIPE_TO_SORT, THEME_DARK, THEME_LIGHT, THEME_SYSTEM } from '../../lib/copy';
import { clearDemo, saveView, setSwipe, swipeOn } from '../../lib/reviewPrefs';
import { getTheme, setTheme, type Theme } from '../../lib/theme';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';
import { failure } from './shared';

const OPTIONS: { value: Theme; label: string }[] = [
  { value: 'sky', label: THEME_SYSTEM },
  { value: 'light', label: THEME_LIGHT },
  { value: 'dark', label: THEME_DARK },
];

export function AppearanceOptions() {
  const [theme, set] = useState<Theme>(getTheme);
  return (
    <div className="stack">
      <fieldset className="card lines radios">
        <legend className="sr-only">{S_APPEARANCE}</legend>
        {OPTIONS.map((o) => (
          <label className="line radio-row" key={o.value}>
            <input type="radio" name="theme" value={o.value} checked={theme === o.value} onChange={() => { set(o.value); setTheme(o.value); }} />
            <span>{o.label}</span>
          </label>
        ))}
      </fieldset>
      <CelebrationSwitches />
      <SwipeSwitches />
    </div>
  );
}

/** Review focus P2: per device, beside Celebrations and Sound. Swipe to sort is on by default; while it is off, focus has
 *  no drag, no demo and no hint. Replay the swipe demo clears the nudge and the hint and opens Review in focus. */
function SwipeSwitches() {
  const [on, setOn] = useState(swipeOn);
  const me = useMe();
  const navigate = useNavigate();
  return (
    <fieldset className="card lines">
      <legend className="sr-only">{SWIPE_TO_SORT}</legend>
      <label className="line check-row">
        <input type="checkbox" role="switch" checked={on} onChange={(e) => { setOn(e.target.checked); setSwipe(e.target.checked); }} />
        <span>{SWIPE_TO_SORT}</span>
      </label>
      <div className="line">
        <Button variant="quiet" disabled={!on}
          onClick={() => { clearDemo(); saveView(me.data?.user.id ?? null, 'focus'); navigate('/review'); }}>{REPLAY_SWIPE_DEMO}</Button>
      </div>
    </fieldset>
  );
}

/** Sorting redesign, Settings; phase 17 spec 3.6: the person's own, saved to them (it says nothing new). Celebrations
 *  shows off, with the reason, on a device set to reduce motion. Sound plays only with celebrations, so it waits while
 *  they are off. A refused save puts the switch back. */
export function CelebrationSwitches() {
  const reduce = reducedMotion();
  const qc = useQueryClient();
  const [chosen, setChosen] = useState(celebrationsChosen);
  const [sound, setS] = useState(soundOn);
  const [error, setError] = useState<string | null>(null);
  const on = chosen && !reduce;
  const hint = useId();
  async function save(key: keyof Prefs, value: boolean, set: (v: boolean) => void) {
    set(value);
    setError(null);
    try {
      await savePref(key, value);
      void qc.invalidateQueries({ queryKey: ['me'] });
    } catch (e) {
      set(!value);
      setError(failure(e));
    }
  }
  return (
    <fieldset className="card lines">
      <legend className="sr-only">{CELEBRATIONS}</legend>
      <label className="line check-row">
        <input type="checkbox" role="switch" checked={on} disabled={reduce} aria-describedby={reduce ? hint : undefined}
          onChange={(e) => void save('celebrations', e.target.checked, setChosen)} />
        <span>{CELEBRATIONS}</span>
      </label>
      {reduce && <p id={hint} className="line muted">{CELEBRATIONS_REDUCED}</p>}
      <label className="line check-row">
        <input type="checkbox" role="switch" checked={sound && on} disabled={!on}
          onChange={(e) => void save('sound', e.target.checked, setS)} />
        <span>{SOUND}</span>
      </label>
      {error && <Notice tone="error">{error}</Notice>}
    </fieldset>
  );
}
