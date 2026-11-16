import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { wrapBook } from '../../test-utils';
import type { Turn } from './askApi';
import { fromTurn, TurnView } from './TurnView';

const TURN: Turn = {
  turn_id: 't_1', asked: 'Why is Eating out over?', sent: 'Why is Eating out over?', chips: [], as_written: true, who: 'JR',
  when: 'Today 9:41 AM', steps: [], answer: 'You spent $120 more.', stop: 'end_turn', line: null, meta: '3 seconds · $0.04',
  saw: [], approval: null, looked_into: false, unfinished: false,
};
const show = (t: Turn, labels: Record<string, string> = {}) =>
  wrapBook(<TurnView view={fromTurn(t)} labels={labels} onAskAgain={() => {}} />);

describe('a question asked about something (Ask about this P9)', () => {
  it('shows "About: …" over the question', () => {
    show({ ...TURN, about: { chip: { kind: 'category', category: 'dining', month: '2026-10' }, sent: "It's about Eating out (category dining) in October 2026." } });
    expect(screen.getByText('About: Eating out · October')).toHaveClass('qabout');
  });
  it("puts the account's name back from the conversation's labels", () => {
    show({ ...TURN, about: { chip: { kind: 'account', account: 'Account 3' }, sent: "It's about Account 3." } }, { 'Account 3': 'Checking ••6789' });
    expect(screen.getByText('About: Checking ••6789 · sent as Account 3')).toBeInTheDocument();
  });
  it('a question with no about has no line', () => {
    const { container } = show({ ...TURN, about: null });
    expect(container.querySelector('.qabout')).toBeNull();
  });
});
