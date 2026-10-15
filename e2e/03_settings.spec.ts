// Entity settings in the browser: the petty-cash account mapping, the sales methods editor and
// each card's own Save (Part 15.20b, 2026-10-14), then the Users / Entity & Integration / Module
// tabs' hand-over to minty-web. These pages
// read the tables the redesign reshapes most (sale_info / entity_sale_setting,
// entity_pettycash_settings, entities).
import { expect, test } from '@playwright/test';
import { login, reportDate, requireCredentials, requireStack, fixtures, xeroLive } from './helpers';

// The mapping and the account-code ticks are Xero's: without a live connection (the seed shop,
// unless E2E_XERO=1) Petty Cash Settings shows only "Xero isn't connected" in their place.
const NEEDS_XERO = 'set E2E_XERO=1 against a shop connected to a Xero Demo Company';

test.describe('entity settings', () => {
  let entityId = '';

  test.beforeEach(async ({ page }) => {
    await requireStack();
    const creds = requireCredentials();
    entityId = creds.entityId;
    await login(page, creds);
  });

  test('petty cash settings show the account mapping and the sales methods', async ({ page }) => {
    test.skip(!xeroLive(), NEEDS_XERO);
    await page.goto(`/entity/settings/entity/${entityId}`);
    const body = page.locator('body');
    for (const name of fixtures().mappingAccounts) {
      await expect(body).toContainText(name);
    }
    for (const contact of fixtures().mappingContacts) {
      await expect(body).toContainText(contact);
    }
    // the methods seeded through the real service, grouped by type
    await expect(page.getByRole('heading', { name: 'Electronic' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Delivery' })).toBeVisible();
    for (const method of ['Visa', 'Alipay', 'Foodpanda']) {
      await expect(body).toContainText(method);
    }
    // the account-code tick list the expense form is fed from
    await expect(page.getByRole('checkbox', { name: '429' })).toBeChecked();
  });

  test('without Xero the mapping and the codes only say how to connect it (phone)', async ({ page }) => {
    test.skip(xeroLive(), 'the shop is connected to Xero');
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto(`/entity/settings/entity/${entityId}`);
    const notices = page.getByRole('status').filter({ hasText: "Xero isn't connected." });
    await expect(notices).toHaveCount(2);
    await expect(page.locator('#main_bank_select')).toHaveCount(0);
    await expect(page.locator('#accountCodeList')).toHaveCount(0);
    // the cards that need no Xero stay
    await expect(page.locator('#ci_country_display')).toBeVisible();
    await expect(page.locator('#paymentMethodsList')).toContainText('Visa');
    // each card's Save waits for nothing from Xero: off with nothing changed
    await expect(page.locator('[data-section-save="country"]')).toBeDisabled();
    await expect(page.locator('[data-section-save="electronic"]')).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  });

  test("a card's Save stays off until that card changed, and off again when it is put back (phone)", async ({ page }) => {
    test.skip(!xeroLive(), NEEDS_XERO);
    await page.setViewportSize({ width: 360, height: 780 });
    await page.goto(`/entity/settings/entity/${entityId}`);
    await page.waitForFunction(() => (window as unknown as { xeroDataReady?: boolean }).xeroDataReady === true);
    await expect(page.locator('#paymentMethodsList')).toContainText('Visa');
    const save = page.locator('[data-section-save="codes"]');
    await expect(save).toBeDisabled();
    // a tick turns the codes card's Save on - and only that card's
    const code = page.getByRole('checkbox', { name: '429' });
    await code.uncheck();
    await expect(save).toBeEnabled();
    await expect(page.locator('[data-section-save="mapping"]')).toBeDisabled();
    await code.check();
    await expect(save).toBeDisabled();
    const mappingSave = page.locator('[data-section-save="mapping"]');
    // a mapping picker, which writes its hidden <select> from script (no input event)
    const contact = page.locator('#cashsale_contact_input');
    const saved = await contact.inputValue();
    const other = fixtures().mappingContacts.find((name) => name !== saved) as string;
    for (const [name, enabled] of [[other, true], [saved, false]] as const) {
      await contact.click();
      await page.locator('#cashsaleContactSuggestions').getByText(name, { exact: true }).first().dispatchEvent('mousedown');
      await expect(mappingSave)[enabled ? 'toBeEnabled' : 'toBeDisabled']();
    }
  });

  test('adding an electronic method through the page makes it available to the sales form', async ({ page }) => {
    await page.goto(`/entity/settings/entity/${entityId}`);
    // "Add New Method" under Electronic opens a small form: pick from the catalogue or type a name
    await page.locator('#addMethodBtn').click();
    await expect(page.locator('#addMethodForm')).toBeVisible();
    // the catalogue picker is a searchable input; "Other" reveals the free-text name
    await page.locator('#methodCatalogInput').click();
    await page.locator('#methodCatalogInput').pressSequentially('Octo');
    await expect(page.locator('#methodCatalogSuggestions')).toBeVisible();
    // the rows pick on mousedown (so the input's blur cannot hide them first)
    await page.locator('#methodCatalogSuggestions [data-value="__other__"]').dispatchEvent('mousedown');
    await page.locator('#methodName').fill('Octopus');
    await page.locator('#saveMethodBtn').click();
    await expect(page.locator('body')).toContainText('Octopus');
    // the Electronic card saves its own methods, through the methods API; the page stays
    await page.locator('[data-section-save="electronic"]').click();
    await expect(page.locator('[data-section-save="electronic"]')).toBeDisabled();
    // read back through the JSON the page itself uses
    await expect.poll(async () => {
      const res = await page.request.get(`/api/entities/${entityId}/payment-methods`);
      const body = await res.json();
      return (body.payment_methods as Array<{ name: string; type: string; enabled: boolean }>)
        .filter((m) => m.enabled && m.type === 'electronic') // the sale_type enum word since C3
        .map((m) => m.name);
    }, { timeout: 15_000 }).toContain('Octopus');
    // and the wizard's sales page offers it (the posted report's page still lists every method)
    await page.goto(`/report/sale?entity_id=${entityId}&transaction_date=${reportDate(-1)}`, { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#shop_sales_octopus')).toBeAttached();
  });

  // Users, Entity & Integration and the Module tab are minty-web's since phase 2 (2026-10-05;
  // Flask's Jinja pages are deleted). Their Flask addresses stay as the way there: an old full-id
  // address 308s to the company's own, which hands the browser to minty-web's /landing with a
  // token for the company. Read the redirects rather than following them - the minty-web dev
  // server is not part of this stack. The pages themselves are minty-web's
  // features/company-settings/e2e/12_company_settings.spec.ts (and the subscription feature's 02),
  // their Flask API tests/test_hub_company_settings.py (the rename and every permission).
  for (const [tab, oldPath] of [
    ['users', (id: string) => `/entity/settings/users/${id}`],
    ['integration', (id: string) => `/entity/${id}/settings/xero`],
    ['modules', (id: string) => `/entity/${id}/settings/modules`],
  ] as const) {
    test(`the ${tab} tab hands the browser to minty-web with a token for the company`, async ({ page }) => {
      const shortId = entityId.slice(0, 8);
      const moved = await page.request.get(oldPath(entityId), { maxRedirects: 0 });
      expect(moved.status()).toBe(308);
      const readable = new URL(moved.headers()['location'], page.url() || 'http://localhost').pathname;
      expect(readable).toMatch(new RegExp(`^/entity/${shortId}/[^/]+/settings/${tab}$`));
      const resp = await page.request.get(readable, { maxRedirects: 0 });
      expect(resp.status()).toBe(302);
      const location = new URL(resp.headers()['location']);
      expect(location.pathname).toBe('/landing');
      expect(location.searchParams.get('next')).toMatch(new RegExp(`^/entities/${shortId}/[^/]+/settings/${tab}$`));
      expect(location.searchParams.get('entity_id')).toBe(entityId);
      expect(location.searchParams.get('token')).toBeTruthy();
    });
  }
});
