// Signing in, the terms modal, the entity list. Every other spec depends on this working.
import { expect, test } from '@playwright/test';
import { acceptTermsIfShown, login, requireCredentials, requireStack } from './helpers';

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

  test('first sign-in shows the terms, accepting them opens the entity list', async ({ page }) => {
    // scripts/e2e_seed.py removes the seeded user's consent, so this run sees the modal.
    const creds = requireCredentials();
    await page.goto('/login');
    await page.locator('#username').fill(creds.email);
    await page.locator('#password').fill(creds.password);
    await page.locator('#submit').click();
    await page.waitForURL((u) => !u.pathname.endsWith('/login'));
    const shown = await acceptTermsIfShown(page);
    test.info().annotations.push({ type: 'terms-modal', description: shown ? 'shown and accepted' : 'already accepted' });
    await expect(page).toHaveURL(/\/entity/);
    await expect(page.getByText('E2E Petty Cash Shop')).toBeVisible();
  });

  test('a signed-in user reaches the company dashboard', async ({ page }) => {
    const creds = requireCredentials();
    await login(page, creds);
    await page.goto(`/entity/${creds.entityId}`);
    await expect(page).toHaveURL(new RegExp(`/entity/${creds.entityId}`));
    // the dashboard: initials in the header, the wizard entry point, the quick actions
    await expect(page.getByRole('button', { name: /start new report/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /view history/i })).toBeVisible();
    await expect(page.getByRole('link', { name: /entity settings/i })).toBeVisible();
  });
});
