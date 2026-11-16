import { fireEvent, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { stubFetch, wrap } from '../test-utils';
import { CategoryField, menuSections } from './CategoryMenu';

const media = (desktop: boolean) => vi.stubGlobal('matchMedia', (q: string) => ({
  matches: desktop && !q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }));

function Harness({ start = 'groceries', withUnsorted = true }: { start?: string; withUnsorted?: boolean }) {
  const [v, setV] = useState(start);
  return <><CategoryField value={v} onChange={setV} withUnsorted={withUnsorted} /><output data-testid="picked">{v}</output></>;
}
const trigger = () => screen.getByRole('button', { name: /^Category / });
const search = () => screen.getByRole('combobox', { name: 'Find a category' });
const options = () => screen.getAllByRole('option').map((o) => o.textContent);
const type = (q: string) => fireEvent.change(search(), { target: { value: q } });
const GROUPS = ['Everyday', 'Home, bills and loans', 'Family, pets, health and giving', 'Money in', 'Business, taxes, transfers and investing'];

beforeEach(() => { stubFetch({ '/api/categorize/usual': { keys: ['dining', 'home'] } }); });
afterEach(() => vi.unstubAllGlobals());

describe('CategoryMenu (sorting redesign, The picker)', () => {
  it('lists your usual, then the five groups, and Not sure yet only where it is allowed', () => {
    expect(menuSections('', [], false).map((s) => s.name)).toEqual(GROUPS);
    expect(menuSections('', ['dining', 'uncategorized'], true).map((s) => s.name)).toEqual(['Your usual', ...GROUPS, 'Not sure yet']);
    expect(menuSections('', ['dining', 'uncategorized'], true)[0].keys).toEqual(['dining']);
    expect(menuSections('pet', [], false)).toEqual([{ id: 'found', name: null, keys: ['pets'] }]);
  });

  it('opens under the trigger on a desktop with the search box focused, your usual first, the groups in two columns', async () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    expect(search()).toHaveFocus();
    expect(document.querySelector('.catmenu-pop')).not.toBeNull();
    expect(document.querySelector('.sheet')).toBeNull();
    const usual = await screen.findByRole('group', { name: 'Your usual' });
    expect(within(usual).getAllByRole('option').map((o) => o.textContent)).toEqual(['Eating out', 'Home and garden']);
    for (const g of [...GROUPS, 'Not sure yet']) expect(screen.getByRole('group', { name: g })).toBeInTheDocument();
    expect(screen.getByRole('listbox')).toHaveClass('catmenu__list--grouped');
  });

  it('on a desktop, every group is a grid of rows under its heading, and the arrows read them in that order', async () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    const usual = await screen.findByRole('group', { name: 'Your usual' });
    const list = screen.getByRole('listbox');
    expect(list).toHaveClass('catmenu__list', 'catmenu__list--grouped');
    expect(list.closest('.catmenu-pop')).not.toBeNull();
    // Usual first, then the groups; each group's heading comes before its rows, which CategoryMenu.css lays out as
    // two columns read left to right, then down: the DOM order, the order the arrows take.
    const groups = within(list).getAllByRole('group');
    expect(groups[0]).toBe(usual);
    expect(usual).toHaveClass('catmenu__group', 'catmenu__group--usual');
    for (const g of groups) {
      expect(g).toHaveClass('catmenu__group');
      expect(g.firstElementChild).toHaveClass('catmenu__head');
      expect([...g.children].slice(1).every((c) => c.classList.contains('catmenu__opt'))).toBe(true);
    }
    const rows = screen.getAllByRole('option');
    expect(search()).toHaveAttribute('aria-activedescendant', rows[0].id);
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    expect(search()).toHaveAttribute('aria-activedescendant', rows[1].id);
    expect(rows[1]).toHaveTextContent('Home and garden');
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    expect(search()).toHaveAttribute('aria-activedescendant', rows[2].id);
    expect(rows[2].closest('[role=group]')).toHaveAccessibleName('Everyday');
  });

  it('a typed search is one ranked list, not grouped', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    type('car');
    expect(screen.getByRole('listbox')).not.toHaveClass('catmenu__list--grouped');
    expect(screen.queryAllByRole('group')).toEqual([]);
  });

  it('is a half sheet on a phone, the search box focused', () => {
    media(false);
    wrap(<Harness />);
    fireEvent.click(trigger());
    expect(screen.getByRole('dialog', { name: 'Category' }).closest('.sheet')).toHaveClass('catmenu-sheet');
    expect(document.querySelector('.catmenu-pop')).toBeNull();
    expect(search()).toHaveFocus();
  });

  it('filters as you type, by label and by everyday words, and says when nothing matches', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    type('gift');
    expect(options()).toEqual(['Gifts']);
    type('gas');
    expect(options()).toEqual(['Getting around', 'Utilities']);
    type('vet');
    expect(options()).toEqual(['Pets']);
    type('llama');
    expect(screen.queryAllByRole('option')).toEqual([]);
    expect(screen.getByText('No category matches “llama”.')).toBeInTheDocument();
    fireEvent.keyDown(search(), { key: 'Enter' });
    expect(screen.getByTestId('picked')).toHaveTextContent('groceries');
  });

  it('moves with the arrow keys in reading order, and Enter picks, closes and returns focus to the trigger', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    type('car');
    const ids = screen.getAllByRole('option').map((o) => o.id);
    expect(search()).toHaveAttribute('aria-activedescendant', ids[0]);
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    expect(search()).toHaveAttribute('aria-activedescendant', ids[1]);
    fireEvent.keyDown(search(), { key: 'ArrowUp' });
    fireEvent.keyDown(search(), { key: 'ArrowUp' });
    expect(search()).toHaveAttribute('aria-activedescendant', ids[ids.length - 1]);
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    fireEvent.keyDown(search(), { key: 'Enter' });
    expect(screen.getByTestId('picked')).toHaveTextContent('travel');
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it('Esc closes and returns focus to the trigger, and so does Tab', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    fireEvent.keyDown(search(), { key: 'Escape' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(trigger()).toHaveFocus();
    fireEvent.click(trigger());
    fireEvent.keyDown(search(), { key: 'Tab' });
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(trigger()).toHaveFocus();
  });

  it('a click picks a row', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    fireEvent.click(screen.getByRole('option', { name: 'Insurance' }));
    expect(screen.getByTestId('picked')).toHaveTextContent('insurance');
    expect(screen.getByRole('button', { name: 'Category Insurance' })).toBeInTheDocument();
  });

  it('does not scroll on open, only after the active row moves', () => {
    media(true);
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    wrap(<Harness />);
    fireEvent.click(trigger());
    expect(spy).not.toHaveBeenCalled();
    fireEvent.keyDown(search(), { key: 'ArrowDown' });
    expect(spy).toHaveBeenCalled();
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
  });

  it('a mouse pick on a desktop returns focus to the trigger', () => {
    media(true);
    wrap(<Harness />);
    fireEvent.click(trigger());
    fireEvent.click(screen.getAllByRole('option')[0]);
    expect(trigger()).toHaveFocus();
  });

  it('is one menu at a time', () => {
    media(true);
    wrap(<><Harness /><Harness start="gifts" /></>);
    const [a, b] = screen.getAllByRole('button', { name: /^Category / });
    fireEvent.click(a);
    fireEvent.click(b);
    expect(screen.getAllByRole('listbox')).toHaveLength(1);
    expect(b).toHaveAttribute('aria-expanded', 'true');
    expect(a).toHaveAttribute('aria-expanded', 'false');
  });
});
