import { expect, test } from '@playwright/test';
import { listView, loginAs, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2). web/e2e/seed_notes.py adds
// three PayPal $13.99 charges (Subscriptions) and one $9.99 one; each test undoes what it saved.
test.beforeAll(async () => { await restoreVault(); });

test.describe('a manager', () => {
  test.beforeEach(async ({ page }) => { await loginAs(page, 'alex'); });

  test('a PayPal note and name reach the other $13.99 rows, read Disney+ (PayPal), and Undo takes them back', async ({ page }) => {
    await page.goto('/transactions?q=DISNEYPLUS&dates=all');
    const rows = page.getByTestId('txn-row');
    await expect(rows).toHaveCount(3);
    await rows.first().click();
    const form = page.getByTestId('note-form');
    const also = form.getByLabel(/^Also the \d+ PayPal \$13\.99 ones$/);
    await expect(also).not.toBeChecked();                                         // a note alone stays on its row
    await expect(form.getByLabel('And future ones')).not.toBeChecked();
    await form.getByLabel('Note').fill('Disney+ subscription');
    await form.getByLabel('Name').fill('Disney+');
    await expect(also).toBeChecked();                                             // a name reaches the rows like it
    await form.getByRole('button', { name: 'Save' }).click();
    const toast = page.getByTestId('undo-toast').filter({ hasText: /^Saved on \d+/ });   // in its page's live region
    await expect(toast).toBeVisible();
    await expect(rows.filter({ hasText: 'Disney+ (PayPal)' })).toHaveCount(3);
    await expect(page.locator('.notes__list').first()).toContainText('Disney+ subscription');      // the open row's notes
    await toast.getByRole('button', { name: 'Undo' }).click();
    await expect(rows.filter({ hasText: 'Disney+ (PayPal)' })).toHaveCount(0);
    await page.goto('/transactions?q=EBAY&dates=all');
    await expect(page.getByTestId('txn-row').first()).not.toContainText('Disney+');
  });

  test('a note from a Review card shows on the card, keeps it in the queue, and Undo takes it away', async ({ page }) => {
    await page.goto('/review');
    await listView(page);
    const id = await page.getByTestId('review-card').first().getAttribute('data-id');
    const card = page.locator(`[data-testid="review-card"][data-id="${id}"]`);
    await card.getByRole('button', { name: 'Note' }).click();
    const form = card.getByTestId('note-form');
    await form.getByLabel('Note').fill('Asked Sam about this one');
    await form.getByRole('button', { name: 'Save' }).click();
    const toast = page.locator('.undo-toast').filter({ hasText: /^Saved/ });
    await expect(toast).toBeVisible();
    await expect(form).toHaveCount(0);                                            // the form closes on save
    const line = card.locator('.notes__list li').filter({ hasText: 'Asked Sam about this one' });
    await expect(line).toHaveText(/^Alex, .+: Asked Sam about this one/);         // on the card at once
    await expect(card).toBeVisible();
    await toast.getByRole('button', { name: 'Undo' }).click();                    // and the vault is as it was
    await expect(toast).toHaveCount(0);
    await expect(line).toHaveCount(0);
  });

  test('a note removed on a Review card says Removed, and Undo puts it back', async ({ page }) => {
    await page.goto('/review');
    await listView(page);
    const id = await page.getByTestId('review-card').first().getAttribute('data-id');
    const card = page.locator(`[data-testid="review-card"][data-id="${id}"]`);
    await card.getByRole('button', { name: 'Note' }).click();
    await card.getByTestId('note-form').getByLabel('Note').fill('Gone and back');
    await card.getByTestId('note-form').getByRole('button', { name: 'Save' }).click();
    const line = card.locator('.notes__list li').filter({ hasText: 'Gone and back' });
    await expect(line).toBeVisible();
    await line.getByRole('button', { name: /^Remove note from / }).click();
    await expect(line).toHaveCount(0);
    const removed = page.locator('.undo-toast').filter({ hasText: /^Removed/ });
    await expect(removed).toBeVisible();
    await removed.getByRole('button', { name: 'Undo' }).click();
    await expect(line).toHaveText(/^Alex, .+: Gone and back/);                      // back on the card
    await line.getByRole('button', { name: /^Remove note from / }).click();      // leave the vault as it was
    await expect(line).toHaveCount(0);
  });
});
