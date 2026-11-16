import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StepBar } from './StepBar';

describe('StepBar (decision 4)', () => {
  it('colours each part done, this step, skipped or not started, with a legend in words', () => {
    render(<StepBar legend current="pay" states={[
      { key: 'about', status: 'done' }, { key: 'banks', status: 'skipped' }, { key: 'home', status: 'doesnt_apply' },
      { key: 'pay', status: 'todo' }, { key: 'children', status: 'todo' }, { key: 'health', status: 'done' }, { key: 'earnings', status: 'todo' },
    ]} />);
    const parts = Array.from(screen.getByTestId('step-bar').children).map((c) => c.className);
    expect(parts).toEqual(['ob-seg is-done', 'ob-seg is-skipped', 'ob-seg is-done', 'ob-seg is-current', 'ob-seg is-todo', 'ob-seg is-done', 'ob-seg is-todo']);
    for (const word of ['Done', 'This step', 'Skipped', 'Not started']) expect(screen.getByText(word)).toBeInTheDocument();
  });
  it('has no legend unless asked', () => {
    render(<StepBar states={[{ key: 'about', status: 'todo' }]} />);
    expect(screen.queryByText('Not started')).toBeNull();
  });
  it('with a label it is an image of that name, and the label is not visible text', () => {
    render(<StepBar label="Step 2 of 3" current="cover" states={[{ key: 'kids', status: 'done' }, { key: 'cover', status: 'todo' }, { key: 'plans', status: 'todo' }]} />);
    expect(screen.getByRole('img', { name: 'Step 2 of 3' })).toBeInTheDocument();
    expect(screen.queryByText('Step 2 of 3')).toBeNull();
  });
});
