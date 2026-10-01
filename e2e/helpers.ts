// Shared plumbing: the seeded identity, signing in through the real login form, the terms
// modal, and skipping with a reason when the stack or the credentials are not there.
//
// WHY A REAL LOGIN
//
// Minty keeps sessions server-side (Flask-Session), so a test cannot forge a cookie the way
// onboarding/e2e mints a JWT. It signs in the way a person does: the /login form with the
// username and password `scripts/e2e_seed.py` set. Nothing is bypassed; the terms gate, the
// CSRF token and the entity list are all exercised on the way in.
//
// TWO SEEDED PEOPLE
//
// The journeys sign in as `e2e-terms@minty.test`, whose Terms the seed accepts. The shared
// `e2e@minty.test` keeps its consent removed and NOTHING ever accepts on it (minty-web's rule):
// 01 only checks that the panel shows for it.

import { expect, test, type Page } from '@playwright/test';
import { BASE_URL } from './urls';

export type Credentials = { email: string; password: string; userId: string; entityId: string };

/** The account the journeys sign in as (Terms accepted), or null when they cannot run. */
export function credentials(): Credentials | null {
  const email = process.env.E2E_MINTY_TERMS_EMAIL;
  const password = process.env.E2E_MINTY_PASSWORD;
  const userId = process.env.E2E_MINTY_TERMS_USER;
  const entityId = process.env.E2E_MINTY_ENTITY;
  if (!email || !password || !userId || !entityId) return null;
  return { email, password, userId, entityId };
}

/** Skip the file unless the seeded identity is configured (see e2e/README.md). */
export function requireCredentials(): Credentials {
  const creds = credentials();
  test.skip(
    !creds,
    'Set E2E_MINTY_TERMS_EMAIL, E2E_MINTY_TERMS_USER, E2E_MINTY_PASSWORD and E2E_MINTY_ENTITY (run scripts/e2e_seed.py --print)',
  );
  return creds as Credentials;
}

/** The shared account that owes the Terms - only ever used to SEE the panel, never to answer it. */
export function requireSharedAccount(): Credentials {
  const email = process.env.E2E_MINTY_EMAIL;
  const password = process.env.E2E_MINTY_PASSWORD;
  const userId = process.env.E2E_MINTY_USER;
  const entityId = process.env.E2E_MINTY_ENTITY;
  const ok = !!(email && password && userId && entityId);
  test.skip(!ok, 'Set E2E_MINTY_EMAIL, E2E_MINTY_USER, E2E_MINTY_PASSWORD and E2E_MINTY_ENTITY (run scripts/e2e_seed.py --print)');
  return { email: email as string, password: password as string, userId: userId as string, entityId: entityId as string };
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
 * The terms panel's tick box, over the entity list when the signed-in person still owes an
 * acceptance: Flask's (templates/legal/_terms_panel.html) or - with the minty-web hub on, where
 * /entity hands over to minty-web's /entities - minty-web's TermsModal over the same question.
 * Either stays disabled until the document has been read to its end.
 */
export function termsTickBox(page: Page) {
  return page
    .locator('#accept-box, [role="dialog"]:has([aria-label="The Terms & Conditions"]) input[type="checkbox"]')
    .first();
}

/**
 * Whether the terms panel shows. The specs never answer it: the journeys' account had its Terms
 * accepted by the seed, so seeing the panel there means the seed did not run.
 */
export async function termsPanelShown(page: Page): Promise<boolean> {
  return termsTickBox(page)
    .waitFor({ state: 'visible', timeout: 2500 })
    .then(() => true, () => false);
}

/** The entity list: Flask's /entity, or minty-web's /entities when the hub is on. */
export const ENTITY_LIST_URL = /\/entit(y|ies)(\/|\?|$)/;

async function failIfTermsOwed(page: Page, creds: Credentials): Promise<void> {
  if (await termsPanelShown(page)) {
    throw new Error(`${creds.email} owes the Terms - run scripts/e2e_seed.py (it accepts them for this account)`);
  }
}

/** Sign in through /login and land on the entity list. */
export async function login(page: Page, creds: Credentials): Promise<void> {
  await page.goto('/login');
  await page.locator('#username').fill(creds.email);
  await page.locator('#password').fill(creds.password);
  await page.locator('#submit').click();
  await page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 15_000 });
  await failIfTermsOwed(page, creds);
}

/** Open the seeded company's dashboard. */
export async function openEntity(page: Page, creds: Credentials): Promise<void> {
  await page.goto(`/entity/${creds.entityId}`);
  await failIfTermsOwed(page, creds);
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
 * The e2e shop is connected to a real Xero organisation (a Demo Company, linked by hand) when
 * ``E2E_XERO=1``: the publish spec runs, and the names below are the organisation's real rows
 * rather than the seed's placeholders (scripts/e2e_seed.py leaves a connected shop's mapping
 * alone). Override any name with its own variable.
 */
export function xeroLive(): boolean {
  return (process.env.E2E_XERO ?? '').trim() === '1';
}

export function fixtures() {
  const live = xeroLive();
  const env = (name: string, dflt: string) => (process.env[name] ?? '').trim() || dflt;
  return {
    /** typed into the supplier search, and the suggestion clicked */
    supplierQuery: env('E2E_SUPPLIER_QUERY', live ? 'ABC' : 'E2E Stationery'),
    supplierName: env('E2E_SUPPLIER', live ? 'ABC Furniture' : 'E2E Stationery Supplier'),
    /**
     * typed into the account search; the suggestion shows the NAME (the code on its own line).
     * The name carries commas on purpose: the receipt's key is minted from it, and a comma
     * inside a key was once read as a separator - two broken halves, "Key not found" previews
     * (fixed 2026-09-18). 445 is Light, Power, Heating in a Demo Company and in the seed.
     */
    accountQuery: env('E2E_EXPENSE_ACCOUNT_QUERY', 'Light'),
    accountName: env('E2E_EXPENSE_ACCOUNT', live ? 'Light, Power, Heating' : 'E2E Light, Power, Heating 445'),
    expenseCode: env('E2E_EXPENSE_ACCOUNT_CODE', '445'),
    /** the code of the account mapped as petty cash: the deposit's movement is booked against it */
    pettyCashCode: env('E2E_PETTY_CASH_CODE', live ? '091' : '090'),
    /** the petty-cash mapping the settings page shows */
    mappingAccounts: live
      ? ['Business Savings Account', 'Business Bank Account', 'Sales', 'Revenue Received in Advance', 'Bank Fees']
      : ['E2E Petty Cash 090', 'E2E Bank 091', 'E2E Cash Sales 200', 'E2E Director Loan 835', 'E2E Cash Discrepancy 499'],
    mappingContacts: live ? ['24 Locks', 'Angelika Tardaguela', '7-Eleven'] : ['E2E Cash Customer', 'E2E Director', 'E2E Discrepancy'],
  };
}

/** A real 1x1 PNG: the browser can decode it, so a receipt that loads has naturalWidth 1. */
export const RECEIPT_PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
  'base64',
);

/**
 * The images under ``within`` that did not load (waited for, then ``naturalWidth`` 0): a
 * receipt whose key the bucket lacks, a static asset that 404s. Data URIs are skipped.
 */
export async function brokenImages(page: Page, within = 'body'): Promise<string[]> {
  return page.evaluate(async (selector) => {
    const images = Array.from(document.querySelectorAll<HTMLImageElement>(`${selector} img`)).filter(
      (img) => img.getAttribute('src') && !img.src.startsWith('data:'),
    );
    await Promise.all(
      images.map((img) =>
        img.complete
          ? Promise.resolve()
          : new Promise<void>((resolve) => {
              img.addEventListener('load', () => resolve(), { once: true });
              img.addEventListener('error', () => resolve(), { once: true });
            }),
      ),
    );
    return images.filter((img) => img.naturalWidth === 0).map((img) => img.src);
  }, within);
}
