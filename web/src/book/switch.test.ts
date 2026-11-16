import { describe, expect, it } from 'vitest';
import type { BookSummary } from '../api/types';
import { switchTarget } from './switch';

const book = (slug: string, kind: 'household' | 'parent', role: 'manager' | 'viewer' = 'manager'): BookSummary =>
  ({ slug, name: slug, kind, role, available: true, reason: null, owners: [], profile: null });

describe('switching books', () => {
  it('opens the same screen in the other book', () => {
    expect(switchTarget('/b/ours/transactions', 'ours', book('mom', 'parent'))).toBe('/b/mom/transactions');
    expect(switchTarget('/b/ours/settings/members', 'ours', book('mom', 'parent'))).toBe('/b/mom/settings/members');
    expect(switchTarget('/b/ours', 'ours', book('mom', 'parent'))).toBe('/b/mom');
  });
  it('goes to Home when the other book has no such screen', () => {
    expect(switchTarget('/b/ours/plan', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/setup/pay', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/settings/setup/pay', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/settings/profile/pay', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/taxes', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/business', 'ours', book('mom', 'parent'))).toBe('/b/mom');
    expect(switchTarget('/b/ours/spending/trends', 'ours', book('mom', 'parent'))).toBe('/b/mom');
  });
  it('a Sample has Settings sections only where they work: the others open its Settings', () => {
    const sample: BookSummary = { ...book('sample', 'household'), sample: true };
    for (const s of ['ready', 'members', 'banks', 'import', 'export', 'chat']) {
      expect(switchTarget(`/b/ours/settings/${s}`, 'ours', sample)).toBe('/b/sample/settings');
    }
    expect(switchTarget('/b/ours/settings/banks', 'ours', sample)).toBe('/b/sample/settings');
    expect(switchTarget('/b/ours/settings/rules', 'ours', sample)).toBe('/b/sample/settings/rules');
    expect(switchTarget('/b/ours/spending', 'ours', sample)).toBe('/b/sample/spending');
  });
  it("a household's Accounts goes to a parent book's Inventory, where its accounts are", () => {
    expect(switchTarget('/b/ours/accounts', 'ours', book('mom', 'parent'))).toBe('/b/mom/inventory');
    expect(switchTarget('/b/ours/accounts/3', 'ours', book('mom', 'parent'))).toBe('/b/mom/inventory');
    expect(switchTarget('/b/ours/accounts', 'ours', book('dad', 'household'))).toBe('/b/dad/accounts');
  });
  it("an account's page goes to the other household's Accounts, since the account belongs to one book", () => {
    expect(switchTarget('/b/ours/accounts/5', 'ours', book('kin', 'household'))).toBe('/b/kin/accounts');
    expect(switchTarget('/b/ours/accounts/5', 'ours', book('kin', 'household', 'viewer'))).toBe('/b/kin/accounts');
  });
  it('your own pages, This book and Books open the same in the other book', () => {
    expect(switchTarget('/b/ours/you/devices', 'ours', book('mom', 'parent'))).toBe('/b/mom/you/devices');
    expect(switchTarget('/b/ours/you/appearance', 'ours', book('mom', 'parent', 'viewer'))).toBe('/b/mom/you/appearance');
    expect(switchTarget('/b/ours/settings/book', 'ours', book('mom', 'parent'))).toBe('/b/mom/settings/book');
    expect(switchTarget('/b/ours/settings/books', 'ours', book('mom', 'parent', 'viewer'))).toBe('/b/mom/settings/books');
  });
  it('goes to Settings when a viewer can\'t use that section', () => {
    expect(switchTarget('/b/ours/settings/banks', 'ours', book('mom', 'parent', 'viewer'))).toBe('/b/mom/settings');
    for (const s of ['import', 'members', 'log', 'book', 'chat']) {
      expect(switchTarget(`/b/mom/settings/${s}`, 'mom', book('dad', 'parent', 'viewer'))).toBe('/b/dad/settings');
    }
    for (const s of ['profile', 'business', 'chat']) {
      expect(switchTarget(`/b/ours/settings/${s}`, 'ours', book('kin', 'household', 'viewer'))).toBe('/b/kin/settings');
    }
  });
  it('keeps the inventory to parent books and an item page to its own book', () => {
    expect(switchTarget('/b/mom/inventory', 'mom', book('ours', 'household'))).toBe('/b/ours');
    expect(switchTarget('/b/mom/inventory/12', 'mom', book('dad', 'parent'))).toBe('/b/dad/inventory');
    expect(switchTarget('/b/mom/inventory', 'mom', book('dad', 'parent'))).toBe('/b/dad/inventory');
    expect(switchTarget('/b/mom/settings/changes', 'mom', book('ours', 'household'))).toBe('/b/ours/settings');
    expect(switchTarget('/b/mom/settings/dismissed', 'mom', book('dad', 'parent', 'viewer'))).toBe('/b/dad/settings');
  });
});
