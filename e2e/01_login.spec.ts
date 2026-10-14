// Signing in, the terms modal, the entity list. Every other spec depends on this working.
//
// The terms modal is MINTY-WEB's (its components/ui/TermsModal), over its /entities: /entity has
// handed the browser there since phase 2, and since 2026-10-12 minty-web holds the documents
// too, so there is no Flask panel to fall back on. This spec therefore needs minty-web running -
// requireStack() only probes Flask, so a failure here with Flask green means minty-web is down.
import { expect, test } from '@playwright/test';
import { ENTITY_LIST_URL, login, requireCredentials, requireSharedAccount, requireStack, termsTickBox } from './helpers';

test.describe('login and terms', () => {
  test.beforeEach(async () => {
    await requireStack();
  });

  test('the login page renders its form', async ({ page }) => {
    await page.goto('/login');
    await expect(page.locator('#username')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
  });

  test('a wrong password stays on the login page', async ({ page }) => {
    const creds = requireCredentials();
    await page.goto('/login');
    await page.locator('#username').fill(creds.email);
    await page.locator('#password').fill('definitely-not-it');
    await page.locator('#submit').click();
    await expect(page).toHaveURL(/\/login/);
  });

  test('a person who owes the terms sees them over the entity list (never answered here)', async ({ page }) => {
    // scripts/e2e_seed.py removes the shared account's consent, so it owes the Terms. Nothing
    // may accept on it (minty-web's rule): the panel is checked, then the page is left as it is.
    // The panel is minty-web's, drawing a document minty-web holds.
    const creds = requireSharedAccount();
    await page.goto('/login');
    await page.locator('#username').fill(creds.email);
    await page.locator('#password').fill(creds.password);
    await page.locator('#submit').click();
    await page.waitForURL((u) => !u.pathname.endsWith('/login'));
    await expect(page).toHaveURL(ENTITY_LIST_URL);
    // the tick box shows, locked until the document has been read to its end
    await expect(termsTickBox(page)).toBeVisible({ timeout: 10_000 });
    await expect(termsTickBox(page)).toBeDisabled();
  });

  test('a person whose terms are accepted lands on the entity list', async ({ page }) => {
    const creds = requireCredentials();
    await login(page, creds);
    await expect(page).toHaveURL(ENTITY_LIST_URL);
    await expect(page.getByText('E2E Petty Cash Shop').first()).toBeVisible();
  });

  test('a signed-in user reaches the company dashboard', async ({ page }) => {
    const creds = requireCredentials();
    await login(page, creds);
    await page.goto(`/entity/${creds.entityId}`);
    // the full id moves to the company's own address, /entity/<shortid>/<name>/petty-cash (2026-10-05)
    await expect(page).toHaveURL(new RegExp(`/entity/${creds.entityId.slice(0, 8)}/[^/?]+/petty-cash$`));
    // the launch page (Part 15.6a): "Petty Cash", the work card's one Primary (the seed wipes the
    // shop's reports, so it is a first use), and the recent reports; the calendar and Quick
    // Actions are gone - history and settings are in the sidebar
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Petty Cash');
    await expect(page.getByRole('link', { name: /start today's daily closing/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Recent reports' })).toBeVisible();
    await expect(page.locator('[data-sidebar-open="menu"]')).toBeVisible();
  });
});
