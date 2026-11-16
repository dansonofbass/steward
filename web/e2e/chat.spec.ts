import { expect, test, type Page } from '@playwright/test';
import { animationsSettled, CHAT_PW, chatOn, chatShot, DEMO, GATEWAY, listView, loginAs, tab, waitForGateway, restoreVault } from './fixtures';

// The demo household as server.sh seeded it, whatever ran before (flaky-test audit E2).
test.beforeAll(async () => { await restoreVault(); });

// Spec 11.5, against the fake gateway (web/e2e/fake_gateway.py). Never the real API.
const who = (name: 'cass' | 'dee', project: string) => `${name}-${project}`;

// Each Playwright project has its own seeded parent book, "Margaret Ellis (Seed phone)" or "(Seed desktop)".
async function seedSlug(page: Page, project: string): Promise<string> {
  const books = (await (await page.request.get('/api/books')).json()).books as { slug: string; name: string }[];
  return books.find((b) => b.name === `Margaret Ellis (Seed ${project})`)!.slug;
}

async function openAsk(page: Page) {
  await page.goto('/b/ours');
  await tab(page, 'Ask').click();
  await expect(page.getByRole('heading', { name: 'Ask about Ours' })).toBeVisible();
}

async function send(page: Page, question: string) {
  await page.getByLabel('Your question').fill(question);
  await expect(page.locator('.willsend__text').first()).not.toHaveText('…');
  await page.getByRole('button', { name: 'Send' }).last().click();
}

test.beforeAll(async ({ request }) => {
  await request.post(`${GATEWAY}/__e2e/reset`);
});

test.afterAll(async ({ browser }, info) => {
  const page = await browser.newPage();
  await loginAs(page, 'alex', DEMO.alex);
  await chatOn(page, 'ours', false);
  await chatOn(page, await seedSlug(page, info.project.name), false);
  await page.request.post(`${GATEWAY}/__e2e/reset`);
  await page.close();
});

test('a manager turns chat on after reading the disclosure', async ({ page }, info) => {
  await loginAs(page, who('cass', info.project.name), CHAT_PW);
  await chatOn(page, 'ours', false);
  await page.goto('/b/ours/settings/chat');
  const sw = page.getByRole('switch', { name: 'Chat in Ours' });
  await sw.click();
  const sheet = page.getByRole('dialog');
  await expect(sheet.getByText('Turn on chat in Ours?')).toBeVisible();
  await expect(sheet).toContainText('Steward sends Claude, an AI made by Anthropic');
  await sheet.getByRole('button', { name: 'Turn on' }).click();
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await expect(tab(page, 'Ask')).toBeVisible();
  await chatShot(page, info.project.name, 'settings-chat');
});

test('each person sees the disclosure once, the first time they open Ask', async ({ page }, info) => {
  await loginAs(page, who('cass', info.project.name), CHAT_PW);
  await chatOn(page, 'ours');
  await loginAs(page, who('dee', info.project.name), CHAT_PW);
  await page.goto('/b/ours/ask');
  await expect(page.getByRole('heading', { name: 'Before you ask' })).toBeVisible();
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(page.getByText('Ask about the money in Ours')).toBeVisible();
  await page.reload();
  await expect(page.getByText('Ask about the money in Ours')).toBeVisible();
  await chatShot(page, info.project.name, 'ask-empty');
});

test.describe('asking', () => {
  test.beforeEach(async ({ page }, info) => {
    await loginAs(page, who('cass', info.project.name), CHAT_PW);
    await chatOn(page, 'ours');
  });

  // With chat on, each Review card's actions gain Ask; the row wraps and the grid's column never grows past the
  // screen, so Review's list never scrolls sideways on a phone or a desktop.
  test('Review with Ask on every card never scrolls sideways', async ({ page }) => {
    for (const size of [{ width: 390, height: 844 }, { width: 1280, height: 800 }]) {
      await page.setViewportSize(size);
      await page.goto('/b/ours/review');
      await listView(page);
      await page.getByTestId('review-card').first().waitFor();
      await expect(page.getByTestId('review-card').first().getByRole('button', { name: /Ask/ })).toBeVisible();
      const { scroll, inner } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: document.documentElement.clientWidth }));
      expect(scroll, `Review at ${size.width} scrolls sideways`).toBeLessThanOrEqual(inner);
    }
  });

  test('the preview shows replaced names, and a model guess is shown before sending', async ({ page }, info) => {
    await openAsk(page);
    await page.getByLabel('Your question').fill('Can Sam and I cover a year on one income?');
    const chip = page.locator('.tok', { hasText: 'Person 2' }).first();
    await expect(chip).toBeVisible();
    await chip.click();
    await expect(page.locator('.tok-pop')).toContainText('Claude gets "Person 2"');
    await page.getByLabel('Your question').fill('Can Sam pay Bright Smile Ortho $6,400 from savings?');
    await expect(page.locator('.tok--model', { hasText: '[organization]' }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Send' }).click();
    const card = page.getByRole('group', { name: 'What Claude will see' });
    await expect(card).toContainText("Zebra-Box's check took out 1 part");
    await chatShot(page, info.project.name, 'will-send');
    await card.getByRole('button', { name: 'Send' }).click();
    await expect(page.locator('.amsg__meta').last()).toContainText(/second/);
  });

  test('an answer shows its steps, names with the alias, What Claude saw, and the cost', async ({ page }, info) => {
    await openAsk(page);
    await send(page, 'Are we spending more on dining than last year?');
    await expect(page.getByText('Looked at spending by category')).toBeVisible();
    await expect(page.getByRole('button', { name: /Sent as Person 2/ })).toBeVisible();
    await expect(page.locator('.amsg__meta').last()).toContainText(/\$0\.\d\d|less than \$0\.01/);
    await chatShot(page, info.project.name, 'conversation');
    await page.getByRole('button', { name: /What Claude saw \(1\)/ }).click();
    await expect(page.getByText('Spending by category', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /Show what was sent/ }).click();
    await expect(page.locator('pre.json')).toContainText('"period"');
  });

  test('store names: approved for this conversation, and declined', async ({ page }, info) => {
    await openAsk(page);
    await send(page, 'Which subscriptions did we add this year?');
    const card = page.getByRole('group', { name: 'Claude asks for store names' });
    await expect(card).toContainText('Totals show the monthly payments but not what they are.');
    await expect(page.getByLabel('Your question')).toBeDisabled();
    await chatShot(page, info.project.name, 'store-names-manager');
    await card.getByRole('button', { name: 'Approve for this conversation' }).click();
    await expect(page.getByText(/Cass approved \d+ store rows? for this conversation\./)).toBeVisible();
    await expect(page.getByText('Here they are by store, from the rows you approved.')).toBeVisible();

    await page.getByRole('button', { name: 'New' }).click();
    await send(page, 'Which subscriptions did we add this year?');
    await page.getByRole('group', { name: 'Claude asks for store names' }).getByRole('button', { name: "Don't send" }).click();
    await expect(page.getByText("Store names weren't sent. Claude answered from totals.")).toBeVisible();
    await expect(page.getByText(/^From totals:/)).toBeVisible();

    await page.goto('/b/ours/settings/chat/sent');
    await expect(page.getByRole('button', { name: /store rows?, approved by Cass/ }).first()).toBeVisible();
  });

  test('the log of what was sent matches the turn', async ({ page }, info) => {
    await openAsk(page);
    await send(page, 'Can Sam and I cover a year on one income?');
    await expect(page.locator('.amsg__meta').last()).toBeVisible();
    await page.getByRole('link', { name: "What's sent" }).click();
    const row = page.getByRole('button', { name: /Question, with 1 part replaced/ }).first();
    await expect(row).toContainText('Cass');
    await chatShot(page, info.project.name, 'sent-log-list');
    await row.click();
    await expect(page.locator('pre.chat__json').first()).toContainText('Can Person 2 and I cover a year on one income?');
    await expect(page.locator('pre.chat__json').first()).not.toContainText('Sam');
    await chatShot(page, info.project.name, 'sent-log-detail');
  });

  test('History lists the conversation and Delete keeps the log', async ({ page }) => {
    await openAsk(page);
    await send(page, 'How much is in savings this month?');
    await expect(page.locator('.amsg__meta').last()).toBeVisible();
    await page.getByRole('button', { name: 'History' }).click();
    await expect(page.getByRole('heading', { name: 'Your conversations' })).toBeVisible();
    const title = page.getByRole('button', { name: 'How much is in savings this' }).first();
    await expect(title).toBeVisible();
    await page.getByRole('button', { name: /^Delete How much is in savings this/ }).first().click();
    await page.getByRole('dialog').getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
  });

  test('Ask is a tab page: the tabs stay, with Ask current, and there is nothing to close', async ({ page }) => {
    await openAsk(page);
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible();
    await expect(tab(page, 'Ask')).toHaveAttribute('aria-current', 'page');
    await expect(page.locator('.behind')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Close' })).toHaveCount(0);
  });

  // On a desktop the Ask column sits in the middle of the content area beside the rail, as every other page does.
  test('on a desktop the Ask column is centred beside the rail', async ({ page, isMobile }) => {
    test.skip(isMobile, 'the rail and the content area are the desktop layout');
    await openAsk(page);
    for (const size of [{ width: 1600, height: 900 }, { width: 1280, height: 800 }]) {
      await page.setViewportSize(size);
      const gaps = () => page.evaluate(() => {
        const main = document.querySelector('.app__main')!;
        const pad = getComputedStyle(main);
        const m = main.getBoundingClientRect();
        const a = document.querySelector('.askp')!.getBoundingClientRect();
        return { left: a.left - (m.left + parseFloat(pad.paddingLeft)), right: m.right - parseFloat(pad.paddingRight) - a.right };
      });
      await expect.poll(async () => { const g = await gaps(); return Math.abs(g.left - g.right); },
        { message: `at ${size.width}: ${JSON.stringify(await gaps())}` }).toBeLessThanOrEqual(2);
    }
  });

  test('Ask about this: the panel on Eating out answers there, Open in Ask carries it to the tab, and the log shows the line', async ({ page }, info) => {
    const { month } = (await (await page.request.get('/api/b/ours/spending')).json()) as { month: string };
    const words = new Date(Number(month.slice(0, 4)), Number(month.slice(5, 7)) - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    const line = `It's about Eating out (category dining) in ${words}.`;
    await page.goto(`/b/ours/spending/dining?month=${month}`);
    await page.getByRole('button', { name: 'Ask about Eating out' }).click();
    const panel = page.getByRole('dialog', { name: 'Ask' });
    await expect(panel.locator('.ask-chip')).toHaveText(/^About: Eating out · /);
    await expect(panel.getByLabel('Your question')).toBeFocused();
    await expect(panel.locator('.willsend')).toContainText(line);
    await panel.getByRole('button', { name: 'Got it' }).click();             // a fresh browser: the first-use tip shows once
    await panel.getByRole('button', { name: 'Is this higher than usual?' }).click();
    await expect(panel.getByLabel('Your question')).toHaveValue('Is this higher than usual?');
    await expect(panel.locator('.willsend__text').last()).not.toHaveText('…');
    await panel.getByRole('button', { name: 'Send' }).click();
    await expect(panel.locator('.amsg__meta').last()).toContainText(/second/);
    await expect(page).toHaveURL(new RegExp(`/b/ours/spending/dining\\?month=${month}$`));   // still on the category page
    await animationsSettled(page);
    await chatShot(page, info.project.name, 'ask-panel');
    await panel.getByRole('button', { name: 'Open in Ask' }).click();
    await expect(page).toHaveURL(new RegExp(`/b/ours/ask/c/\\d+\\?about=category:dining:${month}$`));
    await expect(page.locator('.ask-chip')).toHaveText(/^About: Eating out · /);
    await expect(page.locator('.qabout').first()).toHaveText(/^About: Eating out · /);
    const { requests } = (await (await page.request.get('/api/b/ours/chat/sent')).json()) as { requests: { key: string }[] };
    await page.goto(`/b/ours/settings/chat/sent?open=${encodeURIComponent(requests[0].key)}`);
    await expect(page.getByText("Today's date, who is asking and what it's about")).toBeVisible();
    await expect(page.getByRole('main')).toContainText(line);
  });

  test('with chat off, an account page has no Ask button', async ({ page }) => {
    await chatOn(page, 'ours', false);
    const { accounts } = (await (await page.request.get('/api/b/ours/accounts')).json()) as { accounts: { id: number; name: string; type: string }[] };
    const checking = accounts.find((a) => a.type === 'checking')!;
    await page.goto(`/b/ours/accounts/${checking.id}`);
    await expect(page.getByRole('heading', { level: 1, name: checking.name })).toBeVisible();
    await expect(page.locator('.ask-about')).toHaveCount(0);
  });
});

test('a viewer in a parent book asks and is answered from totals', async ({ page }, info) => {
  await loginAs(page, 'alex', DEMO.alex);
  const slug = await seedSlug(page, info.project.name);
  await chatOn(page, slug);
  await loginAs(page, `vee-${info.project.name}`, 'pw-viewer-demo-2026');
  await page.goto(`/b/${slug}/ask`);
  const start = page.getByRole('button', { name: 'Start' });
  const viewerLine = page.getByText("You're a viewer in this book. You can ask; a manager approves store and payee names.");
  await start.click(); // Vee is new for each project and has not seen the disclosure; it loads after the page, so click waits for it
  await expect(viewerLine).toBeVisible();
  await send(page, 'Is there anything odd this month?');
  await expect(page.getByText("Store and payee names need a manager's OK, so Claude answered from totals.")).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve for this conversation' })).toHaveCount(0);
  await expect(page.getByText(/^From totals:/)).toBeVisible();
  await chatShot(page, info.project.name, 'viewer-parent-book');
});

test.describe('when the gateway is off or the budget is used up', () => {
  test.setTimeout(60_000);
  test.afterEach(async ({ page, request }) => {
    await request.post(`${GATEWAY}/__e2e/reset`);
    // The NAS keeps the gateway's last answer for up to 10 seconds; the next test must not see this one's state.
    await waitForGateway(page, 'ours', (s) => s.gateway.state === 'ok' && !s.budget?.cap_line);
  });

  test('the gateway off: chat says so and the box is paused', async ({ page, request }, info) => {
    await loginAs(page, who('cass', info.project.name), CHAT_PW);
    await chatOn(page, 'ours');
    await request.post(`${GATEWAY}/__e2e/away`, { data: { away: true } });
    await waitForGateway(page, 'ours', (s) => s.gateway.state === 'away');
    await openAsk(page);
    await expect(page.getByRole('heading', { name: 'Chat needs Zebra-Box' })).toBeVisible();
    await expect(page.getByLabel('Your question')).toBeDisabled();
    await expect(page.getByLabel('Your question')).toHaveAttribute('placeholder', 'Paused until Zebra-Box answers');
    await chatShot(page, info.project.name, 'pc-off');
  });

  test('the cap reached: chat stops and says when it starts again', async ({ page, request }, info) => {
    await loginAs(page, who('cass', info.project.name), CHAT_PW);
    await chatOn(page, 'ours');
    await request.post(`${GATEWAY}/__e2e/spend`, { data: { cents: 1000 } });
    await waitForGateway(page, 'ours', (s) => !!s.budget?.cap_line);
    await openAsk(page);
    await expect(page.getByRole('heading', { name: "This month's budget is used up" })).toBeVisible();
    await expect(page.getByText(/This month's chat budget of \$10 is used up\. Chat starts again on/)).toBeVisible();
    await expect(page.getByLabel('Your question')).toBeDisabled();
    await chatShot(page, info.project.name, 'budget-used-up');
  });
});
