// THO-1 (release gate 0.1.0, fix 16f re-check): a removal's line is heard every time, even when it is the same as the
// line already showing. Two members both named Vee, removed one after the other, each say "Removed Vee from Mom.". If the
// live region doesn't change, a screen reader says nothing the second time and a sighted person sees the old line.
// Every way the hook says a line (removed, removedHere, say) must change the region's DOM.
import { act, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useRemoval, type Removal } from '../lib/useRemoval';
import { RemovalLine } from './RemovalLine';

function mount() {
  const ref: { current: Removal | null } = { current: null };
  function Host() {
    const removal = useRemoval();
    ref.current = removal;
    return (
      <section>
        <h2 ref={removal.anchor} tabIndex={-1}>People</h2>
        <RemovalLine removal={removal} />
      </section>
    );
  }
  const { container } = render(<Host />);
  const region = container.querySelector('.removal-line')!;
  let changes = 0;
  const seen = new MutationObserver((records) => { changes += records.length; });
  seen.observe(region, { childList: true, subtree: true, characterData: true });
  /** Says a line through the hook and returns how many DOM changes the live region took. */
  const say = (how: (r: Removal) => void) => {
    seen.takeRecords();
    changes = 0;
    act(() => how(ref.current!));
    return changes + seen.takeRecords().length;
  };
  return { region, say };
}

const WAYS: [string, (r: Removal, text: string) => void][] = [
  ['removed', (r, t) => r.removed(t)],
  ['removedHere', (r, t) => r.removedHere(t)],
  ['say', (r, t) => r.say(t)],
];

describe('the removal line is heard each time (THO-1)', () => {
  it.each(WAYS)('%s: the same line twice changes the live region twice', (_, way) => {
    const { region, say } = mount();
    expect(say((r) => way(r, 'Removed Vee from Mom.'))).toBeGreaterThan(0);
    const first = region.querySelector('p');
    expect(first).toHaveTextContent('Removed Vee from Mom.');
    expect(say((r) => way(r, 'Removed Vee from Mom.'))).toBeGreaterThan(0);
    const second = region.querySelector('p');
    expect(second).toHaveTextContent('Removed Vee from Mom.');
    expect(second).not.toBe(first);   // a new node, which a live region announces
  });

  it('a line said one way and then the same line another way is still heard', () => {
    const { say } = mount();
    say((r) => r.say('Revoked Sam\'s grant for Mom.'));
    expect(say((r) => r.removedHere('Revoked Sam\'s grant for Mom.'))).toBeGreaterThan(0);
    expect(say((r) => r.removed('Revoked Sam\'s grant for Mom.'))).toBeGreaterThan(0);
  });

  it('clear empties the region', () => {
    const { region, say } = mount();
    say((r) => r.removed('Removed Vee from Mom.'));
    say((r) => r.clear());
    expect(region.querySelector('p')).toBeNull();
  });
});
