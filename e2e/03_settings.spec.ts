// Entity settings in the browser: the petty-cash account mapping, the sales methods editor,
// users, the Xero page, the module page, and the CSV export. These pages read the tables the
// redesign reshapes most (sale_info / entity_sale_setting, entity_pettycash_settings, entities).
import { expect, test } from '@playwright/test';
import { login, moneyRegex, reportDate, requireCredentials, requireStack, fixtures, xeroLive } from './helpers';

test.describe('entity settings', () => {
  let entityId = '';

  test.beforeEach(async ({ page }) => {
    await requireStack();
    const creds = requireCredentials();
    entityId = creds.entityId;
    await login(page, creds);
  });

  test('petty cash settings show the account mapping and the sales methods', async ({ page }) => {
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
    await page.getByRole('button', { name: /save changes/i }).click();
    await page.waitForLoadState('networkidle');
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

  test('users page lists the member with an edit and a remove action', async ({ page }) => {
    await page.goto(`/entity/settings/users/${entityId}`);
    await expect(page.getByRole('heading', { name: 'User Management' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Eve Tester' })).toBeVisible();
    await expect(page.getByRole('button', { name: /edit user/i }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: /remove user/i }).first()).toBeVisible();
    await expect(page.locator('body')).toContainText(/admin/i);
  });

  test('xero settings page renders the entity name, country/currency and the connection button', async ({ page }) => {
    await page.goto(`/entity/${entityId}/settings/xero`);
    await expect(page.getByRole('textbox', { name: /entity name/i })).toHaveValue('E2E Petty Cash Shop');
    // a shop linked to a Demo Company by hand is Connected and offers Disconnect; the seed's shop is not
    if (xeroLive()) {
      await expect(page.locator('body')).toContainText('Connected');
      await expect(page.getByRole('button', { name: /disconnect from xero/i })).toBeVisible();
    } else {
      await expect(page.getByRole('button', { name: /^connect to xero/i })).toBeVisible();
    }
    await expect(page.getByRole('heading', { name: /country & currency/i })).toBeVisible();
  });

  test('renaming the entity is reflected in the header and reverted', async ({ page }) => {
    await page.goto(`/entity/${entityId}/settings/xero`);
    const name = page.getByRole('textbox', { name: /entity name/i });
    await name.fill('E2E Petty Cash Shop (renamed)');
    await page.getByRole('button', { name: /save changes/i }).click();
    await page.goto(`/entity/${entityId}/settings/xero`);
    await expect(name).toHaveValue('E2E Petty Cash Shop (renamed)');
    await name.fill('E2E Petty Cash Shop');
    await page.getByRole('button', { name: /save changes/i }).click();
    await page.goto(`/entity/${entityId}/settings/xero`);
    await expect(name).toHaveValue('E2E Petty Cash Shop');
  });

  test('the Module tab hands the browser to minty-web with a token for the company', async ({ page }) => {
    // Flask's Jinja module page was deleted on 2026-10-01: the address is a hand-over to
    // minty-web's Module page. Read the redirect itself rather than following it - the
    // minty-web dev server is not part of this stack.
    const resp = await page.request.get(`/entity/settings/module/${entityId}`, { maxRedirects: 0 });
    expect(resp.status()).toBe(302);
    const location = new URL(resp.headers()['location']);
    expect(location.pathname).toBe('/landing');
    expect(location.searchParams.get('next')).toBe(`/subscription/entities/${entityId}/modules`);
    expect(location.searchParams.get('entity_id')).toBe(entityId);
    expect(location.searchParams.get('token')).toBeTruthy();
  });

  test('history CSV lists the posted day as movements', async ({ page }) => {
    const day = reportDate(-1);
    const res = await page.request.get(`/entity/${entityId}/reports/download-csv?start_date=${day}&end_date=${day}`);
    expect(res.status()).toBe(200);
    const text = await res.text();
    const rows = text.split(/\r?\n/).filter((r) => r.trim());
    expect(rows[0]).toMatch(/^Date,Account Code,Amount/);
    // one line per movement of the report the wizard spec posted: the float added at the
    // start (director account 835), the expense by its remark and account code (445), the
    // cash sale (200) and the deposit, booked against the petty cash account (090 on the
    // seed's mapping, 091 on the Demo Company's)
    expect(text).toMatch(/Cash Addition/);
    expect(text).toMatch(new RegExp(`,${fixtures().expenseCode},-25\\.1,Tape`));
    expect(text).toMatch(/,200,300\.1,Cash Sale/);
    expect(text).toMatch(new RegExp(`,${fixtures().pettyCashCode},-500\\.0,Bank Deposit`));
  });
});
