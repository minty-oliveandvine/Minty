// Shared plumbing: the seeded identity, signing in through the real login form, the terms
// modal, and skipping with a reason when the stack or the credentials are not there.
//
// WHY A REAL LOGIN
//
// Minty keeps sessions server-side (Flask-Session), so a test cannot forge a cookie the way
// onboarding/e2e mints a JWT. It signs in the way a person does: the /login form with the
// username and password `scripts/e2e_seed.py` set. Nothing is bypassed; the terms gate, the
// CSRF token and the entity list are all exercised on the way in.

import { expect, test, type Page } from '@playwright/test';
import { BASE_URL } from './urls';

export type Credentials = { email: string; password: string; userId: string; entityId: string };

/** Credentials from the environment, or null when the authenticated specs cannot run. */
export function credentials(): Credentials | null {
  const email = process.env.E2E_MINTY_EMAIL;
  const password = process.env.E2E_MINTY_PASSWORD;
  const userId = process.env.E2E_MINTY_USER;
  const entityId = process.env.E2E_MINTY_ENTITY;
  if (!email || !password || !userId || !entityId) return null;
  return { email, password, userId, entityId };
}

/** Skip the file unless the seeded identity is configured (see e2e/README.md). */
export function requireCredentials(): Credentials {
  const creds = credentials();
  test.skip(
    !creds,
    'Set E2E_MINTY_EMAIL, E2E_MINTY_PASSWORD, E2E_MINTY_USER and E2E_MINTY_ENTITY (run scripts/e2e_seed.py --print)',
  );
  return creds as Credentials;
}

/** True when Flask answers -- used to skip with a reason instead of timing out. */
export async function reachable(url = `${BASE_URL}/login`): Promise<boolean> {
  try {
    const res = await fetch(url, { redirect: 'manual' });
    return res.status > 0 && res.status < 500;
  } catch {
    return false;
  }
}

export async function requireStack(): Promise<void> {
  test.skip(!(await reachable()), `Flask is not answering at ${BASE_URL}`);
}

/**
 * The terms modal, when the signed-in person still owes an acceptance. It renders over the
 * entity list (templates/legal/_terms_panel.html); the tick box unlocks only once the document
 * has been scrolled to its end, so the test scrolls it the way a reader would. Server-side
 * enforcement lives in blueprints/legal/routes/gate.py. Returns true when it was accepted.
 */
export async function acceptTermsIfShown(page: Page): Promise<boolean> {
  const box = page.locator('#accept-box');
  if (!(await box.isVisible({ timeout: 1500 }).catch(() => false))) return false;
  const doc = page.locator('.tc-doc');
  await doc.evaluate((el) => { el.scrollTop = el.scrollHeight; el.dispatchEvent(new Event('scroll')); });
  await expect(box).toBeEnabled({ timeout: 5000 });
  await box.check();
  await page.locator('#accept-submit').click();
  await expect(page.locator('.tc-modal-backdrop')).toBeHidden({ timeout: 10_000 });
  return true;
}

/** Sign in through /login and land on the entity list, accepting the terms if asked. */
export async function login(page: Page, creds: Credentials): Promise<void> {
  await page.goto('/login');
  await page.locator('#username').fill(creds.email);
  await page.locator('#password').fill(creds.password);
  await page.locator('#submit').click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15_000 });
  await acceptTermsIfShown(page);
}

/** Open the seeded company's dashboard. */
export async function openEntity(page: Page, creds: Credentials): Promise<void> {
  await page.goto(`/entity/${creds.entityId}`);
  await acceptTermsIfShown(page);
  await expect(page).toHaveURL(new RegExp(`/entity/${creds.entityId}`));
}

/** Yesterday in Hong Kong, the latest date the wizard accepts for a brand-new first report. */
export function reportDate(offsetDays = -1): string {
  const now = new Date(Date.now() + 8 * 3600 * 1000 + offsetDays * 86_400_000);
  return now.toISOString().slice(0, 10);
}

/** Money as the pages print it; tolerant of one or two decimals and thousands separators. */
export function moneyRegex(amount: number): RegExp {
  const fixed2 = amount.toFixed(2);
  const fixed1 = amount.toFixed(1);
  const withCommas = fixed2.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return new RegExp([fixed2, fixed1, withCommas].map((s) => s.replace('.', '\\.')).join('|'));
}

/**
 * The mode the stack under test runs in. ``E2E_SUBSCRIPTIONS=0`` says the backends were
 * started with ``SUBSCRIPTION_ENABLED=0`` (subscriptions dark, the cutover state); unset
 * or ``1`` means live. Specs that show different screens in the two states branch on it.
 */
export function subscriptionsDark(): boolean {
  const raw = (process.env.E2E_SUBSCRIPTIONS ?? '1').trim().toLowerCase();
  return raw === '0' || raw === 'false' || raw === 'off';
}
