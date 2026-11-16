import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AliasText, AnswerText } from './aliasText';

const LABELS = { 'Person 2': 'Sam', 'Account 2': 'Rewards Card ••4402', Joint: 'Joint' };

describe('names put back on screen', () => {
  it('shows the label with a dotted line and the alias on tap', () => {
    render(<p><AliasText text="About 60% is on Person 2's Account 2, not Joint." labels={LABELS} /></p>);
    const sam = screen.getByRole('button', { name: 'Sam. Sent as Person 2' });
    expect(sam).toHaveClass('alias');
    expect(screen.getByRole('button', { name: 'Rewards Card ••4402. Sent as Account 2' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Joint/ })).toBeNull();            // same label: nothing to show
    fireEvent.click(sam);
    expect(screen.getByText('Sent as Person 2')).toBeInTheDocument();
  });

  it('leaves an alias it has no label for as written', () => {
    render(<p><AliasText text="Person 7 paid." labels={LABELS} /></p>);
    expect(screen.getByText('Person 7 paid.')).toBeInTheDocument();
  });

  it('renders paragraphs, bold, list lines and makes dollar amounts strong', () => {
    const { container } = render(<AnswerText text={'Yes. Dining came to **$9,184**.\n\n- Up $1,412\n- Person 2 most'} labels={LABELS} />);
    expect(container.querySelectorAll('p')).toHaveLength(1);
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(screen.getByText('$9,184').tagName).toBe('STRONG');
    expect(screen.getByText('$1,412')).toHaveClass('num');
  });
});

const JR_ANSWER = [
  "You've spent $x on the kids this year.",
  '',
  '| Category | Transactions | Amount |',
  '|---|---|---|',
  '| Kids | 15 | $1,234.00 |',
  '| Childcare and education | 7 | $560.00 |',
  '| **Total** | 22 | **$1,794.00** |',
  'This total is probably too low.',
].join('\n');

describe('a table in an answer', () => {
  it('draws a table even with a sentence straight after it', () => {
    const { container } = render(<AnswerText text={JR_ANSWER} labels={LABELS} />);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual(['Category', 'Transactions', 'Amount']);
    expect(container.querySelectorAll('tbody tr')).toHaveLength(3);
    expect(container.querySelector('.answer-table')?.tagName).toBe('DIV');
    const paras = [...container.querySelectorAll('p')].map((p) => p.textContent);
    expect(paras).toEqual(["You've spent $x on the kids this year.", 'This total is probably too low.']);
    expect(container.querySelector('pre')).toBeNull();
  });

  it('sets bold and money emphasis in cells', () => {
    render(<AnswerText text={JR_ANSWER} labels={LABELS} />);
    expect(screen.getByText('Total').tagName).toBe('STRONG');
    expect(screen.getByText('$1,234.00')).toHaveClass('num');
    expect(screen.getByText('$1,794.00').tagName).toBe('STRONG');
  });

  it('right-aligns a number column and honours alignment markers', () => {
    const { container } = render(<AnswerText text={JR_ANSWER} labels={LABELS} />);
    const align = (n: number) => [...container.querySelectorAll('tr')].map((r) => (r.children[n] as HTMLElement).style.textAlign);
    expect(align(2)).toEqual(['right', 'right', 'right', 'right']);
    expect(align(0)).toEqual(['', '', '', '']);
    const marked = render(<AnswerText text={'| a | b | c |\n|:---|---:|:---:|\n| x | y | z |'} labels={LABELS} />);
    const ths = [...marked.container.querySelectorAll('th')].map((h) => h.style.textAlign);
    expect(ths).toEqual(['left', 'right', 'center']);
  });

  it('keeps an escaped pipe as a literal pipe in the cell', () => {
    render(<AnswerText text={'| a | b |\n|---|---|\n| x \\| y | z |'} labels={LABELS} />);
    expect(screen.getByText('x | y')).toBeInTheDocument();
  });

  it('puts an alias back in a cell', () => {
    render(<AnswerText text={'| Who | Paid |\n|---|---|\n| Person 2 | $5 |'} labels={LABELS} />);
    expect(screen.getByRole('button', { name: 'Sam. Sent as Person 2' })).toBeInTheDocument();
  });

  it('falls back to the raw lines when there is no separator or a row is short', () => {
    const noSep = render(<AnswerText text={'| a | b |\n| x | y |'} labels={LABELS} />);
    expect(noSep.container.querySelector('table')).toBeNull();
    expect(noSep.container.querySelector('pre.answer-table')?.textContent).toBe('| a | b |\n| x | y |');
    const short = render(<AnswerText text={'| a | b |\n|---|---|\n| x |'} labels={LABELS} />);
    expect(short.container.querySelector('table')).toBeNull();
    expect(short.container.querySelector('pre.answer-table')?.textContent).toBe('| a | b |\n|---|---|\n| x |');
  });

  it('keeps text before a table in the same block, and list lines as a list', () => {
    const { container } = render(<AnswerText text={'- one\n- two\n| a |\n|---|\n| x |\nafter'} labels={LABELS} />);
    expect(container.querySelectorAll('li')).toHaveLength(2);
    expect(container.querySelectorAll('table')).toHaveLength(1);
    expect(container.querySelector('p')?.textContent).toBe('after');
  });
});

